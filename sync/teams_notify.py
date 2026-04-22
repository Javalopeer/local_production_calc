# -*- coding: utf-8 -*-
"""
Teams Webhook Notifications for Downtime Approvals.

Sends structured JSON to a Power Automate workflow which posts an
Adaptive Card with Approve/Reject buttons.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime

from sync.app_config import get_teams_webhook_url
from sync.app_logger import log_event

_WEBHOOK_TIMEOUT_S = 10  # seconds to wait for Power Automate response


def _get_webhook_url() -> str | None:
    """Return the configured Teams webhook URL, or None."""
    url = get_teams_webhook_url().strip()
    if not url:
        return None
    if not url.startswith("https://"):
        log_event("teams_notify", "invalid webhook URL (must start with https://)", level="WARN")
        return None
    return url


def notify_downtime_submitted(
    designer: str,
    fecha: str,
    start: str,
    end: str,
    duration: int,
    reason: str,
    detalle: str = "",
    dt_id: int = 0,
) -> bool:
    """Send downtime data to Power Automate workflow.

    Sends simple flat JSON fields so Power Automate can easily
    reference them as triggerBody()?['designer'], etc.

    Returns True on success, False on failure.
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        return False

    detail_line = f" — {detalle}" if detalle else ""

    # Simple flat JSON — easy to use in Power Automate expressions
    payload = {
        "designer": designer or "Unknown",
        "fecha": fecha,
        "start": start,
        "end": end,
        "duration": duration,
        "reason": reason,
        "detalle": detalle,
        "dt_id": dt_id,
        "summary": f"⏱ {designer or 'Unknown'} — {reason}{detail_line}",
        "time_range": f"{fecha}  ·  {start}–{end} ({duration} min)",
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as resp:
            status = resp.status
            if status in (200, 202):
                log_event("teams_notify", f"notification sent status={status} dt_id={dt_id}")
                return True
            else:
                log_event("teams_notify", f"unexpected status={status} dt_id={dt_id}", level="WARN")
                return False
    except urllib.error.HTTPError as e:
        log_event("teams_notify", f"http error code={e.code} reason={e.reason} dt_id={dt_id}", level="WARN")
        return False
    except Exception as exc:
        log_event("teams_notify", f"send failed dt_id={dt_id}: {exc}", level="WARN")
        return False
