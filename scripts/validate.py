#!/usr/bin/env python3
"""Blind validation of Outrun the Earthquake. Writes RESULTS.md.

Every quake here comes from the "validation" random stream, which was never
used while choosing the server's thresholds (those were chosen on the "tuning"
stream). The server receives only phone reports and per-cell phone counts; only
this evaluation code compares its answers with the hidden truth.

All numbers describe our SIMULATION, not real earthquakes.

Usage (from the project root, takes several minutes):
    python scripts/validate.py              # full run
    python scripts/validate.py --quick      # smaller run for a fast check
"""

import argparse
import dataclasses
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outrun.evaluation.metrics import false_alarm_hours, run_hidden_test  # noqa: E402
from outrun.server.config import ServerConfig  # noqa: E402
from outrun.sim.reports import ReportConfig  # noqa: E402
from outrun.sim.world import WorldConfig  # noqa: E402

# Proposed acceptance criteria, fixed BEFORE running on the validation stream.
TARGETS = {
    "median_error_km": ("<=", 3.0),
    "p90_error_km": ("<=", 8.0),
    "missed_inside_network_pct": ("<=", 2.0),
    "false_reassurance_pct": ("<=", 1.0),
    "within_predicted_error_pct": ("between", (85.0, 99.0)),
}


def fmt(value, digits=2):
    if isinstance(value, float):
        return "n/a" if value != value else f"{value:.{digits}f}"
    return str(value)


def check(summary, false_alarms_k10):
    rows = []
    for key, (kind, target) in TARGETS.items():
        value = summary[key]
        if kind == "<=":
            ok, text = value <= target, f"<= {target}"
        else:
            ok, text = target[0] <= value <= target[1], f"{target[0]}-{target[1]}"
        rows.append((key, fmt(value), text, "PASS" if ok else "FAIL"))
    rows.append(("false alerts at K=10 (hours with any)", str(false_alarms_k10), "0", "PASS" if false_alarms_k10 == 0 else "FAIL"))
    return rows


