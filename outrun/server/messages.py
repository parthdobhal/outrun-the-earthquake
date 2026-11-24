"""What the server receives and produces.

The server defines its OWN message type instead of importing the simulation's
PhoneReport: reports cross the data wall only as plain data (dictionaries),
exactly as a real server would receive them over a network.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReportMessage:
    """One phone report as the server sees it."""

    report_id: int
    cell_x_km: float
    cell_y_km: float
    t_detect_s: float
    t_received_s: float

    @staticmethod
    def from_dict(data: dict) -> "ReportMessage":
        message = ReportMessage(int(data["report_id"]), float(data["cell_x_km"]),
                                float(data["cell_y_km"]), float(data["t_detect_s"]),
                                float(data["t_received_s"]))
        for value in (message.cell_x_km, message.cell_y_km, message.t_detect_s,
                      message.t_received_s):
            if not math.isfinite(value):
                raise ValueError("report values must be finite")
        return message


@dataclass(frozen=True)
class Estimate:
    """The server's estimate of where and when the earthquake started."""

    x_km: float
    y_km: float
    origin_time_s: float
    inlier_ids: tuple          # report_ids the locator trusted
    candidate_count: int       # reports that passed the pre-filter
    rms_s: float               # timing misfit of the inliers
    predicted_error_km: float  # radius of the ~95 % error circle (largest axis)
    gap_deg: float             # largest angle around the estimate with no reports
    ambiguous: bool            # two separate locations fit almost equally well
    valid: bool                # False if most candidates were rejected
    expected_reporters: int = 0   # active phones that should have reported by now
    actual_reporters: int = 0     # how many of those cells' phones did report
    silence_ok: bool = True       # False if the phones nearest the estimate are silent
    nearby_reports: int = 0       # reports received from within silence_radius_km
    nearby_required: int = 0      # how many of those the alert rule needs here

    @property
    def inlier_count(self) -> int:
        return len(self.inlier_ids)

    def to_dict(self) -> dict:
        def num(v):
            return None if not math.isfinite(v) else round(v, 4)
        return {"x_km": num(self.x_km), "y_km": num(self.y_km),
                "origin_time_s": num(self.origin_time_s), "inlier_count": self.inlier_count,
                "candidate_count": self.candidate_count, "rms_s": num(self.rms_s),
                "predicted_error_km": num(self.predicted_error_km),
                "gap_deg": num(self.gap_deg), "ambiguous": self.ambiguous,
                "valid": self.valid, "expected_reporters": self.expected_reporters,
                "actual_reporters": self.actual_reporters, "silence_ok": self.silence_ok,
                "nearby_reports": self.nearby_reports,
                "nearby_required": self.nearby_required}


@dataclass(frozen=True)
class Alert:
    """An issued (simulated) alert."""

    trigger_report_id: int
    t_issued_s: float      # server decided (after processing time)
    t_delivered_s: float   # alert reaches people (after delivery delay)
    estimate: Estimate


@dataclass(frozen=True)
class Snapshot:
    """The server's state just after one report arrived (for the replay)."""

    t_s: float
    reports_received: int
    estimate: Estimate | None


@dataclass(frozen=True)
class ServerRun:
    """Everything the server did while processing a stream of reports."""

    k_required: int
    alert: Alert | None
    snapshots: tuple = field(default_factory=tuple)
    final_estimate: Estimate | None = None
    reports_processed: int = 0
