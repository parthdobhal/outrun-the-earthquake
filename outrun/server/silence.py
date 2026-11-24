"""Silent-phones check: an estimate is rejected if the phones nearest to it are silent.

If an earthquake really started at the estimated place and time, the active phones
near it would have felt the P-wave first and their reports would have arrived by
now. If most of them are silent, the estimate cannot be right, however well it
fits the reports that DID arrive. (Real early-warning systems use the same idea:
"not-yet-triggered" stations are evidence too.)

The server knows only HOW MANY active phones are in each 2 km cell (from regular
check-ins), not where they are. A cell "should have reported by now" when:

    it is within silence_radius_km of the estimated epicentre, and
    t0_est + P travel time + silence_latency_s <= now

expected = active phones in those cells
actual   = reports received from those cells (at most the cell's phone count)
The check fails when expected >= silence_min_expected and
actual < silence_min_fraction x expected.
"""

import math

import numpy as np


class CellCounts:
    """Active phones per cell, as numpy arrays (built once per run)."""

    def __init__(self, cell_counts):
        rows = list(cell_counts)
        self.x = np.array([float(r["cell_x_km"]) for r in rows])
        self.y = np.array([float(r["cell_y_km"]) for r in rows])
        self.phones = np.array([int(r["phones"]) for r in rows])
        self.index = {(float(r["cell_x_km"]), float(r["cell_y_km"])): i for i, r in enumerate(rows)}


def nearby_report_count(estimate, window_messages, cfg) -> int:
    """Reports received from cells within silence_radius_km of the estimate.

    Positive evidence: a real earthquake always produces reports near its own
    epicentre. A wrong estimate in empty countryside has none, and the silence
    check alone cannot catch it there (no phones nearby means none are silent)."""
    r2 = cfg.silence_radius_km ** 2
    return sum((m.cell_x_km - estimate.x_km) ** 2 + (m.cell_y_km - estimate.y_km) ** 2 <= r2
               for m in window_messages)


def active_phones_near(estimate, cells: CellCounts, cfg) -> int:
    """Active phones in cells within silence_radius_km of the estimate."""
    if cells is None or len(cells.phones) == 0:
        return 0
    d = np.hypot(cells.x - estimate.x_km, cells.y - estimate.y_km)
    return int(cells.phones[d <= cfg.silence_radius_km].sum())


def nearby_reports_required(active_near: int, cfg, have_counts: bool) -> int:
    """How many nearby reports the alert rule needs.

    min_nearby_reports normally, but no more than silence_min_fraction of the
    active phones that are actually there (sparse areas have few phones), and at
    least 1. Without phone counts the fixed number is used."""
    if not have_counts:
        return cfg.min_nearby_reports
    return max(1, min(cfg.min_nearby_reports,
                      math.ceil(cfg.silence_min_fraction * active_near)))


def silence_check(estimate, now_s, cells: CellCounts, window_messages, cfg):
    """Returns (expected_reporters, actual_reporters, ok)."""
    if cells is None or len(cells.phones) == 0:
        return 0, 0, True
    d = np.hypot(cells.x - estimate.x_km, cells.y - estimate.y_km)
    p_arrival = estimate.origin_time_s + np.sqrt(d * d + cfg.depth_km ** 2) / cfg.vp_km_s
    due = (d <= cfg.silence_radius_km) & (p_arrival + cfg.silence_latency_s <= now_s)
    expected = int(cells.phones[due].sum())

    reported = np.zeros(len(cells.phones), dtype=int)
    for message in window_messages:
        i = cells.index.get((message.cell_x_km, message.cell_y_km))
        if i is not None:
            reported[i] += 1
    actual = int(np.minimum(reported, cells.phones)[due].sum())

    ok = expected < cfg.silence_min_expected or actual >= cfg.silence_min_fraction * expected
    return expected, actual, bool(ok)
