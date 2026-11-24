"""Glue between the browser, the simulation, the server and the evaluation.

Data flow for one run (the data wall):
    sim (world, reports, phone counts)  --plain dicts-->  server  --> estimate, alert
    evaluation compares the estimate with the truth AFTER the server has finished.

The browser also receives some ground truth (the epicentre the user clicked,
true phone positions, true wave speeds) so it can DRAW the simulated world. That
is display only: the server function never receives it.
"""

import math
import threading

from outrun.evaluation.metrics import false_alarm_hours, run_hidden_test, true_warning_s
from outrun.server.config import ServerConfig
from outrun.server.decide import run_server
from outrun.server.warn import predicted_blind_radius_km, predicted_warning_s
from outrun.sim.reports import ReportConfig, active_phone_counts, generate_reports
from outrun.sim.world import generate_world

SERVER_CONFIG = ServerConfig()
REPORT_CONFIG = ReportConfig()
DEMO_STREAM = "demo"
MAX_SEED = 1_000_000


class BadRequest(ValueError):
    """Invalid input from the browser (returned as HTTP 400)."""


def _number(data, name, low, high):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadRequest(f"{name} must be a number")
    if not low <= value <= high:
        raise BadRequest(f"{name} must be between {low} and {high}")
    return float(value)


def _integer(data, name, low, high, default=None):
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"{name} must be a whole number")
    if not low <= value <= high:
        raise BadRequest(f"{name} must be between {low} and {high}")
    return value


def r(value, digits=3):
    return None if value is None or not math.isfinite(value) else round(value, digits)


# ---------------------------------------------------------------------------
# World (for drawing)
# ---------------------------------------------------------------------------

def world_payload(seed):
    world = generate_world(seed, DEMO_STREAM)
    return {
        "simulation": True,
        "seed": seed,
        "map": {"width_km": world.config.map_width_km, "height_km": world.config.map_height_km},
        "towns": [{"name": t.name, "x_km": t.x_km, "y_km": t.y_km, "radius_km": t.radius_km}
                  for t in world.config.towns],
        "phones": [[round(p.x_km, 2), round(p.y_km, 2)] for p in world.phones],
        "k": {"min": SERVER_CONFIG.k_min, "max": SERVER_CONFIG.k_max,
              "default": SERVER_CONFIG.k_default},
    }


# ---------------------------------------------------------------------------
# One earthquake
# ---------------------------------------------------------------------------

def estimate_payload(estimate):
    return None if estimate is None else estimate.to_dict()


