"""The simulated world: a map, towns, phones and one hidden earthquake.

EVERYTHING HERE IS SIMULATED AND IS GROUND TRUTH. The towns are invented,
phone positions are random, and the earthquake is hidden from the server.
The server will never receive a World, a Phone or an EarthquakeSource; in the
next milestone, outrun/sim/reports.py turns a World into phone reports, and
only those reports cross to the server.

Map: x runs from 0 to map_width_km (west to east), y from 0 to map_height_km
(south to north). All distances in km, all times in seconds from the start of
the simulation.

Random parts (each from its own sub-stream, see rng.py):
- "phones": where each phone is, and its clock error
- "quake":  the earthquake's position (unless given), depth and origin time
- "speeds": the true wave speeds, nudged a few per cent away from the nominal
            6.0 / 3.5 km/s, so the server's assumed speeds are never exactly
            right (avoids the "inverse crime" of solving with the same model
            that generated the data)
"""

import math
from dataclasses import dataclass, field

from outrun.sim.model import EarthquakeSource, WaveSpeeds, _require_finite
from outrun.sim.rng import make_rng


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Town:
    """An invented town: phones are scattered uniformly within its radius."""

    name: str
    x_km: float
    y_km: float
    radius_km: float
    phone_count: int


@dataclass(frozen=True)
class Phone:
    """One simulated phone (ground truth: the server never sees this object).

    clock_offset_s: how wrong this phone's clock is. A phone that detects
    shaking at true time t will report t + clock_offset_s.
    """

    phone_id: int
    x_km: float
    y_km: float
    clock_offset_s: float


DEFAULT_TOWNS = (
    Town("Northville", 60.0, 140.0, 12.0, 900),
    Town("Eastport", 150.0, 110.0, 10.0, 700),
    Town("Southbridge", 80.0, 50.0, 8.0, 500),
)


@dataclass(frozen=True)
class WorldConfig:
    """Settings for building a world. Every number here is an assumption of the
    simulation, not a measurement, and is listed in the project's assumptions."""

    map_width_km: float = 200.0
    map_height_km: float = 200.0
    towns: tuple = DEFAULT_TOWNS
    rural_phone_count: int = 600
    clock_offset_sd_s: float = 0.1
    depth_min_km: float = 5.0
    depth_max_km: float = 20.0
    origin_time_min_s: float = 0.0
    origin_time_max_s: float = 5.0
    nominal_speeds: WaveSpeeds = field(default_factory=WaveSpeeds)
    speed_perturbation: float = 0.03  # true speeds within +/- 3 % of nominal

    def __post_init__(self) -> None:
        for name in ("map_width_km", "map_height_km"):
            value = getattr(self, name)
            _require_finite(value, f"{name} must be finite")
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if not isinstance(self.towns, tuple):
            raise TypeError("towns must be a tuple of Town objects")
        for town in self.towns:
            if not isinstance(town, Town):
                raise TypeError("towns must contain only Town objects")
            _require_finite(town.x_km, f"town {town.name} x_km must be finite")
            _require_finite(town.y_km, f"town {town.name} y_km must be finite")
            _require_finite(town.radius_km, f"town {town.name} radius_km must be finite")
            if not (0 <= town.x_km <= self.map_width_km and 0 <= town.y_km <= self.map_height_km):
                raise ValueError(f"town {town.name} centre must be inside the map")
            if town.radius_km <= 0:
                raise ValueError(f"town {town.name} radius_km must be greater than zero")
            _require_count(town.phone_count, f"town {town.name} phone_count")

        _require_count(self.rural_phone_count, "rural_phone_count")
        if self.rural_phone_count + sum(t.phone_count for t in self.towns) == 0:
            raise ValueError("the world must contain at least one phone")

        _require_finite(self.clock_offset_sd_s, "clock_offset_sd_s must be finite")
        if self.clock_offset_sd_s < 0:
            raise ValueError("clock_offset_sd_s cannot be negative")

        for name in ("depth_min_km", "depth_max_km", "origin_time_min_s", "origin_time_max_s"):
            _require_finite(getattr(self, name), f"{name} must be finite")
        if not 0 <= self.depth_min_km <= self.depth_max_km:
            raise ValueError("need 0 <= depth_min_km <= depth_max_km")
        if self.origin_time_min_s > self.origin_time_max_s:
            raise ValueError("need origin_time_min_s <= origin_time_max_s")

        if not isinstance(self.nominal_speeds, WaveSpeeds):
            raise TypeError("nominal_speeds must be a WaveSpeeds object")
        p, s = self.nominal_speeds.p_km_s, self.nominal_speeds.s_km_s
        if p <= s:
            raise ValueError("nominal P-wave speed must be greater than nominal S-wave speed")
        _require_finite(self.speed_perturbation, "speed_perturbation must be finite")
        # Each true speed is nominal * (1 + u) with |u| <= e. The slowest possible
        # P is p(1 - e) and the fastest possible S is s(1 + e). P stays faster
        # than S for EVERY draw exactly when p(1 - e) > s(1 + e), that is when
        # e < (p - s) / (p + s). For the defaults (6.0, 3.5) the limit is 0.263.
        # The check is done with the same floating-point operations that
        # generate_speeds uses, so rounding cannot break the guarantee.
        e = self.speed_perturbation
        if not (0 <= e and p * (1.0 - e) > s * (1.0 + e)):
            limit = max_speed_perturbation(self.nominal_speeds)
            raise ValueError(
                f"speed_perturbation must be at least 0 and below {limit:.6f} so that "
                "the P-wave is always faster than the S-wave"
            )
        # The fastest possible true P speed is p(1 + e). For very large finite
        # nominal speeds this product can be bigger than the largest float and
        # become infinity, and generate_speeds would then fail. Check it here,
        # with the same floating-point operations generate_speeds uses, so a
        # config that is accepted can always be generated. (The fastest S speed
        # needs no check: it is below the slowest P speed, which is finite.)
        if not math.isfinite(p * (1.0 + e)):
            raise ValueError(
                "speed_perturbation is too large for these nominal speeds: the "
                "fastest possible true P-wave speed would overflow to infinity"
            )


