"""Tests for outrun/sim/reports.py: simulated phone reports."""

import dataclasses
import math

import pytest

from outrun.sim.model import p_wave_arrival_time, s_wave_arrival_time
from outrun.sim.reports import (
    KIND_FALSE,
    KIND_LATE_S,
    KIND_P,
    PhoneReport,
    ReportConfig,
    cell_centre,
    detection_probability,
    generate_reports,
)
from outrun.sim.world import generate_world


def world(seed=7, xy=(70.0, 120.0)):
    return generate_world(seed, "demo", quake_xy=xy)


def test_reports_contain_no_ground_truth_fields():
    fields = {f.name for f in dataclasses.fields(PhoneReport)}
    assert fields == {"report_id", "cell_x_km", "cell_y_km", "t_detect_s", "t_received_s"}


def test_same_world_gives_identical_reports():
    assert generate_reports(world()) == generate_reports(world())


def test_different_seeds_give_different_reports():
    assert generate_reports(world(1))[0] != generate_reports(world(2))[0]


def test_reports_sorted_by_arrival_with_sequential_ids():
    reports, truths = generate_reports(world())
    assert [r.report_id for r in reports] == list(range(len(reports)))
    assert all(a.t_received_s <= b.t_received_s for a, b in zip(reports, reports[1:]))
    assert set(truths) == {r.report_id for r in reports}


def test_positions_are_cell_centres_not_true_positions():
    w = world()
    reports, truths = generate_reports(w)
    phones = {p.phone_id: p for p in w.phones}
    for r in reports[:300]:
        phone = phones[truths[r.report_id].phone_id]
        assert r.cell_x_km == cell_centre(phone.x_km, 2.0)
        assert r.cell_y_km == cell_centre(phone.y_km, 2.0)
        assert abs(r.cell_x_km - phone.x_km) <= 1.0 and abs(r.cell_y_km - phone.y_km) <= 1.0
        assert (r.cell_x_km, r.cell_y_km) != (phone.x_km, phone.y_km)


def test_cell_centre_examples():
    assert cell_centre(0.0, 2.0) == 1.0
    assert cell_centre(3.9, 2.0) == 3.0
    assert cell_centre(4.0, 2.0) == 5.0


def test_genuine_reports_never_before_their_wave_arrives():
    w = world()
    reports, truths = generate_reports(w)
    phones = {p.phone_id: p for p in w.phones}
    for r in reports:
        truth = truths[r.report_id]
        if truth.kind == KIND_FALSE:
            continue
        phone = phones[truth.phone_id]
        arrival = (p_wave_arrival_time if truth.kind == KIND_P else s_wave_arrival_time)(
            w.quake, phone.x_km, phone.y_km, w.speeds)
        delay = truth.true_detect_s - arrival
        assert 0.2 - 1e-9 <= delay <= 1.0 + 1e-9
        assert r.t_detect_s == pytest.approx(truth.true_detect_s + phone.clock_offset_s)
        assert 0.5 - 1e-9 <= r.t_received_s - truth.true_detect_s <= 3.0 + 1e-9


def test_report_mix_is_mostly_genuine_p():
    _, truths = generate_reports(world())
    kinds = [t.kind for t in truths.values()]
    assert kinds.count(KIND_P) > 0.85 * len(kinds)
    assert kinds.count(KIND_LATE_S) > 0 and kinds.count(KIND_FALSE) > 0


def test_detection_probability_shape():
    c = ReportConfig()
    assert detection_probability(0.0, c) == 1.0
    assert detection_probability(30.0, c) == 1.0
    assert detection_probability(65.0, c) == pytest.approx(0.5)
    assert detection_probability(100.0, c) == 0.0
    assert detection_probability(150.0, c) == 0.0


def test_no_detections_beyond_detect_zero_km():
    w = world()
    reports, truths = generate_reports(w)
    phones = {p.phone_id: p for p in w.phones}
    q = w.quake
    for truth in truths.values():
        if truth.kind != KIND_FALSE:
            p = phones[truth.phone_id]
            assert math.hypot(p.x_km - q.x_km, p.y_km - q.y_km, q.depth_km) < 100.0


def test_no_quake_mode_gives_only_false_reports():
    _, truths = generate_reports(world(), include_quake=False)
    assert truths and all(t.kind == KIND_FALSE for t in truths.values())


def test_false_report_rate_matches_config():
    config = ReportConfig(false_rate_per_hour=2.0, duration_s=3600.0)
    _, truths = generate_reports(world(), config, include_quake=False)
    expected = 2700 * 2.0  # phones x rate x 1 hour
    assert len(truths) == pytest.approx(expected, rel=0.05)


def test_zero_false_rate_gives_no_false_reports():
    _, truths = generate_reports(world(), ReportConfig(false_rate_per_hour=0.0))
    assert all(t.kind != KIND_FALSE for t in truths.values())


def test_fewer_online_phones_give_fewer_reports():
    full = len(generate_reports(world())[0])
    quarter = len(generate_reports(world(), ReportConfig(online_fraction=0.25))[0])
    assert 0.18 * full < quarter < 0.32 * full


def test_upload_delay_scale_delays_arrival_but_not_detection():
    base, _ = generate_reports(world(), ReportConfig(false_rate_per_hour=0.0))
    slow, _ = generate_reports(world(), ReportConfig(false_rate_per_hour=0.0, upload_delay_scale=3.0))
    base_detect = sorted(r.t_detect_s for r in base)
    slow_detect = sorted(r.t_detect_s for r in slow)
    assert base_detect == pytest.approx(slow_detect)
    assert max(r.t_received_s for r in slow) > max(r.t_received_s for r in base)


def test_report_round_trips_through_dict():
    r = generate_reports(world())[0][0]
    assert PhoneReport.from_dict(r.to_dict()) == r


@pytest.mark.parametrize(
    "changes",
    [{"cell_size_km": 0.0}, {"online_fraction": 0.0}, {"online_fraction": 1.5},
     {"detect_full_km": 50.0, "detect_zero_km": 40.0}, {"late_s_fraction": 1.2},
     {"upload_delay_min_s": 2.0, "upload_delay_max_s": 1.0}, {"upload_delay_scale": -1.0},
     {"false_rate_per_hour": -0.1}, {"duration_s": 0.0}, {"detect_delay_min_s": math.nan}],
)
def test_report_config_rejects_invalid_values(changes):
    with pytest.raises(ValueError):
        ReportConfig(**changes)
