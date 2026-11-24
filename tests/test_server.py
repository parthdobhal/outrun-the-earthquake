"""Tests for the warning server: pre-filter, locator, silence check, alert rule,
warning times and the data wall at run time.

Most tests build reports by hand from the server's own model, so the expected
answer is known exactly. Integration tests use the full simulation."""

import json
import math

import numpy as np
import pytest

from outrun.server.config import ServerConfig
from outrun.server.decide import alert_rule, first_alert_snapshot, run_server
from outrun.server.locator import locate
from outrun.server.messages import ReportMessage
from outrun.server.prefilter import compatibility_matrix, select_candidates
from outrun.server.silence import CellCounts, silence_check
from outrun.server.warn import predicted_blind_radius_km, predicted_warning_s
from outrun.sim.reports import active_phone_counts, generate_reports
from outrun.sim.world import generate_world

CFG = ServerConfig()


def synthetic(points, source=(100.0, 100.0), t0=2.0, cfg=CFG):
    """Exact detection times at the given cells under the server's own model."""
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    t = t0 + np.sqrt((x - source[0]) ** 2 + (y - source[1]) ** 2 + cfg.depth_km ** 2) / cfg.vp_km_s
    return np.arange(len(points)), x, y, t


def ring(n, radius, centre=(100.0, 100.0)):
    return [(centre[0] + radius * math.cos(2 * math.pi * i / n),
             centre[1] + radius * math.sin(2 * math.pi * i / n)) for i in range(n)]


# ---------------------------------------------------------------------------
# Locator
# ---------------------------------------------------------------------------


def test_locator_recovers_source_from_exact_surrounding_reports():
    ids, x, y, t = synthetic(ring(8, 20.0), source=(103.0, 97.0), t0=2.5)
    e = locate(ids, x, y, t, CFG)
    assert math.hypot(e.x_km - 103.0, e.y_km - 97.0) < 0.1
    assert abs(e.origin_time_s - 2.5) < 0.01
    assert e.inlier_count == 8 and e.valid and not e.ambiguous


def test_locator_needs_at_least_four_reports():
    ids, x, y, t = synthetic(ring(3, 20.0))
    with pytest.raises(ValueError):
        locate(ids, x, y, t, CFG)


def test_locator_rejects_false_reports_as_outliers():
    rng = np.random.default_rng(1)
    ids, x, y, t = synthetic(ring(30, 25.0), source=(100.0, 100.0), t0=2.0)
    t = t + rng.normal(0, 0.1, len(t))
    fx = rng.uniform(0, 200, 15); fy = rng.uniform(0, 200, 15); ft = rng.uniform(-20, 20, 15)
    all_ids = np.arange(45)
    e = locate(all_ids, np.concatenate([x, fx]), np.concatenate([y, fy]),
               np.concatenate([t, ft]), CFG)
    assert math.hypot(e.x_km - 100.0, e.y_km - 100.0) < 1.0
    # Every false report that genuinely disagrees with the true quake (by more
    # than 0.5 s) must be rejected. A random report can, by chance, land on
    # exactly the time a real one would have; nothing could tell those apart,
    # and they do no harm.
    true_t = 2.0 + np.sqrt((fx - 100.0) ** 2 + (fy - 100.0) ** 2 + CFG.depth_km ** 2) / CFG.vp_km_s
    disagreeing = {30 + i for i in range(15) if abs(ft[i] - true_t[i]) > 0.5}
    assert len(disagreeing) >= 12
    assert disagreeing.isdisjoint(e.inlier_ids)


def test_a_few_false_reports_cannot_drag_the_fit_away():
    """Regression: least squares used to start from ALL reports, so three false
    reports pulled the answer 67 km away."""
    ids, x, y, t = synthetic(ring(60, 6.0, centre=(150.0, 105.0)), source=(150.0, 105.0), t0=3.0)
    e = locate(np.arange(63), np.concatenate([x, [73.0, 81.0, 67.0]]),
               np.concatenate([y, [47.0, 51.0, 143.0]]), np.concatenate([t, [0.8, 2.3, 3.6]]), CFG)
    assert math.hypot(e.x_km - 150.0, e.y_km - 105.0) < 1.0


