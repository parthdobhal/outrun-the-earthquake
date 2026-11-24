"""Tests for outrun/sim/world.py: map, towns, phones and the hidden quake."""

import dataclasses
import math
import random
import statistics
import sys
from fractions import Fraction

import pytest

from outrun.sim.model import EarthquakeSource, WaveSpeeds
import outrun.sim.world as world_module
from outrun.sim.world import (
    DEFAULT_TOWNS,
    MAX_SAMPLING_ATTEMPTS,
    Phone,
    Town,
    World,
    WorldConfig,
    _point_in_town,
    generate_phones,
    generate_quake,
    generate_speeds,
    generate_world,
    max_speed_perturbation,
)

CONFIG = WorldConfig()
TOTAL_PHONES = sum(t.phone_count for t in DEFAULT_TOWNS) + CONFIG.rural_phone_count


# ---------------------------------------------------------------------------
# Reproducibility and stream separation
# ---------------------------------------------------------------------------


def test_same_seed_and_stream_give_identical_worlds():
    assert generate_world(11, "demo") == generate_world(11, "demo")


def test_different_seeds_give_different_worlds():
    a, b = generate_world(1, "demo"), generate_world(2, "demo")
    assert a.quake != b.quake
    assert a.phones != b.phones
    assert a.speeds != b.speeds


def test_tuning_and_validation_worlds_differ_for_the_same_seed():
    a, b = generate_world(5, "tuning"), generate_world(5, "validation")
    assert a.quake != b.quake and a.phones != b.phones


def test_phones_do_not_change_when_the_quake_is_placed_by_hand():
    """Clicking a different epicentre must not reshuffle the phones (needed so the
    slider can replay the same quake and phones)."""
    auto = generate_world(3, "demo")
    placed = generate_world(3, "demo", quake_xy=(20.0, 180.0))
    assert placed.phones == auto.phones
    assert placed.speeds == auto.speeds


def test_hand_placed_quake_keeps_seeded_depth_and_origin_time():
    a = generate_world(3, "demo", quake_xy=(20.0, 180.0))
    b = generate_world(3, "demo", quake_xy=(150.0, 30.0))
    assert (a.quake.x_km, a.quake.y_km) == (20.0, 180.0)
    assert (b.quake.x_km, b.quake.y_km) == (150.0, 30.0)
    assert a.quake.depth_km == b.quake.depth_km
    assert a.quake.origin_time_s == b.quake.origin_time_s


@pytest.mark.parametrize("seed", range(5))
def test_hand_placed_quake_has_same_depth_and_time_as_automatic_one(seed):
    """Placing the epicentre by hand must not change the seeded depth or origin
    time compared with letting the seed choose the epicentre."""
    auto = generate_world(seed, "demo").quake
    placed = generate_world(seed, "demo", quake_xy=(10.0, 10.0)).quake
    assert placed.depth_km == auto.depth_km
    assert placed.origin_time_s == auto.origin_time_s


@pytest.mark.parametrize("seed", range(20))
def test_phones_and_quake_use_independent_random_streams(seed):
    """If phones and quake shared one random stream, the first rural phone would
    be drawn with the same numbers as the epicentre and sit exactly on it."""
    config = WorldConfig(towns=(), rural_phone_count=50)
    world = generate_world(seed, "demo", config=config)
    epicentre = (world.quake.x_km, world.quake.y_km)
    assert all((p.x_km, p.y_km) != epicentre for p in world.phones)


def test_generation_does_not_touch_global_random_state():
    random.seed(99)
    before = random.getstate()
    generate_world(4, "validation")
    assert random.getstate() == before


# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------


def test_phone_count_matches_config():
    assert len(generate_world(0).phones) == TOTAL_PHONES == 2700


def test_phone_ids_are_unique_and_sequential():
    phones = generate_world(0).phones
    assert [p.phone_id for p in phones] == list(range(len(phones)))


