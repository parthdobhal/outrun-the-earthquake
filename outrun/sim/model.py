
"""Scientific model for the Outrun the Earthquake simulation.

All coordinates are measured in kilometres and all times in seconds.

Simulation times are relative to the start of the simulation (t = 0 s), not
real clock times. Keep them small: floating-point numbers hold only about
15-16 significant digits, so very large absolute times would lose sub-second
precision in arrival times.

Simplifying assumptions (this is a teaching simulation, not a seismic model):
- Uniform crust: waves travel in straight lines at constant P and S speeds.
  Real crust is layered, so real travel times differ.
- Flat surface: x and y are flat-map kilometres (no Earth curvature) and every
  observation point sits on the surface at z = 0 (no elevation). This is a
  reasonable approximation over a few hundred kilometres.
- Point source: the earthquake starts at a single point at depth_km below the
  surface; the length of a real fault rupture is not modelled.
"""

from dataclasses import dataclass
from math import hypot, isfinite


def _require_finite(value: float, message: str) -> None:
    """Raise ValueError(message) unless `value` is a finite number.

    Integers too large to convert to a float (e.g. 10**400) make isfinite()
    raise OverflowError; those are reported as ValueError too. Non-numbers
    still raise TypeError, exactly as isfinite() does.
    """
    try:
        finite = isfinite(value)
    except OverflowError:
        raise ValueError(message) from None
    if not finite:
        raise ValueError(message)


@dataclass(frozen=True)
class EarthquakeSource:
    """Ground-truth location and origin time of a simulated earthquake."""

    x_km: float
    y_km: float
    depth_km: float
    origin_time_s: float

    def __post_init__(self) -> None:
        values = {
            "x_km": self.x_km,
            "y_km": self.y_km,
            "depth_km": self.depth_km,
            "origin_time_s": self.origin_time_s,
        }

        for name, value in values.items():
            _require_finite(value, f"{name} must be finite")

        if self.depth_km < 0:
            raise ValueError("depth_km cannot be negative")


@dataclass(frozen=True)
class WaveSpeeds:
    """Wave propagation speeds, measured in kilometres per second."""

    p_km_s: float = 6.0
    s_km_s: float = 3.5

    def __post_init__(self) -> None:
        values = {
            "p_km_s": self.p_km_s,
            "s_km_s": self.s_km_s,
        }

        for name, value in values.items():
            _require_finite(value, f"{name} must be finite")

            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")


def distance_3d(
    source: EarthquakeSource,
    x_km: float,
    y_km: float,
) -> float:
    """Calculate 3D distance from an earthquake source to a surface point."""

    _require_finite(x_km, "Observation coordinates must be finite")
    _require_finite(y_km, "Observation coordinates must be finite")

    dx = x_km - source.x_km
    dy = y_km - source.y_km
    dz = source.depth_km

    # hypot avoids overflow from squaring large-but-finite differences.
    distance = hypot(dx, dy, dz)
    _require_finite(distance, "Distance is too large to represent")
    return distance


def p_wave_arrival_time(
    source: EarthquakeSource,
    x_km: float,
    y_km: float,
    speeds: WaveSpeeds = WaveSpeeds(),
) -> float:
    """Calculate the P-wave arrival time at a surface location."""

    distance = distance_3d(source, x_km, y_km)
    arrival = source.origin_time_s + distance / speeds.p_km_s
    _require_finite(arrival, "P-wave arrival time is too large to represent")
    return arrival


def s_wave_arrival_time(
    source: EarthquakeSource,
    x_km: float,
    y_km: float,
    speeds: WaveSpeeds = WaveSpeeds(),
) -> float:
    """Calculate the S-wave arrival time at a surface location."""

    distance = distance_3d(source, x_km, y_km)
    arrival = source.origin_time_s + distance / speeds.s_km_s
    _require_finite(arrival, "S-wave arrival time is too large to represent")
    return arrival