def test_estimate_stays_inside_search_region_when_reports_are_clustered():
    """Regression: reports from one tiny area once sent the estimate 10,000 km away."""
    ids, x, y, t = synthetic([(150.0 + 0.5 * i, 105.0 + 0.3 * (i % 3)) for i in range(10)],
                             source=(150.0, 105.0))
    e = locate(ids, x, y, t + np.linspace(0, 0.4, 10), CFG)
    m = CFG.search_margin_km
    assert -m <= e.x_km <= CFG.region_width_km + m and -m <= e.y_km <= CFG.region_height_km + m


def test_one_sided_reports_give_large_gap_and_no_alert():
    # Reports only in a small arc north of a source 60 km away.
    points = [(100.0 + 8 * math.cos(a), 160.0 + 8 * math.sin(a)) for a in np.linspace(0, 6.2, 25)]
    ids, x, y, t = synthetic(points, source=(100.0, 100.0))
    e = locate(ids, x, y, t, CFG)
    assert e.gap_deg > CFG.gap_max_deg or e.predicted_error_km > CFG.predicted_error_max_km
    assert not alert_rule(e, 10, CFG)


def test_reports_along_a_line_are_flagged_ambiguous():
    points = [(40.0 + 5 * i, 100.0) for i in range(25)]  # a straight road
    ids, x, y, t = synthetic(points, source=(100.0, 130.0))
    e = locate(ids, x, y, t, CFG)
    assert e.ambiguous  # the mirror image at (100, 70) fits equally well
    assert not alert_rule(e, 10, CFG)


def test_predicted_error_grows_with_timing_noise():
    rng = np.random.default_rng(3)
    ids, x, y, t = synthetic(ring(30, 25.0))
    quiet = locate(ids, x, y, t + rng.normal(0, 0.05, 30), CFG)
    noisy = locate(ids, x, y, t + rng.normal(0, 0.4, 30), CFG)
    assert noisy.predicted_error_km > quiet.predicted_error_km
    assert noisy.rms_s > quiet.rms_s


# ---------------------------------------------------------------------------
# Pre-filter
# ---------------------------------------------------------------------------


def test_prefilter_rejects_pair_needing_speed_above_p():
    x = np.array([0.0, 6.0]); y = np.array([0.0, 0.0])
    # 6 km apart: the P-wave needs 1 s; with 1 s slack, a gap above 2 s is impossible.
    assert compatibility_matrix(x, y, np.array([0.0, 1.9]), 6.0, 1.0)[0, 1]
    assert not compatibility_matrix(x, y, np.array([0.0, 2.1]), 6.0, 1.0)[0, 1]


def test_prefilter_keeps_genuine_reports_and_drops_some_random_ones():
    """The pre-filter is only a cheap first pass: distant reports are allowed
    large time gaps, so many random reports still pass. The locator's outlier
    rejection removes the rest (see the outlier tests)."""
    ids, x, y, t = synthetic(ring(20, 10.0))
    rng = np.random.default_rng(5)
    fx, fy, ft = rng.uniform(0, 200, 20), rng.uniform(0, 200, 20), rng.uniform(-50, 50, 20)
    chosen = select_candidates(np.concatenate([x, fx]), np.concatenate([y, fy]),
                               np.concatenate([t, ft]), 6.0, 1.0)
    assert set(range(20)) <= set(chosen.tolist())
    assert len(set(chosen.tolist()) & set(range(20, 40))) < 20


# ---------------------------------------------------------------------------
# Silent-phones check
# ---------------------------------------------------------------------------


def test_silence_check_rejects_estimate_whose_nearby_phones_are_silent():
    e = locate(*synthetic(ring(8, 20.0)), CFG)
    cells = CellCounts([{"cell_x_km": 101.0, "cell_y_km": 101.0, "phones": 30}])
    expected, actual, ok = silence_check(e, now_s=30.0, cells=cells, window_messages=[], cfg=CFG)
    assert (expected, actual, ok) == (30, 0, False)


def test_silence_check_passes_when_nearby_phones_reported():
    e = locate(*synthetic(ring(8, 20.0)), CFG)
    cells = CellCounts([{"cell_x_km": 101.0, "cell_y_km": 101.0, "phones": 30}])
    reports = [ReportMessage(i, 101.0, 101.0, 3.0, 4.0) for i in range(20)]
    assert silence_check(e, 30.0, cells, reports, CFG) == (30, 20, True)