@pytest.mark.parametrize("seed", range(5))
def test_all_phones_are_inside_the_map(seed):
    for p in generate_world(seed).phones:
        assert 0 <= p.x_km <= CONFIG.map_width_km
        assert 0 <= p.y_km <= CONFIG.map_height_km


def test_town_phones_are_inside_their_town_circle():
    phones = generate_world(0).phones
    start = 0
    for town in DEFAULT_TOWNS:
        for p in phones[start:start + town.phone_count]:
            assert math.hypot(p.x_km - town.x_km, p.y_km - town.y_km) <= town.radius_km + 1e-9
        start += town.phone_count


def test_town_on_map_edge_keeps_its_phones_inside_the_map():
    corner = Town("Corner", 0.0, 0.0, 30.0, 400)
    config = WorldConfig(towns=(corner,), rural_phone_count=0)
    phones = generate_phones(8, "demo", config)
    assert len(phones) == 400
    assert all(0 <= p.x_km <= 200 and 0 <= p.y_km <= 200 for p in phones)


def test_town_phones_are_spread_over_the_area_not_crowded_at_centre():
    """With uniform-by-area sampling, about half the phones lie within
    R / sqrt(2) of the centre (half the area)."""
    town = Town("Test", 100.0, 100.0, 20.0, 4000)
    config = WorldConfig(towns=(town,), rural_phone_count=0)
    phones = generate_phones(1, "demo", config)
    inner = sum(math.hypot(p.x_km - 100, p.y_km - 100) <= 20 / math.sqrt(2) for p in phones)
    assert 0.46 < inner / len(phones) < 0.54


def test_clock_offsets_have_the_configured_spread():
    offsets = [p.clock_offset_s for p in generate_world(0).phones]
    assert abs(statistics.fmean(offsets)) < 0.01
    assert statistics.stdev(offsets) == pytest.approx(CONFIG.clock_offset_sd_s, rel=0.1)


def test_zero_clock_spread_gives_perfect_clocks():
    config = WorldConfig(clock_offset_sd_s=0.0)
    assert all(p.clock_offset_s == 0.0 for p in generate_world(0, config=config).phones)


# ---------------------------------------------------------------------------
# Quake and speeds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_random_quake_respects_config_ranges(seed):
    q = generate_world(seed, "tuning").quake
    assert isinstance(q, EarthquakeSource)
    assert 0 <= q.x_km <= CONFIG.map_width_km and 0 <= q.y_km <= CONFIG.map_height_km
    assert CONFIG.depth_min_km <= q.depth_km <= CONFIG.depth_max_km
    assert CONFIG.origin_time_min_s <= q.origin_time_s <= CONFIG.origin_time_max_s


def test_random_quakes_cover_the_map():
    quakes = [generate_quake(s, "tuning", CONFIG) for s in range(400)]
    xs = [q.x_km for q in quakes]
    ys = [q.y_km for q in quakes]
    assert min(xs) < 20 and max(xs) > 180 and min(ys) < 20 and max(ys) > 180


@pytest.mark.parametrize("seed", range(50))
def test_true_speeds_are_near_nominal_but_not_assumed_exactly(seed):
    s = generate_world(seed).speeds
    assert isinstance(s, WaveSpeeds)
    assert 6.0 * 0.97 <= s.p_km_s <= 6.0 * 1.03
    assert 3.5 * 0.97 <= s.s_km_s <= 3.5 * 1.03
    assert s.p_km_s > s.s_km_s


def test_speed_perturbation_zero_gives_nominal_speeds():
    config = WorldConfig(speed_perturbation=0.0)
    assert generate_speeds(0, "demo", config) == WaveSpeeds(6.0, 3.5)


@pytest.mark.parametrize("xy", [(-1.0, 50.0), (50.0, 200.1), (math.nan, 1.0), (1.0, math.inf)])
def test_quake_outside_map_or_non_finite_is_rejected(xy):
    with pytest.raises(ValueError):
        generate_quake(0, "demo", CONFIG, xy)


