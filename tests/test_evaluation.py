"""Tests for outrun/evaluation/metrics.py."""

import math

import pytest

from outrun.evaluation.metrics import (
    evaluate_quake,
    false_alarm_hours,
    percentile,
    run_hidden_test,
    summarise,
    true_warning_s,
)
from outrun.sim.world import generate_world


def test_percentile_examples():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    assert percentile([5], 0.9) == 5
    assert math.isnan(percentile([], 0.5))


def test_evaluate_quake_compares_with_truth():
    result = evaluate_quake(3, stream="validation", k=10)
    assert result.alerted
    assert result.location_error_km < 10
    assert result.alert_delay_s > 0
    assert len(result.warnings) == 3


def test_true_warning_uses_true_s_arrival():
    world = generate_world(4, "validation")
    q = world.quake
    t_delivered = q.origin_time_s + 10.0
    w = true_warning_s(world, q.x_km, q.y_km, t_delivered)
    assert w == pytest.approx(q.depth_km / world.speeds.s_km_s - 10.0)


def test_summary_of_a_small_hidden_test():
    s = run_hidden_test(6, k=10, stream="tuning", start_seed=0)
    assert s["quakes"] == 6 and len(s["rows"]) == 6
    assert s["alerted"] <= 6
    assert 0 <= s["within_predicted_error_pct"] <= 100


def test_summarise_counts_missed_only_inside_network():
    from outrun.evaluation.metrics import QuakeResult
    nan = math.nan
    results = [
        QuakeResult(1, True, True, 5.0, 1.0, 1.0, 0.1, 3.0, True, (), 0),
        QuakeResult(2, True, False, nan, nan, nan, nan, nan, False, (), 0),
        QuakeResult(3, False, False, nan, nan, nan, nan, nan, False, (), 0),
    ]
    s = summarise(results)
    assert s["missed_inside_network"] == 1 and s["inside_network"] == 2
    assert s["missed_inside_network_pct"] == 50.0


def test_false_alarm_hours_structure():
    fa = false_alarm_hours([4, 10], [0], stream="tuning")
    assert fa["hours"] == 1 and set(fa["hours_with_false_alert"]) == {4, 10}
    assert fa["hours_with_false_alert"][4] >= fa["hours_with_false_alert"][10]
