"""Causality pre-filter: drop reports that cannot belong to the same earthquake.

Idea: a seismic wave cannot travel faster than the P-wave. So if two reports came
from the same earthquake, the gap between their detection times can be no larger
than (distance between them) / v_P, plus a small allowance (slack) for clock
errors, coarse 2 km cells and detection delays.

    compatible(i, j)  <=>  |t_i - t_j| <= d_ij / v_P + slack

The report compatible with the most others is taken as the "seed"; the seed and
everything compatible with it become the candidates passed to the locator.
This is only a cheap first pass: reports far apart are allowed large time gaps
(a P-wave needs about 17 s to cross 100 km), so many random false reports still
pass it. The locator's outlier rejection removes those.
"""

import numpy as np


def compatibility_matrix(x, y, t, vp_km_s, slack_s):
    """Boolean n x n matrix: True where two reports could share one source."""
    dx = x[:, None] - x[None, :]
    dy = y[:, None] - y[None, :]
    distance = np.hypot(dx, dy)
    return np.abs(t[:, None] - t[None, :]) <= distance / vp_km_s + slack_s


def select_candidates(x, y, t, vp_km_s, slack_s):
    """Indices (into x, y, t) of the seed and the reports compatible with it."""
    n = len(t)
    if n == 0:
        return np.array([], dtype=int)
    compatible = compatibility_matrix(x, y, t, vp_km_s, slack_s)
    counts = compatible.sum(axis=1)
    # Ties go to the earliest detection (lowest t), so the choice is deterministic.
    order = np.lexsort((t, -counts))
    seed = order[0]
    return np.flatnonzero(compatible[seed])