def test_quake_on_map_edge_is_allowed():
    q = generate_quake(0, "demo", CONFIG, (0.0, 200.0))
    assert (q.x_km, q.y_km) == (0.0, 200.0)


def test_quake_xy_must_have_two_values():
    with pytest.raises(ValueError):
        generate_quake(0, "demo", CONFIG, (1.0, 2.0, 3.0))


# ---------------------------------------------------------------------------
# Immutability and types
# ---------------------------------------------------------------------------


def test_world_and_its_parts_are_immutable():
    world = generate_world(0)
    assert isinstance(world, World) and isinstance(world.phones, tuple)
    assert isinstance(world.phones[0], Phone)
    with pytest.raises(dataclasses.FrozenInstanceError):
        world.quake = None
    with pytest.raises(dataclasses.FrozenInstanceError):
        world.phones[0].x_km = 0.0


def test_world_records_its_seed_and_stream():
    world = generate_world(21, "validation")
    assert (world.seed, world.stream) == (21, "validation")


def test_generate_world_rejects_unknown_stream_and_bad_seed():
    with pytest.raises(ValueError):
        generate_world(0, "production")
    with pytest.raises(ValueError):
        generate_world(-5)
    with pytest.raises(TypeError):
        generate_world(1.5)


def test_generate_world_rejects_non_config():
    with pytest.raises(TypeError):
        generate_world(0, config={"map_width_km": 100})


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"map_width_km": 0.0},
        {"map_height_km": -10.0},
        {"map_width_km": math.inf},
        {"rural_phone_count": -1},
        {"clock_offset_sd_s": -0.1},
        {"clock_offset_sd_s": math.nan},
        {"depth_min_km": -1.0},
        {"depth_min_km": 30.0, "depth_max_km": 10.0},
        {"origin_time_min_s": 10.0, "origin_time_max_s": 1.0},
        {"speed_perturbation": -0.01},
        {"speed_perturbation": 0.5},
        {"towns": (Town("Outside", 250.0, 50.0, 5.0, 10),)},
        {"towns": (Town("NoRadius", 50.0, 50.0, 0.0, 10),)},
        {"towns": (Town("Negative", 50.0, 50.0, 5.0, -3),)},
        {"towns": (), "rural_phone_count": 0},
    ],
)
def test_config_rejects_invalid_values(changes):
    with pytest.raises(ValueError):
        WorldConfig(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"rural_phone_count": 10.5},
        {"rural_phone_count": True},
        {"towns": [DEFAULT_TOWNS[0]]},
        {"towns": ("not a town",)},
        {"towns": (Town("Float", 50.0, 50.0, 5.0, 2.5),)},
        {"nominal_speeds": (6.0, 3.5)},
    ],
)
def test_config_rejects_wrong_types(changes):
    with pytest.raises(TypeError):
        WorldConfig(**changes)


def test_custom_small_world():
    config = WorldConfig(map_width_km=50.0, map_height_km=40.0,
                         towns=(Town("Tiny", 25.0, 20.0, 5.0, 30),), rural_phone_count=20)
    world = generate_world(2, config=config)
    assert len(world.phones) == 50
    assert all(0 <= p.x_km <= 50 and 0 <= p.y_km <= 40 for p in world.phones)


# ---------------------------------------------------------------------------
# Regression: phone placement must stay fast and uniform (revision of 2B)
# ---------------------------------------------------------------------------


class CountingRandom(random.Random):
    """A random generator that counts how many uniform() draws are made."""

    def __init__(self, seed):
        super().__init__(seed)
        self.uniform_calls = 0

    def uniform(self, a, b):
        self.uniform_calls += 1
        return super().uniform(a, b)


