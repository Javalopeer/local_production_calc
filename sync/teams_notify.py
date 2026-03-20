# -*- coding: utf-8 -*-
"""
Teams Webhook Notifications for Downtime Approvals.

Sends an Adaptive Card to a Teams channel when a designer submits
a downtime for approval.  Each team configures its own webhook URL.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime

from sync.app_config import load_config


def _get_webhook_url() -> str | None:
    """Return the configured Teams webhook URL, or None."""
    cfg = load_config()
    url = cfg.get("teams_webhook", "").strip()
    if not url:
        return None
    # Basic validation — must be an HTTPS webhook URL
    if not url.startswith("https://"):
        print("[teams_notify] Invalid webhook URL (must start with https://)")
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
) -> bool:
    """Send a message to Teams Workflow webhook when a downtime is submitted.
    Returns True on success, False on failure.
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        return False
    submitted_at = datetime.now().strftime("%I:%M %p")
    # Workflows expect a simple JSON payload, not Adaptive Card
    payload = {
        "designer": designer,
        "fecha": fecha,
        "hora_inicio": start,
        "hora_fin": end,
        "duracion": duration,
        "razon": reason,
        "detalle": detalle,
        "enviado": submitted_at,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            if status in (200, 202):
                print(f"[teams_notify] Workflow notification sent ({status}).")
                return True
            else:
                print(f"[teams_notify] Unexpected status: {status}")
                return False
    except urllib.error.HTTPError as e:
        print(f"[teams_notify] HTTP error {e.code}: {e.reason}")
        return False
    except Exception as exc:
        print(f"[teams_notify] Failed to send: {exc}")
        return False