def test_silence_check_waits_until_reports_are_due():
    e = locate(*synthetic(ring(8, 20.0), t0=2.0), CFG)
    cells = CellCounts([{"cell_x_km": 101.0, "cell_y_km": 101.0, "phones": 30}])
    # P arrives about 3.7 s; plus 4.5 s latency: not due before about 8.2 s.
    assert silence_check(e, 6.0, cells, [], CFG) == (0, 0, True)


# ---------------------------------------------------------------------------
# Warning times
# ---------------------------------------------------------------------------


def test_predicted_warning_formula():
    e = locate(*synthetic(ring(8, 20.0), source=(100.0, 100.0), t0=0.0), CFG)
    d = 80.0
    expected = math.sqrt(d * d + CFG.depth_km ** 2) / CFG.vs_km_s - 7.5
    assert predicted_warning_s(e, 180.0, 100.0, 7.5, CFG) == pytest.approx(expected, abs=0.02)


def test_warning_is_zero_at_the_predicted_blind_radius():
    e = locate(*synthetic(ring(8, 20.0), source=(100.0, 100.0), t0=0.0), CFG)
    r = predicted_blind_radius_km(e, 7.5, CFG)
    assert predicted_warning_s(e, e.x_km + r, e.y_km, 7.5, CFG) == pytest.approx(0.0, abs=1e-9)
    assert predicted_warning_s(e, e.x_km + r - 1, e.y_km, 7.5, CFG) < 0
    assert predicted_warning_s(e, e.x_km + r + 1, e.y_km, 7.5, CFG) > 0


# ---------------------------------------------------------------------------
# The full server on simulated quakes
# ---------------------------------------------------------------------------


def simulated(seed=5, xy=(100.0, 90.0)):
    world = generate_world(seed, "demo", quake_xy=xy)
    reports, truths = generate_reports(world)
    return world, [r.to_dict() for r in reports], truths, list(active_phone_counts(world))


def test_server_alerts_and_locates_a_simulated_quake():
    world, reports, _, cells = simulated()
    run = run_server(reports, k=10, cell_counts=cells)
    assert run.alert is not None
    e = run.alert.estimate
    assert math.hypot(e.x_km - world.quake.x_km, e.y_km - world.quake.y_km) < 5.0
    assert run.alert.t_issued_s > world.quake.origin_time_s
    assert run.alert.t_delivered_s == pytest.approx(run.alert.t_issued_s + CFG.delivery_s)


def test_alert_never_has_fewer_than_k_trusted_reports():
    _, reports, _, cells = simulated()
    for k in (4, 10, 25, 40):
        run = run_server(reports, k=k, cell_counts=cells)
        assert run.alert is not None and run.alert.estimate.inlier_count >= k


def test_larger_k_never_alerts_earlier():
    _, reports, _, cells = simulated()
    times = [run_server(reports, k=k, cell_counts=cells).alert.t_issued_s for k in (4, 10, 20, 40)]
    assert times == sorted(times)


def test_one_pass_gives_the_same_alert_as_a_run_for_each_k():
    _, reports, _, cells = simulated(seed=11, xy=(30.0, 190.0))
    full = run_server(reports, k=4, cell_counts=cells, stop_after_alert=False)
    for k in (4, 8, 15, 30):
        direct = run_server(reports, k=k, cell_counts=cells).alert
        snapshot = first_alert_snapshot(full.snapshots, k)
        assert snapshot is not None and direct is not None
        assert snapshot.t_s + CFG.processing_s == pytest.approx(direct.t_issued_s)


def test_no_alert_from_noise_only_at_default_k():
    world = generate_world(2, "tuning")
    from outrun.sim.reports import ReportConfig
    reports, _ = generate_reports(world, ReportConfig(duration_s=1800.0), include_quake=False)
    run = run_server([r.to_dict() for r in reports], k=10,
                     cell_counts=list(active_phone_counts(world)))
    assert run.alert is None