def test_huge_town_on_tiny_map_is_placed_quickly():
    """Old method: about 1.3 in a million tries succeeded here (16.6 million
    draws for ONE phone). New method: a couple of draws per phone."""
    town = Town("Huge", 0.0, 0.0, 1000.0, 1)
    config = WorldConfig(map_width_km=1.0, map_height_km=1.0, towns=(town,), rural_phone_count=0)
    rng = CountingRandom(1)
    points = [_point_in_town(rng, town, config) for _ in range(1000)]
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in points)
    assert rng.uniform_calls <= 2 * 1000 * 2  # at most 2 tries per phone on average


@pytest.mark.parametrize(
    "town, width, height",
    [
        (Town("Centre", 100.0, 100.0, 10.0, 1), 200.0, 200.0),   # fully on the map
        (Town("Corner", 0.0, 0.0, 30.0, 1), 200.0, 200.0),       # quarter on the map
        (Town("Edge", 100.0, 0.0, 30.0, 1), 200.0, 200.0),       # half on the map
        (Town("Narrow", 5.0, 50.0, 500.0, 1), 10.0, 100.0),      # map is a thin strip
        (Town("Far", 200.0, 200.0, 5000.0, 1), 200.0, 200.0),    # radius >> map
    ],
)
def test_average_tries_per_phone_stay_below_four_thirds_over_pi(town, width, height):
    """At least pi/4 of the sampling box is inside the circle, so the average
    number of tries is at most 4/pi = 1.27 (allow a little random variation)."""
    config = WorldConfig(map_width_km=width, map_height_km=height, towns=(town,),
                         rural_phone_count=0)
    rng = CountingRandom(7)
    n = 4000
    for _ in range(n):
        x, y = _point_in_town(rng, town, config)
        assert 0 <= x <= width and 0 <= y <= height
        assert math.hypot(x - town.x_km, y - town.y_km) <= town.radius_km + 1e-9
    average_tries = rng.uniform_calls / 2 / n
    assert average_tries < 4 / math.pi + 0.05


def test_corner_town_is_uniform_over_its_quarter_circle():
    """A quarter circle of radius 20: half its area lies within 20/sqrt(2) of
    the centre, and half of it lies below the 45-degree line."""
    town = Town("Corner", 0.0, 0.0, 20.0, 20000)
    config = WorldConfig(towns=(town,), rural_phone_count=0)
    phones = generate_phones(3, "demo", config)
    inner = sum(math.hypot(p.x_km, p.y_km) <= 20 / math.sqrt(2) for p in phones) / len(phones)
    below_diagonal = sum(p.y_km < p.x_km for p in phones) / len(phones)
    assert inner == pytest.approx(0.5, abs=0.015)
    assert below_diagonal == pytest.approx(0.5, abs=0.015)


def test_edge_town_is_uniform_over_its_half_circle():
    """Half circle of radius 20 above the map edge y = 0. The share of its area
    with y <= 10 is 2*(5*sqrt(300) + 200*pi/6) / (200*pi) = 0.6090."""
    town = Town("Edge", 100.0, 0.0, 20.0, 20000)
    config = WorldConfig(towns=(town,), rural_phone_count=0)
    phones = generate_phones(4, "demo", config)
    expected = 2 * (5 * math.sqrt(300) + 200 * math.pi / 6) / (200 * math.pi)
    share = sum(p.y_km <= 10 for p in phones) / len(phones)
    assert expected == pytest.approx(0.6090, abs=1e-4)
    assert share == pytest.approx(expected, abs=0.015)


def test_sampling_stops_with_an_error_instead_of_looping_forever():
    """A broken generator that always picks the box corner (outside the circle)
    must hit the safety limit and raise, not hang."""

    class AlwaysCorner:
        calls = 0

        def uniform(self, a, b):
            AlwaysCorner.calls += 1
            return b

    town = Town("Centre", 100.0, 100.0, 10.0, 1)
    with pytest.raises(RuntimeError):
        _point_in_town(AlwaysCorner(), town, CONFIG)
    assert AlwaysCorner.calls == 2 * MAX_SAMPLING_ATTEMPTS