def max_speed_perturbation(speeds: WaveSpeeds) -> float:
    """Largest perturbation (exclusive) that keeps P faster than S for every draw:
    (p - s) / (p + s).

    Overflow guard: for very large finite speeds, p + s can be bigger than the
    largest float (about 1.8e308) and become infinity, which would make the
    answer 0. The ratio does not change if both speeds are divided by the same
    number, so both are first scaled down by the larger one. The scale used is
    the power of two just above max(p, s) (from math.frexp): dividing by a power
    of two only changes the float's exponent, so it is exact, and for ordinary
    speeds the result is bit-for-bit the same as the plain formula. After
    scaling both values are below 1, so their sum is below 2 and cannot overflow.
    """
    p, s = speeds.p_km_s, speeds.s_km_s
    _, exponent = math.frexp(max(p, s))
    p_scaled = math.ldexp(p, -exponent)
    s_scaled = math.ldexp(s, -exponent)
    return (p_scaled - s_scaled) / (p_scaled + s_scaled)


@dataclass(frozen=True)
class World:
    """One complete simulated world. All of it is ground truth."""

    seed: int
    stream: str
    config: WorldConfig
    phones: tuple
    quake: EarthquakeSource
    speeds: WaveSpeeds


def _require_count(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


MAX_SAMPLING_ATTEMPTS = 10_000


def _point_in_town(rng, town: Town, config: WorldConfig) -> tuple:
    """A uniformly random point in the part of the town's circle that lies on the map.

    Method (rejection sampling from a small box):
    1. Clip the circle's bounding square to the map. Call the result the box.
       The box contains every point that is both in the circle and on the map.
    2. Pick a point uniformly in the box, and keep it only if it is inside the
       circle. Points uniform over the box, kept only inside the circle, are
       uniform over (circle AND map): every point of that region has the same
       chance.

    Why this is fast: the box always contains the town centre, and no part of
    it is further than R from the centre along x or along y. For such a box at
    least pi/4 (about 79 %) of its area is inside the circle, so on average
    fewer than 1.3 tries are needed, however large the town is compared with the
    map. (The previous method drew points over the whole circle and could need
    millions of tries when most of the circle was off the map.)

    MAX_SAMPLING_ATTEMPTS is a safety net that should never be reached; if it
    is, something is wrong and we stop with an error instead of looping forever.
    """
    x_min = max(0.0, town.x_km - town.radius_km)
    x_max = min(config.map_width_km, town.x_km + town.radius_km)
    y_min = max(0.0, town.y_km - town.radius_km)
    y_max = min(config.map_height_km, town.y_km + town.radius_km)

    for _ in range(MAX_SAMPLING_ATTEMPTS):
        x = rng.uniform(x_min, x_max)
        y = rng.uniform(y_min, y_max)
        # math.hypot instead of comparing squares: squaring a very large finite
        # radius (e.g. 1e200 ** 2) raises OverflowError, but hypot computes the
        # distance without squaring large numbers, so it stays finite.
        if math.hypot(x - town.x_km, y - town.y_km) <= town.radius_km:
            return x, y

    raise RuntimeError(f"could not place a phone in town {town.name} "
                       f"after {MAX_SAMPLING_ATTEMPTS} attempts")


def generate_phones(seed: int, stream: str, config: WorldConfig) -> tuple:
    """All phones: town phones first (in town order), then rural phones."""

    rng = make_rng(seed, stream, "phones")
    phones = []

    def add(x, y):
        offset = rng.gauss(0.0, config.clock_offset_sd_s) if config.clock_offset_sd_s else 0.0
        phones.append(Phone(len(phones), x, y, offset))

    for town in config.towns:
        for _ in range(town.phone_count):
            add(*_point_in_town(rng, town, config))
    for _ in range(config.rural_phone_count):
        add(rng.uniform(0, config.map_width_km), rng.uniform(0, config.map_height_km))

    return tuple(phones)


def generate_quake(seed: int, stream: str, config: WorldConfig, quake_xy=None) -> EarthquakeSource:
    """The hidden earthquake. If quake_xy is given (e.g. where the user clicked),
    the epicentre is placed there; depth and origin time are still random."""

    rng = make_rng(seed, stream, "quake")
    # Always draw x and y, even when quake_xy is given, so that depth and origin
    # time are the same for a given seed wherever the user clicks.
    x = rng.uniform(0, config.map_width_km)
    y = rng.uniform(0, config.map_height_km)
    depth = rng.uniform(config.depth_min_km, config.depth_max_km)
    origin = rng.uniform(config.origin_time_min_s, config.origin_time_max_s)

    if quake_xy is not None:
        if len(quake_xy) != 2:
            raise ValueError("quake_xy must be (x_km, y_km)")
        x, y = quake_xy
        _require_finite(x, "quake x must be finite")
        _require_finite(y, "quake y must be finite")
        if not (0 <= x <= config.map_width_km and 0 <= y <= config.map_height_km):
            raise ValueError("quake_xy must be inside the map")

    return EarthquakeSource(x, y, depth, origin)


def generate_speeds(seed: int, stream: str, config: WorldConfig) -> WaveSpeeds:
    """True wave speeds: each nominal speed times (1 + u), u uniform in +/-perturbation."""

    rng = make_rng(seed, stream, "speeds")
    e = config.speed_perturbation

    def nudge():
        # uniform(-e, e) may round a hair past an end point; clamp it so the
        # draw is always within [-e, e], as WorldConfig's check assumes.
        return min(max(rng.uniform(-e, e), -e), e)

    p = config.nominal_speeds.p_km_s * (1.0 + nudge())
    s = config.nominal_speeds.s_km_s * (1.0 + nudge())
    # WorldConfig's limit guarantees this mathematically; the check guards
    # against any future change that breaks that guarantee.
    if not p > s:
        raise RuntimeError(f"generated P speed {p} is not greater than S speed {s}")
    return WaveSpeeds(p_km_s=p, s_km_s=s)


def generate_world(seed: int, stream: str = "demo", config: WorldConfig | None = None,
                   quake_xy=None) -> World:
    """Build a complete, reproducible world from a seed and stream."""

    config = WorldConfig() if config is None else config
    if not isinstance(config, WorldConfig):
        raise TypeError("config must be a WorldConfig")

    return World(
        seed=seed,
        stream=stream,
        config=config,
        phones=generate_phones(seed, stream, config),
        quake=generate_quake(seed, stream, config, quake_xy),
        speeds=generate_speeds(seed, stream, config),
    )