def run_payload(data):
    seed = _integer(data, "seed", 0, MAX_SEED, default=7)
    k = _integer(data, "k", SERVER_CONFIG.k_min, SERVER_CONFIG.k_max, default=SERVER_CONFIG.k_default)
    width, height = SERVER_CONFIG.region_width_km, SERVER_CONFIG.region_height_km
    quake_x = _number(data, "quake_x_km", 0.0, width)
    quake_y = _number(data, "quake_y_km", 0.0, height)
    you_x = _number(data, "you_x_km", 0.0, width) if "you_x_km" in data else 100.0
    you_y = _number(data, "you_y_km", 0.0, height) if "you_y_km" in data else 100.0

    # 1. Simulation (ground truth lives here)
    world = generate_world(seed, DEMO_STREAM, quake_xy=(quake_x, quake_y))
    reports, truths = generate_reports(world, REPORT_CONFIG)
    cells = active_phone_counts(world, REPORT_CONFIG)

    # 2. Server: receives plain report data and phone counts ONLY
    run = run_server([rep.to_dict() for rep in reports], k, SERVER_CONFIG, cell_counts=list(cells))

    # 3. Evaluation and display data (after the server has finished)
    q, speeds = world.quake, world.speeds
    processed_ids = {rep.report_id for rep in sorted(
        reports, key=lambda m: (m.t_received_s, m.report_id))[: run.reports_processed]}
    final = run.final_estimate
    trusted = set(final.inlier_ids) if final is not None else set()

    snapshots, last = [], None
    for snap in run.snapshots:
        if snap.estimate is not None and snap.estimate is not last:
            last = snap.estimate
            snapshots.append({"t_s": r(snap.t_s), "reports_received": snap.reports_received,
                              "estimate": estimate_payload(snap.estimate)})

    alert = None
    places = []
    if run.alert is not None:
        a, e = run.alert, run.alert.estimate
        t_del = a.t_delivered_s
        true_reach = speeds.s_km_s * (t_del - q.origin_time_s)
        alert = {
            "t_issued_s": r(a.t_issued_s), "t_delivered_s": r(t_del),
            "seconds_after_quake_start": r(a.t_issued_s - q.origin_time_s),
            "estimate": estimate_payload(e),
            "location_error_km": r(math.hypot(e.x_km - q.x_km, e.y_km - q.y_km)),
            "origin_time_error_s": r(e.origin_time_s - q.origin_time_s),
            "predicted_blind_radius_km": r(predicted_blind_radius_km(e, t_del, SERVER_CONFIG)),
            "true_blind_radius_km": r(math.sqrt(max(true_reach ** 2 - q.depth_km ** 2, 0.0))),
        }
        for name, x, y in [("You", you_x, you_y)] + [(t.name, t.x_km, t.y_km) for t in world.config.towns]:
            places.append({"name": name, "x_km": r(x), "y_km": r(y),
                           "predicted_warning_s": r(predicted_warning_s(e, x, y, t_del, SERVER_CONFIG)),
                           "true_warning_s": r(true_warning_s(world, x, y, t_del))})

    phone_of = {rid: tr.phone_id for rid, tr in truths.items()}
    return {
        "simulation": True,
        "seed": seed,
        "k": k,
        "truth": {"x_km": r(q.x_km), "y_km": r(q.y_km), "depth_km": r(q.depth_km),
                  "origin_time_s": r(q.origin_time_s), "vp_km_s": r(speeds.p_km_s),
                  "vs_km_s": r(speeds.s_km_s)},
        "reports": [{"id": rep.report_id, "phone": phone_of[rep.report_id],
                     "cell_x_km": rep.cell_x_km, "cell_y_km": rep.cell_y_km,
                     "t_detect_s": r(rep.t_detect_s), "t_received_s": r(rep.t_received_s),
                     "processed": rep.report_id in processed_ids,
                     "trusted": rep.report_id in trusted} for rep in reports],
        "reports_total": len(reports),
        "snapshots": snapshots,
        "alert": alert,
        "final_estimate": estimate_payload(final),
        "final_location_error_km": r(math.hypot(final.x_km - q.x_km, final.y_km - q.y_km)) if final else None,
        "places": places,
        "you": {"x_km": you_x, "y_km": you_y},
        "server_assumptions": {"vp_km_s": SERVER_CONFIG.vp_km_s, "vs_km_s": SERVER_CONFIG.vs_km_s,
                               "depth_km": SERVER_CONFIG.depth_km,
                               "processing_s": SERVER_CONFIG.processing_s,
                               "delivery_s": SERVER_CONFIG.delivery_s},
    }


# ---------------------------------------------------------------------------
# Hidden test (quakes the user cannot see)
# ---------------------------------------------------------------------------

def hidden_test_payload(data):
    k = _integer(data, "k", SERVER_CONFIG.k_min, SERVER_CONFIG.k_max, default=SERVER_CONFIG.k_default)
    n = _integer(data, "n", 1, 60, default=25)
    batch = _integer(data, "batch", 0, 10_000, default=0)
    summary = run_hidden_test(n, k=k, stream="validation", start_seed=20_000 + batch * n,
                              report_config=REPORT_CONFIG, server_config=SERVER_CONFIG)
    clean = {key: (r(v) if isinstance(v, float) else v) for key, v in summary.items()
             if key not in ("rows", "errors_km", "alert_delays_s")}
    clean["errors_km"] = [r(v) for v in summary["errors_km"]]
    clean["alert_delays_s"] = [r(v) for v in summary["alert_delays_s"]]
    clean["simulation"] = True
    clean["stream"] = "validation"
    clean["first_seed"] = 20_000 + batch * n
    return clean


# ---------------------------------------------------------------------------
# False alarms per K (measured once in the background, then cached)
# ---------------------------------------------------------------------------

class FalseAlarmCache:
    """Simulated hours of pure noise, measured once in a background thread."""

    def __init__(self, hours=6):
        self.hours, self.result, self.error = hours, None, None
        self._lock = threading.Lock()
        self._started = False

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            result = false_alarm_hours(range(SERVER_CONFIG.k_min, SERVER_CONFIG.k_max + 1),
                                       range(1000, 1000 + self.hours), stream="validation",
                                       report_config=REPORT_CONFIG, server_config=SERVER_CONFIG)
            with self._lock:
                self.result = result
        except Exception as err:  # reported to the browser, never hidden
            with self._lock:
                self.error = str(err)

    def payload(self):
        with self._lock:
            if self.error:
                return {"status": "error", "error": self.error}
            if self.result is None:
                return {"status": "measuring", "hours": self.hours}
            return {"status": "ready", "simulation": True, "hours": self.result["hours"],
                    "hours_with_false_alert": {str(k): v for k, v in
                                               self.result["hours_with_false_alert"].items()}}
