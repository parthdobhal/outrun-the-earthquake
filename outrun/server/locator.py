"""Find where and when the earthquake started, from report times and cells only.

Model the server assumes: a report at cell (x_i, y_i) detected at time t_i
satisfies, apart from noise,

    t_i = t0 + T_i(x, y),   T_i = sqrt((x - x_i)^2 + (y - y_i)^2 + h^2) / v_P

with unknowns x, y (epicentre) and t0 (origin time). Depth h is fixed at the
server's assumed value.

Three steps, each covering the others' weaknesses:
1. GRID SEARCH finds the right neighbourhood. At every grid point the best t0 is
   the median of (t_i - T_i); the cost is the sum of squared residuals, each
   capped so one bad report cannot dominate. A coarse grid, then a fine one.
2. LEAST SQUARES (Gauss-Newton) refines the best grid point to a precise answer.
3. OUTLIER REJECTION drops reports whose residual is far larger than the
   typical one (3 x a robust spread, at least 0.5 s), then refits; repeated.

Quality measures, used by the alert rule:
- rms_s: timing misfit of the trusted reports
- predicted_error_km: the radius of an approximately 95 % error circle: the
  least-squares (timing-noise) part along its longest axis, combined with a
  fixed model-error term for the server's simplifications
- gap_deg: largest angle around the estimate with no reports (large = one-sided)
- ambiguous: a clearly different location (> 20 km away) fits almost as well
"""

import math

import numpy as np

from outrun.server.messages import Estimate

CHI2_95_2D_SQRT = math.sqrt(5.991)  # 95 % radius factor for a 2-D normal error


def travel_times(gx, gy, x, y, depth_km, vp_km_s):
    """P travel times from grid points (shape G) to reports (shape n): G x n."""
    dx = gx[:, None] - x[None, :]
    dy = gy[:, None] - y[None, :]
    return np.sqrt(dx * dx + dy * dy + depth_km * depth_km) / vp_km_s


def grid_costs(gx, gy, x, y, t, cfg):
    """Robust cost and best origin time at every grid point."""
    residual = t[None, :] - travel_times(gx, gy, x, y, cfg.depth_km, cfg.vp_km_s)
    t0 = np.median(residual, axis=1)
    misfit = residual - t0[:, None]
    cost = np.minimum(misfit * misfit, cfg.residual_cap_s ** 2).sum(axis=1)
    return cost, t0


def make_grid(x0, x1, y0, y1, step):
    xs = np.arange(x0, x1 + step / 2, step)
    ys = np.arange(y0, y1 + step / 2, step)
    gx, gy = np.meshgrid(xs, ys)
    return gx.ravel(), gy.ravel()


def grid_search(x, y, t, cfg):
    """Returns (best_x, best_y, best_t0, ambiguous)."""
    m = cfg.search_margin_km
    gx, gy = make_grid(-m, cfg.region_width_km + m, -m, cfg.region_height_km + m,
                       cfg.coarse_step_km)
    cost, t0 = grid_costs(gx, gy, x, y, t, cfg)
    best = int(np.argmin(cost))

    far = np.hypot(gx - gx[best], gy - gy[best]) > cfg.ambiguity_separation_km
    ambiguous = bool(far.any() and cost[best] > 0
                     and cost[far].min() <= cfg.ambiguity_ratio * cost[best])

    h = cfg.fine_half_width_km
    fx, fy = make_grid(gx[best] - h, gx[best] + h, gy[best] - h, gy[best] + h, cfg.fine_step_km)
    fine_cost, fine_t0 = grid_costs(fx, fy, x, y, t, cfg)
    j = int(np.argmin(fine_cost))
    return float(fx[j]), float(fy[j]), float(fine_t0[j]), ambiguous


def residuals_and_jacobian(params, x, y, t, cfg):
    px, py, t0 = params
    dx, dy = px - x, py - y
    distance = np.sqrt(dx * dx + dy * dy + cfg.depth_km ** 2)
    residual = t - t0 - distance / cfg.vp_km_s
    jacobian = np.column_stack([-dx / (cfg.vp_km_s * distance),
                                -dy / (cfg.vp_km_s * distance),
                                -np.ones_like(t)])
    return residual, jacobian


def clamp_to_region(params, cfg):
    """Keep the epicentre inside the search region (the region plus its margin).
    Without this, reports from one small area (where distance is poorly
    constrained) could send the estimate thousands of km away."""
    m = cfg.search_margin_km
    params = np.array(params, dtype=float)
    params[0] = min(max(params[0], -m), cfg.region_width_km + m)
    params[1] = min(max(params[1], -m), cfg.region_height_km + m)
    return params


