"""Server settings. These are the server's ASSUMPTIONS and thresholds.

Note the wave speeds and depth here are what the server ASSUMES. The simulated
world uses slightly different true values (see outrun/sim/world.py), as in real
life, where nobody knows the exact speeds under a given place.

The thresholds were chosen using the "tuning" random stream only, and results
are reported on the separate "validation" stream (scripts/validate.py).
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    # What the server assumes about the Earth
    vp_km_s: float = 6.0
    vs_km_s: float = 3.5
    depth_km: float = 10.0

    # Region the server searches (the server knows its own monitoring area)
    region_width_km: float = 200.0
    region_height_km: float = 200.0
    search_margin_km: float = 50.0

    # Pre-filter
    window_s: float = 60.0          # only reports that arrived in the last 60 s
    max_window_reports: int = 300   # keeps the work bounded
    causality_slack_s: float = 1.0  # allowance for clock, cell and delay errors

    # Locator
    coarse_step_km: float = 4.0
    fine_step_km: float = 1.0
    fine_half_width_km: float = 6.0
    residual_cap_s: float = 1.5     # caps one bad report's influence in the grid search
    outlier_sigmas: float = 3.0
    outlier_floor_s: float = 0.5
    timing_noise_floor_s: float = 0.15  # never claim timing better than this
    model_error_km: float = 2.5     # extra error from the server's simplified model
                                    # (fixed depth, approximate speeds); tuned on the
                                    # tuning stream so the 95 % circle is honest
    ambiguity_ratio: float = 1.1
    ambiguity_separation_km: float = 20.0
    max_reports_used: int = 200     # locate with at most this many reports
    post_alert_reports: int = 100   # reports still processed after the alert

    # Alert rule (the slider changes K only)
    k_default: int = 10
    k_min: int = 4
    k_max: int = 40
    rms_max_s: float = 0.6
    predicted_error_max_km: float = 10.0
    gap_max_deg: float = 240.0      # reports must not all lie on one side
    confirm_min_distance_km: float = 2.0  # two updates "agree" within this (or their error)
    confirmations_required: int = 1   # consecutive passing updates needed (1 = no wait)

    # Silent-phones check (the server's own assumptions, deliberately not the
    # simulation's exact detection rules)
    silence_radius_km: float = 25.0   # phones this close should feel the quake
    silence_latency_s: float = 4.5    # detection + upload allowance before expecting a report
    silence_min_expected: int = 5     # only judge silence when at least this many are expected
    silence_min_fraction: float = 0.3 # at least this share of expected phones must report
    min_nearby_reports: int = 5       # reports needed from within silence_radius_km

    # Timing of the alert itself (assumed values)
    processing_s: float = 0.5
    delivery_s: float = 2.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if not self.vp_km_s > self.vs_km_s > 0:
            raise ValueError("need vp_km_s > vs_km_s > 0")
        if self.depth_km < 0:
            raise ValueError("depth_km cannot be negative")
        if not 4 <= self.k_min <= self.k_default <= self.k_max:
            raise ValueError("need 4 <= k_min <= k_default <= k_max")
        for name in ("coarse_step_km", "fine_step_km", "window_s", "region_width_km",
                     "region_height_km", "outlier_floor_s", "timing_noise_floor_s"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")
