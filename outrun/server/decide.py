"""The warning server's main loop and its alert rule.

The server processes reports one at a time, in the order they ARRIVE. After each
one it:
  1. keeps only recent reports (the last window_s seconds, at most
     max_window_reports of them),
  2. runs the causality pre-filter,
  3. runs the locator if there are enough candidates,
  4. checks the ALERT RULE. The first time it holds, an alert is issued.

ALERT RULE (K is the number the judge controls with the slider). By default an
alert is issued on the first locator update that passes it; AlertConfirmer can
optionally require several consecutive, agreeing updates (confirmations_required):
    at least K trusted (inlier) reports
    AND timing misfit (rms) <= rms_max_s
    AND predicted location error <= predicted_error_max_km
    AND the location is not ambiguous
    AND the reports surround the estimate well enough (gap <= gap_max_deg)
    AND the phones nearest the estimate are not silent (see silence.py)
    AND enough reports came from near the estimate (min_nearby_reports, or 30 % of
        the active phones there if fewer, and at least 1; see silence.py)
    AND most candidates were trusted (valid)

After the alert, up to post_alert_reports more reports keep refining the
displayed estimate, but the alert time never changes.

To keep the work bounded, the locator is re-run only when the number of
candidates has changed enough (every change while there are few, then each 10 %
growth, and whenever it shrinks), and at most max_reports_used reports are used.
"""

import dataclasses

import numpy as np

from outrun.server.config import ServerConfig
from outrun.server.locator import locate
from outrun.server.messages import Alert, ReportMessage, ServerRun, Snapshot
from outrun.server.prefilter import select_candidates
from outrun.server.silence import (CellCounts, active_phones_near, nearby_report_count,
                                   nearby_reports_required, silence_check)


class AlertConfirmer:
    """Optionally requires the alert rule to hold on several consecutive locator
    updates that agree with each other, each using more trusted reports.

    confirmations_required = 1 (the default) alerts on the first passing update.
    Larger values trade warning time for extra caution.
    """

    def __init__(self, k, cfg):
        self.k, self.cfg, self.previous, self.streak = k, cfg, None, 0

    def update(self, estimate) -> bool:
        """Feed each NEW estimate; returns True when the alert is confirmed."""
        if not alert_rule(estimate, self.k, self.cfg):
            self.previous, self.streak = None, 0
            return False
        previous, self.previous = self.previous, estimate
        if previous is None:
            self.streak = 1
        else:
            moved = ((estimate.x_km - previous.x_km) ** 2
                     + (estimate.y_km - previous.y_km) ** 2) ** 0.5
            agree = moved <= max(previous.predicted_error_km, estimate.predicted_error_km,
                                 self.cfg.confirm_min_distance_km)
            grew = estimate.inlier_count > previous.inlier_count
            self.streak = self.streak + 1 if (agree and grew) else 1
        return self.streak >= self.cfg.confirmations_required


def alert_rule(estimate, k, cfg: ServerConfig) -> bool:
    return (estimate is not None and estimate.valid and not estimate.ambiguous
            and estimate.inlier_count >= k
            and estimate.rms_s <= cfg.rms_max_s
            and estimate.predicted_error_km <= cfg.predicted_error_max_km
            and estimate.gap_deg <= cfg.gap_max_deg
            and estimate.silence_ok
            and estimate.nearby_reports >= max(estimate.nearby_required, 1))


def run_server(reports, k: int | None = None, cfg: ServerConfig | None = None,
               keep_snapshots: bool = True, stop_after_alert: bool = True,
               cell_counts=None) -> ServerRun:
    """Process reports (ReportMessage objects or plain dicts) as they arrive.

    cell_counts: active phones per cell (plain dicts with cell_x_km, cell_y_km,
    phones). Without it the silent-phones check is skipped.

    stop_after_alert=False processes every report (used to measure false alarms
    over long periods; the sequence of estimates does not depend on K)."""
    cfg = ServerConfig() if cfg is None else cfg
    k = cfg.k_default if k is None else k
    if isinstance(k, bool) or not isinstance(k, int) or not cfg.k_min <= k <= cfg.k_max:
        raise ValueError(f"K must be an integer from {cfg.k_min} to {cfg.k_max}")

    messages = [r if isinstance(r, ReportMessage) else ReportMessage.from_dict(r)
                for r in reports]
    messages.sort(key=lambda m: (m.t_received_s, m.report_id))

    window = []
    snapshots = []
    confirmer = AlertConfirmer(k, cfg)
    cells = CellCounts(cell_counts) if cell_counts is not None else None
    alert = None
    alert_index = 0
    estimate = None
    last_located_count = 0
    processed = 0

    for message in messages:
        processed += 1
        now = message.t_received_s
        window.append(message)
        window = [m for m in window if m.t_received_s >= now - cfg.window_s]
        window = window[-cfg.max_window_reports:]

        x = np.array([m.cell_x_km for m in window])
        y = np.array([m.cell_y_km for m in window])
        t = np.array([m.t_detect_s for m in window])
        ids = np.array([m.report_id for m in window])

        candidates = select_candidates(x, y, t, cfg.vp_km_s, cfg.causality_slack_s)
        count = len(candidates)
        # Re-locate when the candidate set changed enough: every change while it
        # is small, every 10 % growth when large, and whenever it shrank (old
        # reports left the time window).
        grew_enough = count != last_located_count and (
            count <= 40 or count >= 1.1 * last_located_count or count < last_located_count)
        if count >= 4 and grew_enough:
            use = candidates[np.argsort(t[candidates], kind="stable")][:cfg.max_reports_used]
            estimate = locate(ids[use], x[use], y[use], t[use], cfg, candidate_count=count)
            expected, actual, ok = silence_check(estimate, now, cells, window, cfg)
            required = nearby_reports_required(active_phones_near(estimate, cells, cfg), cfg,
                                               have_counts=cells is not None)
            estimate = dataclasses.replace(estimate, expected_reporters=expected,
                                           actual_reporters=actual, silence_ok=ok,
                                           nearby_reports=nearby_report_count(estimate, window, cfg),
                                           nearby_required=required)
            last_located_count = count
            confirmed = confirmer.update(estimate)
            if alert is None and confirmed:
                issued = now + cfg.processing_s
                alert = Alert(message.report_id, issued, issued + cfg.delivery_s, estimate)
                alert_index = processed

        if keep_snapshots:
            snapshots.append(Snapshot(now, processed, estimate))

        if stop_after_alert and alert is not None and (processed - alert_index >= cfg.post_alert_reports
                                  or estimate.inlier_count >= cfg.max_reports_used):
            break  # enough refinement; further reports cannot change the alert

    return ServerRun(k_required=k, alert=alert, snapshots=tuple(snapshots),
                     final_estimate=estimate, reports_processed=processed)


def first_alert_snapshot(snapshots, k: int, cfg: ServerConfig | None = None):
    """The first snapshot at which the alert rule holds for this K (or None).

    Because the server's estimates do not depend on K, one run with
    keep_snapshots=True gives the alert time for every K."""
    cfg = ServerConfig() if cfg is None else cfg
    confirmer = AlertConfirmer(k, cfg)
    last = None
    for snapshot in snapshots:
        if snapshot.estimate is None or snapshot.estimate is last:
            continue  # only NEW estimates count, as in run_server
        last = snapshot.estimate
        if confirmer.update(snapshot.estimate):
            return snapshot
    return None
