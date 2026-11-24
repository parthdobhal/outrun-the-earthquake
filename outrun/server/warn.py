"""Predicted warning time, computed by the server from its ESTIMATE only.

For a place at horizontal distance d from the estimated epicentre:

    predicted S arrival  = t0_est + sqrt(d^2 + h^2) / v_S
    predicted warning    = predicted S arrival - time the alert is delivered

A warning <= 0 means the strong shaking arrives before (or as) the alert does:
that place is in the no-warning zone ("blind zone"). Its predicted radius is the
horizontal distance at which the S-wave arrives exactly when the alert does.
"""

import math

from outrun.server.config import ServerConfig


def predicted_warning_s(estimate, x_km, y_km, t_delivered_s, cfg: ServerConfig) -> float:
    d = math.hypot(x_km - estimate.x_km, y_km - estimate.y_km)
    s_arrival = estimate.origin_time_s + math.sqrt(d * d + cfg.depth_km ** 2) / cfg.vs_km_s
    return s_arrival - t_delivered_s


def predicted_blind_radius_km(estimate, t_delivered_s, cfg: ServerConfig) -> float:
    reach = cfg.vs_km_s * (t_delivered_s - estimate.origin_time_s)  # S distance travelled
    return math.sqrt(max(reach * reach - cfg.depth_km ** 2, 0.0))