def gauss_newton(params, x, y, t, cfg, iterations=15):
    """Least-squares refinement of (x, y, t0); halves the step if the fit worsens.
    The epicentre is kept inside the search region."""
    params = clamp_to_region(params, cfg)
    residual, jacobian = residuals_and_jacobian(params, x, y, t, cfg)
    cost = float(residual @ residual)
    for _ in range(iterations):
        step, *_ = np.linalg.lstsq(jacobian, -residual, rcond=None)
        for _ in range(10):
            trial = clamp_to_region(params + step, cfg)
            r_trial, j_trial = residuals_and_jacobian(trial, x, y, t, cfg)
            c_trial = float(r_trial @ r_trial)
            if c_trial <= cost:
                break
            step = step / 2
        else:
            break  # no improvement possible
        params, residual, jacobian, cost = trial, r_trial, j_trial, c_trial
        if math.hypot(step[0], step[1]) < 0.01:  # moved less than 10 m
            break
    return params, residual, jacobian


def azimuthal_gap_deg(px, py, x, y):
    """Largest angle (degrees) around (px, py) containing no report cells."""
    angles = np.unique(np.round(np.degrees(np.arctan2(y - py, x - px)) % 360.0, 6))
    if len(angles) < 2:
        return 360.0
    gaps = np.diff(np.concatenate([angles, [angles[0] + 360.0]]))
    return float(gaps.max())


def locate(ids, x, y, t, cfg, candidate_count=None):
    """Estimate (x, y, t0) from report ids, cells and detection times (numpy arrays)."""
    n = len(t)
    candidate_count = n if candidate_count is None else candidate_count
    if n < 4:
        raise ValueError("at least 4 reports are needed (3 unknowns plus one check)")

    gx, gy, gt0, ambiguous = grid_search(x, y, t, cfg)
    params = (gx, gy, gt0)

    # Start least squares ONLY with reports that already fit the grid answer.
    # Ordinary least squares is pulled strongly by outliers; starting with all
    # reports let a few false reports drag the fit tens of km away.
    residual_grid, _ = residuals_and_jacobian(params, x, y, t, cfg)
    centred = residual_grid - np.median(residual_grid)
    spread = 1.4826 * float(np.median(np.abs(centred)))
    inliers = np.abs(centred) <= max(cfg.outlier_sigmas * spread, cfg.outlier_floor_s)
    if inliers.sum() < 4:
        inliers = np.ones(n, dtype=bool)

    for _ in range(6):
        params, _, _ = gauss_newton(params, x[inliers], y[inliers], t[inliers], cfg)
        residual_all, _ = residuals_and_jacobian(params, x, y, t, cfg)
        r_in = residual_all[inliers]
        spread = 1.4826 * float(np.median(np.abs(r_in - np.median(r_in))))
        threshold = max(cfg.outlier_sigmas * spread, cfg.outlier_floor_s)
        new_inliers = np.abs(residual_all) <= threshold
        if new_inliers.sum() < 4 or np.array_equal(new_inliers, inliers):
            break
        inliers = new_inliers

    if inliers.sum() >= 4:
        params, r_in, jacobian = gauss_newton(params, x[inliers], y[inliers], t[inliers], cfg)
    else:
        r_in, jacobian = residuals_and_jacobian(params, x[inliers], y[inliers], t[inliers], cfg)

    k = int(inliers.sum())
    rms = float(np.sqrt(np.mean(r_in ** 2))) if k else math.inf
    sigma = max(rms, cfg.timing_noise_floor_s)
    try:
        covariance = sigma ** 2 * np.linalg.inv(jacobian.T @ jacobian)
        largest = float(np.linalg.eigvalsh(covariance[:2, :2]).max())
        statistical = CHI2_95_2D_SQRT * math.sqrt(max(largest, 0.0))
        # Add the model error (fixed depth, approximate speeds), which timing
        # noise alone does not capture.
        predicted_error = math.hypot(statistical, cfg.model_error_km)
    except np.linalg.LinAlgError:
        predicted_error = math.inf
    if not math.isfinite(predicted_error):
        predicted_error = math.inf

    px, py, t0 = (float(v) for v in params)
    return Estimate(
        x_km=px, y_km=py, origin_time_s=t0,
        inlier_ids=tuple(int(i) for i in np.asarray(ids)[inliers]),
        candidate_count=candidate_count,
        rms_s=rms, predicted_error_km=predicted_error,
        gap_deg=azimuthal_gap_deg(px, py, x[inliers], y[inliers]),
        ambiguous=ambiguous,
        valid=k >= max(4, n // 2),
    )
