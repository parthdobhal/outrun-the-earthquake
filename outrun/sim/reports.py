"""Phone reports: the ONLY information that crosses from the simulation to the server.

A real phone that feels shaking sends a short message: roughly where it is and
when it felt it. Here we simulate that message (a PhoneReport) for every phone.

What a PhoneReport contains (and the server may see):
    report_id     a number used only to tell reports apart
    cell_x_km     centre of the 2 km grid cell the phone is in (NOT its true position,
    cell_y_km     mirroring the privacy coarsening used by real systems)
    t_detect_s    when the phone says it detected shaking, read from ITS OWN clock
    t_received_s  when the message reached the server

The server also receives, once, the number of active phones in each cell
(active_phone_counts): a count only, as real systems know from regular check-ins.

What a report does NOT contain: the phone's true position, its clock error,
whether the report is genuine, or anything about the earthquake. Those stay in
ReportTruth, which only the simulation and the evaluation code may use.

How reports are made (all simulated assumptions, listed in docs/ASSUMPTIONS.md):
- Only "online" phones take part (online_fraction of them, chosen at random).
- Detection chance falls with distance from the hypocentre: certain within
  detect_full_km, falling in a straight line to zero at detect_zero_km
  (one fixed, moderate earthquake: we do not model magnitude).
- A detecting phone notices the P-wave after a short delay (detect_delay_s range).
  A fraction late_s_fraction of them miss the P-wave and only notice the S-wave.
- The phone stamps the time with its own clock, which is off by its clock_offset_s.
- The report reaches the server after an upload delay (upload_delay_s range,
  multiplied by upload_delay_scale).
- "Bumped" phones send false reports at random times (false_rate_per_hour per phone).
"""

import math
from dataclasses import dataclass

from outrun.sim.model import _require_finite, p_wave_arrival_time, s_wave_arrival_time
from outrun.sim.rng import make_rng
from outrun.sim.world import World

KIND_P = "P"          # genuine report of the P-wave
KIND_LATE_S = "late_S"  # genuine shaking, but the phone only noticed the S-wave
KIND_FALSE = "false"   # a bumped or dropped phone, not an earthquake


@dataclass(frozen=True)
class PhoneReport:
    """What the server receives. Contains no ground truth."""

    report_id: int
    cell_x_km: float
    cell_y_km: float
    t_detect_s: float
    t_received_s: float

    def to_dict(self) -> dict:
        return {"report_id": self.report_id, "cell_x_km": self.cell_x_km,
                "cell_y_km": self.cell_y_km, "t_detect_s": self.t_detect_s,
                "t_received_s": self.t_received_s}

    @staticmethod
    def from_dict(data: dict) -> "PhoneReport":
        return PhoneReport(int(data["report_id"]), float(data["cell_x_km"]),
                           float(data["cell_y_km"]), float(data["t_detect_s"]),
                           float(data["t_received_s"]))


@dataclass(frozen=True)
class ReportTruth:
    """Ground truth about one report (simulation and evaluation only)."""

    report_id: int
    phone_id: int
    kind: str              # KIND_P, KIND_LATE_S or KIND_FALSE
    true_detect_s: float   # true time the phone detected (without its clock error)


@dataclass(frozen=True)
class ReportConfig:
    """Assumptions about phones and the network. None of these are measurements."""

    cell_size_km: float = 2.0
    online_fraction: float = 1.0
    detect_full_km: float = 30.0
    detect_zero_km: float = 100.0
    detect_delay_min_s: float = 0.2
    detect_delay_max_s: float = 1.0
    late_s_fraction: float = 0.03
    upload_delay_min_s: float = 0.5
    upload_delay_max_s: float = 3.0
    upload_delay_scale: float = 1.0
    false_rate_per_hour: float = 0.5
    duration_s: float = 90.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _require_finite(getattr(self, name), f"{name} must be finite")
        if self.cell_size_km <= 0:
            raise ValueError("cell_size_km must be greater than zero")
        if not 0 < self.online_fraction <= 1:
            raise ValueError("online_fraction must be in (0, 1]")
        if not 0 <= self.detect_full_km <= self.detect_zero_km:
            raise ValueError("need 0 <= detect_full_km <= detect_zero_km")
        if not 0 <= self.detect_delay_min_s <= self.detect_delay_max_s:
            raise ValueError("need 0 <= detect_delay_min_s <= detect_delay_max_s")
        if not 0 <= self.late_s_fraction <= 1:
            raise ValueError("late_s_fraction must be in [0, 1]")
        if not 0 <= self.upload_delay_min_s <= self.upload_delay_max_s:
            raise ValueError("need 0 <= upload_delay_min_s <= upload_delay_max_s")
        if self.upload_delay_scale < 0:
            raise ValueError("upload_delay_scale cannot be negative")
        if self.false_rate_per_hour < 0:
            raise ValueError("false_rate_per_hour cannot be negative")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be greater than zero")