def sweep_row(label, summary):
    return (f"| {label} | {summary['inside_network']} | {summary['alerted']} | "
            f"{fmt(summary['missed_inside_network_pct'], 1)} | {fmt(summary['median_error_km'])} | "
            f"{fmt(summary['p90_error_km'])} | {fmt(summary['median_alert_delay_s'])} |")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="smaller, faster run")
    args = parser.parse_args()
    n_base, n_k, n_sweep, hours = (40, 20, 15, 4) if args.quick else (200, 100, 50, 20)

    start = time.time()
    lines = []
    out = lines.append
    out("# Validation results (simulation only)\n")
    out(f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/validate.py`"
        f"{' --quick' if args.quick else ''} on Python {platform.python_version()}.\n")
    out("All quakes come from the **validation** random stream, which was not used to choose "
        "any threshold. The server saw only phone reports and per-cell phone counts. "
        "**These numbers describe our simulation, not real earthquakes.**\n")

    print(f"Baseline: {n_base} hidden quakes at K=10 ...", flush=True)
    base = run_hidden_test(n_base, k=10, stream="validation")
    print("False alarms ...", flush=True)
    fa = false_alarm_hours(range(4, 41), range(1000, 1000 + hours), stream="validation")
    fa10 = fa["hours_with_false_alert"][10]

    out("## Baseline (K = 10)\n")
    out("| Measure | Result | Proposed target | |\n|---|---|---|---|")
    for key, value, target, verdict in check(base, fa10):
        out(f"| {key} | {value} | {target} | {verdict} |")
    out(f"\nOther measures: {base['quakes']} quakes, {base['inside_network']} inside the phone "
        f"network (at least 20 phones within 30 km), {base['alerted']} alerted; median alert "
        f"{fmt(base['median_alert_delay_s'])} s after the quake started; average origin-time "
        f"error {fmt(base['origin_time_bias_s'], 2)} s (positive = estimated later than true; "
        "mostly the phones' detection delay, which the server does not model).\n")

    out("## The report threshold K (the slider)\n")
    out(f"{n_k} hidden quakes per K, and {hours} simulated hours of noise (no earthquake) "
        "to count false alerts.\n")
    out("| K | Alerted | Median error (km) | 90th pct error (km) | Median alert delay (s) | Noise hours with a false alert |")
    out("|---|---|---|---|---|---|")
    for k in (4, 6, 10, 20, 40):
        print(f"K={k} ...", flush=True)
        s = run_hidden_test(n_k, k=k, stream="validation", start_seed=5000)
        out(f"| {k} | {s['alerted']}/{s['quakes']} | {fmt(s['median_error_km'])} | {fmt(s['p90_error_km'])} | "
            f"{fmt(s['median_alert_delay_s'])} | {fa['hours_with_false_alert'][k]} of {fa['hours']} |")

    out("\n## Robustness sweeps (K = 10, no pass/fail)\n")
    out(f"{n_sweep} hidden quakes per row.\n")
    out("| Condition | Inside network | Alerted | Missed inside (%) | Median error (km) | 90th pct error (km) | Median alert delay (s) |")
    out("|---|---|---|---|---|---|---|")
    sweeps = [
        ("Baseline", {}, {}, {}),
        ("50 % of phones online", {}, {"online_fraction": 0.5}, {}),
        ("25 % of phones online", {}, {"online_fraction": 0.25}, {}),
        ("10 % of phones online", {}, {"online_fraction": 0.10}, {}),
        ("Upload delays x2", {}, {"upload_delay_scale": 2.0}, {}),
        ("Upload delays x4", {}, {"upload_delay_scale": 4.0}, {}),
        ("Clock error 0.2 s", {"clock_offset_sd_s": 0.2}, {}, {}),
        ("Clock error 0.5 s", {"clock_offset_sd_s": 0.5}, {}, {}),
        ("False reports x5", {}, {"false_rate_per_hour": 2.5}, {}),
        ("False reports x20", {}, {"false_rate_per_hour": 10.0}, {}),
        ("Late S-wave reports 10 %", {}, {"late_s_fraction": 0.10}, {}),
        ("Late S-wave reports 30 %", {}, {"late_s_fraction": 0.30}, {}),
        ("Towns only (no countryside phones)", {"rural_phone_count": 0}, {}, {}),
        ("Inverse-crime check: true speeds = assumed, depth = 10 km",
         {"speed_perturbation": 0.0, "depth_min_km": 10.0, "depth_max_km": 10.0}, {}, {}),
    ]
    for label, world_changes, report_changes, server_changes in sweeps:
        print(f"Sweep: {label} ...", flush=True)
        s = run_hidden_test(n_sweep, k=10, stream="validation", start_seed=9000,
                            world_config=WorldConfig(**world_changes),
                            report_config=ReportConfig(**report_changes),
                            server_config=ServerConfig(**server_changes))
        out(sweep_row(label, s))

    out("\n## How to read this\n")
    out("- **Inside network** means at least 20 phones within 30 km of the epicentre. Quakes "
        "outside it are harder, and are not counted as missed if no alert is sent.")
    out("- The **inverse-crime check** gives the server a perfect model. Its errors should be "
        "smaller than the baseline's; the gap shows how much the deliberately imperfect "
        "model costs, and that we did not test with the same model we solve with.")
    out("- Thresholds were tuned on the tuning stream; targets were set before this run. "
        "A FAIL is reported as it is, not hidden by changing the target.")
    out("\n## Validation history (disclosed)\n")
    out("This validation stream was run three times during development. Each time it "
        "revealed a weakness, the fix was chosen using the **tuning** stream only, then "
        "validation was run again:")
    out("1. First run: with phones only in towns, alerts had a median error of 18.2 km and a "
        "90th percentile of 71.5 km (wrong estimates in empty countryside passed the silent-"
        "phones check because no phones were there to be silent). Fix: also require reports "
        "from near the estimate.")
    out("2. Second run: requiring a fixed 5 nearby reports made sparse networks miss many "
        "quakes (25 % missed with a quarter of phones online, 69 % with a tenth). Fix: require "
        "5, or 30 % of the active phones actually near the estimate if that is fewer (at least 1).")
    out("3. This file is the third run.")
    out(f"\nRun time: {time.time() - start:.0f} s.")

    path = ROOT / "RESULTS.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {path} in {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()
