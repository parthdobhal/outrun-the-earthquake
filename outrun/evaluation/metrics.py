"""Compare the server's results with the hidden truth, AFTER a run.

This is the only code that sees both the ground truth (from outrun.sim) and the
server's output. It never feeds anything back into the server.

Everything here describes our SIMULATION, not real earthquakes.
"""

import math
import statistics
from dataclasses import dataclass

from outrun.server.config import ServerConfig
from outrun.server.decide import first_alert_snapshot, run_server
from outrun.server.warn import predicted_warning_s
from outrun.sim.model import s_wave_arrival_time
from outrun.sim.reports import ReportConfig, active_phone_counts, generate_reports
from outrun.sim.world import WorldConfig, generate_world


@dataclass(frozen=True)
class QuakeResult:
    """How the server did on one hidden earthquake."""

    seed: int
    inside_network: bool
    alerted: bool
    alert_delay_s: float          # alert issued minus true origin time
    location_error_km: float      # at alert time
    final_location_error_km: float
    origin_time_error_s: float    # estimate minus truth, at alert time
    predicted_error_km: float
    inside_predicted_error: bool  # truth within the predicted error radius
    warnings: tuple               # (place, predicted_s, true_s) per place
    false_reassurance: int        # places told "you have time" that had none


def phones_near(world, x, y, radius_km):
    return sum(math.hypot(p.x_km - x, p.y_km - y) <= radius_km for p in world.phones)


def is_inside_network(world, radius_km=30.0, min_phones=20):
    """Simple definition used for reporting: at least 20 phones within 30 km."""
    return phones_near(world, world.quake.x_km, world.quake.y_km, radius_km) >= min_phones


def true_warning_s(world, x_km, y_km, t_delivered_s):
    return s_wave_arrival_time(world.quake, x_km, y_km, world.speeds) - t_delivered_s


def evaluate_quake(seed, stream="validation", k=None, world_config=None, report_config=None,
                   server_config=None, places=None) -> QuakeResult:
    """Generate a hidden quake, run the server on its reports only, then compare."""
    server_config = ServerConfig() if server_config is None else server_config
    world = generate_world(seed, stream, world_config)
    reports, _truths = generate_reports(world, report_config)
    # Only plain report data crosses to the server.
    run = run_server([r.to_dict() for r in reports], k, server_config, keep_snapshots=False,
                     cell_counts=active_phone_counts(world, report_config))

    q = world.quake
    if places is None:
        places = tuple((t.name, t.x_km, t.y_km) for t in world.config.towns)
    final = run.final_estimate
    final_error = (math.hypot(final.x_km - q.x_km, final.y_km - q.y_km)
                   if final is not None else math.nan)

    if run.alert is None:
        return QuakeResult(seed, is_inside_network(world), False, math.nan, math.nan,
                           final_error, math.nan, math.nan, False, (), 0)

    e = run.alert.estimate
    error = math.hypot(e.x_km - q.x_km, e.y_km - q.y_km)
    warnings, false_reassurance = [], 0
    for name, x, y in places:
        predicted = predicted_warning_s(e, x, y, run.alert.t_delivered_s, server_config)
        actual = true_warning_s(world, x, y, run.alert.t_delivered_s)
        warnings.append((name, predicted, actual))
        if predicted > 0 >= actual:
            false_reassurance += 1
    return QuakeResult(
        seed=seed, inside_network=is_inside_network(world), alerted=True,
        alert_delay_s=run.alert.t_issued_s - q.origin_time_s,
        location_error_km=error, final_location_error_km=final_error,
        origin_time_error_s=e.origin_time_s - q.origin_time_s,
        predicted_error_km=e.predicted_error_km,
        inside_predicted_error=error <= e.predicted_error_km,
        warnings=tuple(warnings), false_reassurance=false_reassurance,
    )


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return math.nan
    index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
    return values[index]


def summarise(results) -> dict:
    """Summary numbers for a list of QuakeResult."""
    inside = [r for r in results if r.inside_network]
    alerted_inside = [r for r in inside if r.alerted]
    alerted = [r for r in results if r.alerted]
    errors = [r.location_error_km for r in alerted_inside]
    place_runs = sum(len(r.warnings) for r in alerted)
    return {
        "quakes": len(results),
        "inside_network": len(inside),
        "alerted": len(alerted),
        "missed_inside_network": len(inside) - len(alerted_inside),
        "missed_inside_network_pct": 100.0 * (len(inside) - len(alerted_inside)) / len(inside) if inside else math.nan,
        "median_error_km": statistics.median(errors) if errors else math.nan,
        "p90_error_km": percentile(errors, 0.9),
        "median_alert_delay_s": statistics.median(r.alert_delay_s for r in alerted) if alerted else math.nan,
        "origin_time_bias_s": statistics.fmean(r.origin_time_error_s for r in alerted) if alerted else math.nan,
        "within_predicted_error_pct": 100.0 * sum(r.inside_predicted_error for r in alerted) / len(alerted) if alerted else math.nan,
        "false_reassurance_pct": 100.0 * sum(r.false_reassurance for r in alerted) / place_runs if place_runs else 0.0,
        "errors_km": errors,
        "alert_delays_s": [r.alert_delay_s for r in alerted],
    }


def false_alarm_hours(k_values, seeds, stream="validation", world_config=None,
                      report_config=None, server_config=None) -> dict:
    """For each K: in how many simulated one-hour periods of pure noise (no
    earthquake, only bumped phones) the server raised at least one alert.

    One server pass per hour serves every K, because the server's estimates do
    not depend on K (see first_alert_snapshot)."""
    server_config = ServerConfig() if server_config is None else server_config
    report_config = ReportConfig() if report_config is None else report_config
    one_hour = ReportConfig(**{**report_config.__dict__, "duration_s": 3600.0})
    counts = {k: 0 for k in k_values}
    for seed in seeds:
        world = generate_world(seed, stream, world_config)
        reports, _ = generate_reports(world, one_hour, include_quake=False)
        run = run_server([r.to_dict() for r in reports], server_config.k_min, server_config,
                         keep_snapshots=True, stop_after_alert=False,
                         cell_counts=active_phone_counts(world, one_hour))
        for k in k_values:
            if first_alert_snapshot(run.snapshots, k, server_config) is not None:
                counts[k] += 1
    return {"hours": len(seeds), "hours_with_false_alert": counts}


def run_hidden_test(n, k=None, stream="validation", start_seed=0, world_config=None,
                    report_config=None, server_config=None) -> dict:
    """n hidden random earthquakes; returns the summary plus per-quake rows."""
    results = [evaluate_quake(seed, stream, k, world_config, report_config, server_config)
               for seed in range(start_seed, start_seed + n)]
    summary = summarise(results)
    summary["k"] = (ServerConfig() if server_config is None else server_config).k_default if k is None else k
    summary["rows"] = [{"seed": r.seed, "inside_network": r.inside_network, "alerted": r.alerted,
                        "location_error_km": r.location_error_km,
                        "alert_delay_s": r.alert_delay_s} for r in results]
    return summary