def test_server_rerun_from_json_gives_identical_result():
    """Run-time data wall: the server's answer depends ONLY on the plain data it
    receives. Saved to JSON and replayed, it must give exactly the same alert."""
    _, reports, _, cells = simulated(seed=7, xy=(70.0, 120.0))
    first = run_server(reports, k=10, cell_counts=cells)
    replay = json.loads(json.dumps({"reports": reports, "cells": cells}))
    second = run_server(replay["reports"], k=10, cell_counts=replay["cells"])
    assert first.alert == second.alert
    assert first.final_estimate == second.final_estimate


def test_report_order_in_input_does_not_matter():
    _, reports, _, cells = simulated()
    assert run_server(list(reversed(reports)), k=10, cell_counts=cells).alert == \
        run_server(reports, k=10, cell_counts=cells).alert


@pytest.mark.parametrize("k", [3, 41, 10.0, True, "10"])
def test_k_must_be_an_integer_in_range(k):
    with pytest.raises(ValueError):
        run_server([], k=k)


def test_empty_report_stream_gives_no_alert():
    run = run_server([], k=10)
    assert run.alert is None and run.final_estimate is None


@pytest.mark.parametrize("changes", [{"vp_km_s": 3.0}, {"depth_km": -1.0}, {"k_min": 3},
                                     {"coarse_step_km": 0.0}, {"rms_max_s": math.nan}])
def test_server_config_rejects_bad_values(changes):
    with pytest.raises(ValueError):
        ServerConfig(**changes)


def test_report_message_rejects_non_finite_values():
    with pytest.raises(ValueError):
        ReportMessage.from_dict({"report_id": 1, "cell_x_km": math.nan, "cell_y_km": 1.0,
                                 "t_detect_s": 1.0, "t_received_s": 2.0})


def test_estimate_stays_in_region_for_the_real_case_that_diverged():
    """Regression with the exact reports that once produced an estimate at
    (-33290, 25882) km: the first 10 reports of a quake inside Eastport."""
    world = generate_world(3, "demo", quake_xy=(150.0, 105.0))
    reports, _ = generate_reports(world)
    first = reports[:10]
    e = locate(np.array([r.report_id for r in first]), np.array([r.cell_x_km for r in first]),
               np.array([r.cell_y_km for r in first]), np.array([r.t_detect_s for r in first]), CFG)
    m = CFG.search_margin_km
    assert -m <= e.x_km <= CFG.region_width_km + m and -m <= e.y_km <= CFG.region_height_km + m


def test_alert_rule_refuses_an_estimate_whose_nearby_phones_are_silent():
    import dataclasses
    e = dataclasses.replace(locate(*synthetic(ring(30, 20.0)), CFG), nearby_reports=30)
    assert alert_rule(e, 10, CFG)
    assert not alert_rule(dataclasses.replace(e, silence_ok=False), 10, CFG)


def test_alert_rule_needs_reports_from_near_the_estimate():
    """Regression: with no phones near a wrong estimate, the silence check has
    nothing to judge, so the rule also needs positive evidence: reports from
    within silence_radius_km of the estimate."""
    import dataclasses
    e = dataclasses.replace(locate(*synthetic(ring(30, 20.0)), CFG), nearby_required=5)
    assert alert_rule(dataclasses.replace(e, nearby_reports=5), 10, CFG)
    assert not alert_rule(dataclasses.replace(e, nearby_reports=4), 10, CFG)
    # Even where no phones are expected, at least one nearby report is needed.
    empty = dataclasses.replace(e, nearby_required=0, nearby_reports=0)
    assert not alert_rule(empty, 10, CFG)


@pytest.mark.parametrize("active, expected", [(0, 1), (1, 1), (3, 1), (4, 2), (10, 3),
                                              (16, 5), (200, 5)])
def test_nearby_reports_required_scales_with_local_phones(active, expected):
    from outrun.server.silence import nearby_reports_required
    assert nearby_reports_required(active, CFG, have_counts=True) == expected
    assert nearby_reports_required(active, CFG, have_counts=False) == CFG.min_nearby_reports


def test_run_server_counts_nearby_reports():
    _, reports, _, cells = simulated()
    run = run_server(reports, k=10, cell_counts=cells)
    assert run.alert.estimate.nearby_reports >= CFG.min_nearby_reports
