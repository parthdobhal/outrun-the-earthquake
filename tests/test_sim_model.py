
"""Tests for the scientific earthquake simulation model."""

import dataclasses
import math

import pytest

from outrun.sim.model import (
    EarthquakeSource,
    WaveSpeeds,
    distance_3d,
    p_wave_arrival_time,
    s_wave_arrival_time,
)


def test_default_wave_speeds():
    speeds = WaveSpeeds()

    assert speeds.p_km_s == 6.0
    assert speeds.s_km_s == 3.5


def test_custom_wave_speeds():
    speeds = WaveSpeeds(p_km_s=8.0, s_km_s=4.0)

    assert speeds.p_km_s == 8.0
    assert speeds.s_km_s == 4.0


def test_source_creation():
    source = EarthquakeSource(
        x_km=10.0,
        y_km=20.0,
        depth_km=5.0,
        origin_time_s=100.0,
    )

    assert source.x_km == 10.0
    assert source.y_km == 20.0
    assert source.depth_km == 5.0
    assert source.origin_time_s == 100.0


def test_zero_depth_is_valid():
    source = EarthquakeSource(0.0, 0.0, 0.0, 0.0)

    assert source.depth_km == 0.0


def test_distance_with_depth_only():
    source = EarthquakeSource(0.0, 0.0, 5.0, 0.0)

    assert distance_3d(source, 0.0, 0.0) == 5.0


def test_distance_with_horizontal_and_vertical_difference():
    source = EarthquakeSource(0.0, 0.0, 4.0, 0.0)

    # sqrt(3² + 4² + 4²) = sqrt(41)
    assert distance_3d(source, 3.0, 4.0) == pytest.approx(math.sqrt(41))


def test_distance_is_symmetric_in_horizontal_coordinates():
    source = EarthquakeSource(2.0, 3.0, 4.0, 0.0)

    first = distance_3d(source, 5.0, 7.0)
    second = distance_3d(source, -1.0, -1.0)

    assert first == pytest.approx(second)


def test_distance_zero_at_surface_source():
    source = EarthquakeSource(2.0, 3.0, 0.0, 0.0)

    assert distance_3d(source, 2.0, 3.0) == 0.0


def test_p_wave_arrival_includes_origin_time():
    source = EarthquakeSource(0.0, 0.0, 12.0, 100.0)

    # Distance = 12 km, speed = 6 km/s, travel time = 2 s.
    assert p_wave_arrival_time(source, 0.0, 0.0) == pytest.approx(102.0)


def test_s_wave_arrival_includes_origin_time():
    source = EarthquakeSource(0.0, 0.0, 7.0, 100.0)

    # Distance = 7 km, speed = 3.5 km/s, travel time = 2 s.
    assert s_wave_arrival_time(source, 0.0, 0.0) == pytest.approx(102.0)


def test_s_wave_arrives_after_p_wave():
    source = EarthquakeSource(0.0, 0.0, 10.0, 50.0)

    p_time = p_wave_arrival_time(source, 0.0, 0.0)
    s_time = s_wave_arrival_time(source, 0.0, 0.0)

    assert p_time < s_time


def test_custom_speeds_affect_arrival_times():
    source = EarthquakeSource(0.0, 0.0, 20.0, 10.0)
    speeds = WaveSpeeds(p_km_s=10.0, s_km_s=5.0)

    assert p_wave_arrival_time(source, 0.0, 0.0, speeds) == pytest.approx(12.0)
    assert s_wave_arrival_time(source, 0.0, 0.0, speeds) == pytest.approx(14.0)


def test_negative_coordinates_are_valid():
    source = EarthquakeSource(-10.0, -20.0, 5.0, 0.0)

    assert distance_3d(source, -10.0, -20.0) == 5.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("x_km", math.nan),
        ("x_km", math.inf),
        ("y_km", -math.inf),
        ("depth_km", math.nan),
        ("origin_time_s", math.inf),
    ],
)
def test_source_rejects_non_finite_values(field, value):
    values = {
        "x_km": 0.0,
        "y_km": 0.0,
        "depth_km": 5.0,
        "origin_time_s": 0.0,
    }
    values[field] = value

    with pytest.raises(ValueError):
        EarthquakeSource(**values)


def test_source_rejects_negative_depth():
    with pytest.raises(ValueError):
        EarthquakeSource(0.0, 0.0, -1.0, 0.0)


@pytest.mark.parametrize(
    "p_speed,s_speed",
    [
        (0.0, 3.5),
        (-1.0, 3.5),
        (6.0, 0.0),
        (6.0, -1.0),
        (math.nan, 3.5),
        (6.0, math.inf),
    ],
)
def test_wave_speeds_reject_invalid_values(p_speed, s_speed):
    with pytest.raises(ValueError):
        WaveSpeeds(p_km_s=p_speed, s_km_s=s_speed)