# ---------------------------------------------------------------------------
# Regression: the P-wave must always be faster than the S-wave (revision of 2B)
# ---------------------------------------------------------------------------


def test_max_speed_perturbation_formula():
    assert max_speed_perturbation(WaveSpeeds(6.0, 3.5)) == pytest.approx(2.5 / 9.5)
    assert max_speed_perturbation(WaveSpeeds(4.0, 3.5)) == pytest.approx(0.5 / 7.5)


def test_perturbation_that_could_make_s_faster_than_p_is_rejected():
    """Before the fix this was accepted, and 109 of 2000 worlds had S >= P."""
    with pytest.raises(ValueError):
        WorldConfig(nominal_speeds=WaveSpeeds(4.0, 3.5), speed_perturbation=0.1)


@pytest.mark.parametrize("nominal", [WaveSpeeds(3.5, 3.5), WaveSpeeds(3.0, 3.5)])
def test_nominal_s_not_slower_than_p_is_rejected(nominal):
    with pytest.raises(ValueError):
        WorldConfig(nominal_speeds=nominal)


def test_perturbation_just_above_the_limit_is_rejected():
    # (The limit itself is rounded when stored as a float, so whether that exact
    # float is accepted depends on rounding; the worst-case test below proves the
    # largest ACCEPTED value is still safe.)
    nominal = WaveSpeeds(6.0, 3.5)
    with pytest.raises(ValueError):
        WorldConfig(speed_perturbation=max_speed_perturbation(nominal) * (1 + 1e-9))


def largest_accepted_perturbation(nominal):
    """The largest float e that WorldConfig accepts for these nominal speeds,
    found by binary search between 0 (accepted) and just above the limit
    (rejected), down to neighbouring floats."""

    def accepted(e):
        try:
            WorldConfig(nominal_speeds=nominal, speed_perturbation=e)
            return True
        except ValueError:
            return False

    lo, hi = 0.0, max_speed_perturbation(nominal) * (1 + 1e-6)
    assert accepted(lo) and not accepted(hi)
    while math.nextafter(lo, hi) < hi:
        mid = lo + (hi - lo) / 2
        if mid <= lo or mid >= hi:
            mid = math.nextafter(lo, hi)
        if accepted(mid):
            lo = mid
        else:
            hi = mid
    assert accepted(lo) and not accepted(math.nextafter(lo, 1.0))
    return lo


@pytest.mark.parametrize("nominal", [WaveSpeeds(6.0, 3.5), WaveSpeeds(4.0, 3.5),
                                     WaveSpeeds(3.5000001, 3.5)])
def test_worst_case_draws_at_the_largest_accepted_perturbation_keep_p_faster(nominal, monkeypatch):
    """Force the worst possible draws (slowest P, fastest S), even draws that
    overshoot the range slightly, at the largest perturbation that is accepted."""
    e = largest_accepted_perturbation(nominal)
    config = WorldConfig(nominal_speeds=nominal, speed_perturbation=e)

    class WorstCase:
        def __init__(self):
            self.n = 0

        def uniform(self, a, b):
            self.n += 1
            # first draw (P): overshoot below -e; second draw (S): overshoot above +e
            return a - 1e-3 if self.n == 1 else b + 1e-3

    monkeypatch.setattr(world_module, "make_rng", lambda *args: WorstCase())
    speeds = generate_speeds(0, "demo", config)
    assert speeds.p_km_s > speeds.s_km_s


def test_many_worlds_near_the_limit_keep_p_faster():
    nominal = WaveSpeeds(4.0, 3.5)
    config = WorldConfig(nominal_speeds=nominal,
                         speed_perturbation=largest_accepted_perturbation(nominal))
    for seed in range(3000):
        s = generate_speeds(seed, "tuning", config)
        assert s.p_km_s > s.s_km_s