def cell_centre(value_km: float, cell_size_km: float) -> float:
    """Centre of the grid cell containing value_km (cells start at 0)."""
    return (math.floor(value_km / cell_size_km) + 0.5) * cell_size_km


def detection_probability(distance_km: float, config: ReportConfig) -> float:
    """1 within detect_full_km, falling linearly to 0 at detect_zero_km."""
    if distance_km <= config.detect_full_km:
        return 1.0
    if distance_km >= config.detect_zero_km:
        return 0.0
    span = config.detect_zero_km - config.detect_full_km
    return (config.detect_zero_km - distance_km) / span


def online_phones(world: World, config: ReportConfig) -> list:
    """The phones taking part in this world (same choice every time for a seed)."""
    rng_online = make_rng(world.seed, world.stream, "reports", "online")
    return [p for p in world.phones if rng_online.random() < config.online_fraction]


def active_phone_counts(world: World, config: ReportConfig | None = None) -> tuple:
    """How many online phones are in each grid cell, as plain data for the server.

    Real systems know roughly how many active phones are in an area because phones
    check in regularly. Only a COUNT per coarse cell is shared: no positions, no ids.
    Returns a tuple of dicts {"cell_x_km", "cell_y_km", "phones"}.
    """
    config = ReportConfig() if config is None else config
    counts = {}
    for phone in online_phones(world, config):
        cell = (cell_centre(phone.x_km, config.cell_size_km),
                cell_centre(phone.y_km, config.cell_size_km))
        counts[cell] = counts.get(cell, 0) + 1
    return tuple({"cell_x_km": cx, "cell_y_km": cy, "phones": n}
                 for (cx, cy), n in sorted(counts.items()))


def generate_reports(world: World, config: ReportConfig | None = None,
                     include_quake: bool = True) -> tuple:
    """Simulate every phone report for one world.

    Returns (reports, truths):
        reports  tuple of PhoneReport, sorted by arrival at the server
        truths   dict report_id -> ReportTruth (keep this away from the server)

    include_quake=False gives only false reports (used to measure false alarms).
    """
    config = ReportConfig() if config is None else config
    rng_detect = make_rng(world.seed, world.stream, "reports", "detect")
    rng_false = make_rng(world.seed, world.stream, "reports", "false")

    online = online_phones(world, config)
    raw = []  # (phone, kind, true_detect_s)

    if include_quake:
        quake, speeds = world.quake, world.speeds
        for phone in online:
            distance = math.hypot(phone.x_km - quake.x_km, phone.y_km - quake.y_km,
                                  quake.depth_km)
            # Always draw the same number of random numbers per phone, so that
            # changing one setting does not reshuffle every other phone.
            u_detect, u_late, u_delay = rng_detect.random(), rng_detect.random(), rng_detect.random()
            if u_detect >= detection_probability(distance, config):
                continue
            delay = config.detect_delay_min_s + u_delay * (config.detect_delay_max_s - config.detect_delay_min_s)
            if u_late < config.late_s_fraction:
                kind, arrival = KIND_LATE_S, s_wave_arrival_time(quake, phone.x_km, phone.y_km, speeds)
            else:
                kind, arrival = KIND_P, p_wave_arrival_time(quake, phone.x_km, phone.y_km, speeds)
            raw.append((phone, kind, arrival + delay))

    # False reports: a random process with the given total rate over duration_s.
    total_rate_per_s = len(online) * config.false_rate_per_hour / 3600.0
    t = 0.0
    while total_rate_per_s > 0:
        t += rng_false.expovariate(total_rate_per_s)
        if t > config.duration_s:
            break
        raw.append((online[rng_false.randrange(len(online))], KIND_FALSE, t))

    # Upload delays (from their own stream, so they do not shift detection draws).
    rng_upload = make_rng(world.seed, world.stream, "reports", "upload")
    built = []
    for phone, kind, true_detect in raw:
        upload = rng_upload.uniform(config.upload_delay_min_s, config.upload_delay_max_s)
        upload *= config.upload_delay_scale
        built.append((true_detect + upload, phone, kind, true_detect))

    built.sort(key=lambda item: (item[0], item[1].phone_id))
    reports, truths = [], {}
    for report_id, (t_received, phone, kind, true_detect) in enumerate(built):
        reports.append(PhoneReport(
            report_id=report_id,
            cell_x_km=cell_centre(phone.x_km, config.cell_size_km),
            cell_y_km=cell_centre(phone.y_km, config.cell_size_km),
            t_detect_s=true_detect + phone.clock_offset_s,
            t_received_s=t_received,
        ))
        truths[report_id] = ReportTruth(report_id, phone.phone_id, kind, true_detect)
    return tuple(reports), truths