@pytest.mark.parametrize(
    "x_km,y_km",
    [
        (math.nan, 0.0),
        (0.0, math.inf),
        (-math.inf, 0.0),
    ],
)
def test_distance_rejects_non_finite_observation_coordinates(x_km, y_km):
    source = EarthquakeSource(0.0, 0.0, 5.0, 0.0)

    with pytest.raises(ValueError):
        distance_3d(source, x_km, y_km)


def test_dataclasses_are_immutable():
    source = EarthquakeSource(0.0, 0.0, 5.0, 0.0)
    speeds = WaveSpeeds()

    with pytest.raises(AttributeError):
        source.depth_km = 10.0

    with pytest.raises(AttributeError):
        speeds.p_km_s = 10.0


# ---------------------------------------------------------------------------
# Numerical robustness (Milestone 2A revision)
# ---------------------------------------------------------------------------


def test_distance_with_extremely_large_finite_coordinates():
    # Squaring 1e200 would overflow; hypot must still give the right answer.
    source = EarthquakeSource(1e200, 0.0, 0.0, 0.0)

    assert distance_3d(source, 0.0, 0.0) == pytest.approx(1e200)


def test_distance_rejects_result_too_large_to_represent():
    # Each coordinate is finite, but their difference overflows to infinity.
    source = EarthquakeSource(1.7e308, 0.0, 0.0, 0.0)

    with pytest.raises(ValueError):
        distance_3d(source, -1.7e308, 0.0)


def test_arrival_rejects_result_too_large_to_represent():
    # Origin time 1.7e308 s and travel time 1e308 s are each finite,
    # but their sum overflows to infinity.
    source = EarthquakeSource(0.0, 0.0, 1e308, 1.7e308)

    with pytest.raises(ValueError):
        p_wave_arrival_time(source, 0.0, 0.0, WaveSpeeds(p_km_s=1.0, s_km_s=0.5))


def test_tiny_positive_wave_speeds_are_accepted():
    speeds = WaveSpeeds(p_km_s=5e-324, s_km_s=5e-324)

    assert speeds.p_km_s > 0 and speeds.s_km_s > 0


@pytest.mark.parametrize("arrival", [p_wave_arrival_time, s_wave_arrival_time])
def test_tiny_wave_speeds_giving_infinite_travel_time_are_rejected(arrival):
    # 10 km / 5e-324 km/s overflows to an infinite travel time.
    source = EarthquakeSource(0.0, 0.0, 10.0, 0.0)
    speeds = WaveSpeeds(p_km_s=5e-324, s_km_s=5e-324)

    with pytest.raises(ValueError):
        arrival(source, 0.0, 0.0, speeds)


@pytest.mark.parametrize("field", ["x_km", "y_km", "depth_km", "origin_time_s"])
def test_source_rejects_extremely_large_integers(field):
    values = {
        "x_km": 0.0,
        "y_km": 0.0,
        "depth_km": 5.0,
        "origin_time_s": 0.0,
    }
    values[field] = 10**400

    with pytest.raises(ValueError):
        EarthquakeSource(**values)


@pytest.mark.parametrize("field", ["p_km_s", "s_km_s"])
def test_wave_speeds_reject_extremely_large_integers(field):
    with pytest.raises(ValueError):
        WaveSpeeds(**{field: 10**400})


@pytest.mark.parametrize(
    "x_km,y_km",
    [(10**400, 0.0), (0.0, -(10**400))],
    ids=["huge_x", "huge_negative_y"],
)
def test_distance_rejects_extremely_large_integer_coordinates(x_km, y_km):
    source = EarthquakeSource(0.0, 0.0, 5.0, 0.0)

    with pytest.raises(ValueError):
        distance_3d(source, x_km, y_km)


@pytest.mark.parametrize(
    "changes",
    [
        {"depth_km": -1.0},
        {"x_km": math.nan},
        {"origin_time_s": math.inf},
        {"y_km": 10**400},
    ],
)
def test_replace_reruns_source_validation(changes):
    source = EarthquakeSource(0.0, 0.0, 5.0, 0.0)

    with pytest.raises(ValueError):
        dataclasses.replace(source, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"p_km_s": 0.0},
        {"s_km_s": -1.0},
        {"p_km_s": math.nan},
    ],
)
def test_replace_reruns_wave_speed_validation(changes):
    with pytest.raises(ValueError):
        dataclasses.replace(WaveSpeeds(), **changes)


def test_replace_with_valid_values_works():
    source = dataclasses.replace(EarthquakeSource(0.0, 0.0, 5.0, 0.0), depth_km=8.0)

    assert source.depth_km == 8.0