# ---------------------------------------------------------------------------
# Regression: very large but finite values must not overflow (revision of 2B)
# ---------------------------------------------------------------------------

FLOAT_MAX = sys.float_info.max  # about 1.8e308, the largest finite float


@pytest.mark.parametrize("radius", [1e200, 1e300, FLOAT_MAX])
def test_very_large_finite_town_radius_does_not_overflow(radius):
    """The old check squared the radius: 1e200 ** 2 raises OverflowError.
    With math.hypot no large number is squared, so phones are placed normally."""
    with pytest.raises(OverflowError):
        radius ** 2  # what the old code did
    town = Town("Giant", 100.0, 100.0, radius, 300)
    config = WorldConfig(towns=(town,), rural_phone_count=0)
    world = generate_world(5, "demo", config)
    assert len(world.phones) == 300
    for phone in world.phones:
        assert 0 <= phone.x_km <= config.map_width_km
        assert 0 <= phone.y_km <= config.map_height_km


def test_very_large_finite_map_and_town_do_not_overflow():
    """Map, town position and radius all near the largest float: the box edges
    town.x_km + radius may round to infinity, but they are clipped to the map,
    and the distance check stays finite."""
    town = Town("Giant", FLOAT_MAX / 2, FLOAT_MAX, FLOAT_MAX, 200)
    config = WorldConfig(map_width_km=FLOAT_MAX, map_height_km=FLOAT_MAX,
                         towns=(town,), rural_phone_count=0)
    phones = generate_phones(9, "demo", config)
    assert len(phones) == 200
    for p in phones:
        assert math.isfinite(p.x_km) and math.isfinite(p.y_km)
        assert 0 <= p.x_km <= FLOAT_MAX and 0 <= p.y_km <= FLOAT_MAX
        assert math.hypot(p.x_km - town.x_km, p.y_km - town.y_km) <= town.radius_km


# Nominal speeds whose plain sum p + s is larger than the largest float, but
# for which P raised by the full perturbation limit, p(1 + limit), stays finite.
LARGE_SPEEDS = [
    WaveSpeeds(1.0e308, 9.0e307),
    WaveSpeeds(1.2e308, 1.0e308),
    WaveSpeeds(1.6e308, 1.5e308),
]

# Nominal speeds so close to the largest float that even a modest perturbation
# would push the fastest possible P speed past it.
NEAR_MAX_SPEEDS = [
    WaveSpeeds(1.55e308, 1.0e308),
    WaveSpeeds(1.7e308, 1.0e308),
    WaveSpeeds(FLOAT_MAX, FLOAT_MAX / 2),
]


@pytest.mark.parametrize("nominal", LARGE_SPEEDS + NEAR_MAX_SPEEDS)
def test_max_speed_perturbation_is_correct_for_very_large_speeds(nominal):
    p, s = nominal.p_km_s, nominal.s_km_s
    assert math.isinf(p + s)  # the plain formula would divide by infinity and give 0
    exact = (Fraction(p) - Fraction(s)) / (Fraction(p) + Fraction(s))
    result = max_speed_perturbation(nominal)
    assert math.isfinite(result) and result > 0
    assert result == pytest.approx(float(exact), rel=1e-15)


@pytest.mark.parametrize("nominal", [WaveSpeeds(6.0, 3.5), WaveSpeeds(4.0, 3.5),
                                     WaveSpeeds(3.5000001, 3.5), WaveSpeeds(1e-300, 5e-301)])
def test_scaled_formula_matches_plain_formula_for_ordinary_speeds(nominal):
    """Scaling by a power of two is exact, so ordinary speeds give exactly the
    same float as before the fix."""
    p, s = nominal.p_km_s, nominal.s_km_s
    assert max_speed_perturbation(nominal) == (p - s) / (p + s)


@pytest.mark.parametrize("nominal", LARGE_SPEEDS)
def test_very_large_speeds_limit_is_enforced(nominal):
    limit = max_speed_perturbation(nominal)
    WorldConfig(nominal_speeds=nominal, speed_perturbation=limit * (1 - 1e-9))
    with pytest.raises(ValueError):
        WorldConfig(nominal_speeds=nominal, speed_perturbation=limit * (1 + 1e-9))


@pytest.mark.parametrize("nominal", LARGE_SPEEDS)
def test_worst_case_draws_keep_p_faster_for_very_large_speeds(nominal, monkeypatch):
    """At the largest accepted perturbation, force the slowest P and the fastest
    S (even draws that overshoot the range): P must still be faster, and both
    speeds must stay finite."""
    e = largest_accepted_perturbation(nominal)
    assert e == pytest.approx(max_speed_perturbation(nominal), rel=1e-12)
    config = WorldConfig(nominal_speeds=nominal, speed_perturbation=e)

    class WorstCase:
        def __init__(self):
            self.n = 0

        def uniform(self, a, b):
            self.n += 1
            return a - 1e-3 if self.n == 1 else b + 1e-3

    monkeypatch.setattr(world_module, "make_rng", lambda *args: WorstCase())
    speeds = generate_speeds(0, "demo", config)
    assert math.isfinite(speeds.p_km_s) and math.isfinite(speeds.s_km_s)
    assert speeds.p_km_s > speeds.s_km_s


@pytest.mark.parametrize("nominal", LARGE_SPEEDS)
def test_random_worlds_with_very_large_speeds_keep_p_faster(nominal):
    config = WorldConfig(nominal_speeds=nominal,
                         speed_perturbation=largest_accepted_perturbation(nominal))
    for seed in range(500):
        s = generate_speeds(seed, "tuning", config)
        assert math.isfinite(s.p_km_s) and math.isfinite(s.s_km_s)
        assert s.p_km_s > s.s_km_s


@pytest.mark.parametrize("nominal", NEAR_MAX_SPEEDS)
def test_perturbation_that_would_overflow_p_is_rejected(nominal):
    """Found while adding the large-speed tests: these configs were accepted,
    then generate_speeds crashed when a draw pushed P past the largest float.
    Now WorldConfig rejects them, so an accepted config always generates."""
    e = 0.9 * max_speed_perturbation(nominal)  # safe for P > S ...
    assert math.isinf(nominal.p_km_s * (1.0 + e))  # ... but P could overflow
    with pytest.raises(ValueError, match="overflow"):
        WorldConfig(nominal_speeds=nominal, speed_perturbation=e)


@pytest.mark.parametrize("nominal", NEAR_MAX_SPEEDS)
def test_near_max_speeds_generate_at_largest_accepted_perturbation(nominal, monkeypatch):
    """For near-maximum speeds the largest accepted perturbation is limited by
    overflow, not by P > S. At that value the worst draws (fastest P, then
    slowest P with fastest S) must give finite speeds with P faster."""
    e = largest_accepted_perturbation(nominal)
    assert 0 < e < max_speed_perturbation(nominal)
    config = WorldConfig(nominal_speeds=nominal, speed_perturbation=e)

    for first, second in (("high", "high"), ("low", "high")):
        class Forced:
            def __init__(self):
                self.n = 0

            def uniform(self, a, b):
                self.n += 1
                side = first if self.n == 1 else second
                return b + 1e-3 if side == "high" else a - 1e-3

        monkeypatch.setattr(world_module, "make_rng", lambda *args: Forced())
        speeds = generate_speeds(0, "demo", config)
        assert math.isfinite(speeds.p_km_s) and math.isfinite(speeds.s_km_s)
        assert speeds.p_km_s > speeds.s_km_s
    monkeypatch.undo()

    for seed in range(500):
        s = generate_speeds(seed, "tuning", config)
        assert math.isfinite(s.p_km_s) and s.p_km_s > s.s_km_s
