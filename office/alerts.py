"""Alert checking and push notifications to NanoClaw.

Called after every Dashboard.refresh() cycle. Checks the in-memory dashboard
data against alert thresholds and POSTs a notification to NanoClaw when
conditions are met. Alert state is persisted to alert_state.json so
restarts don't re-fire already-sent alerts.

Required environment variables:
  NANOCLAW_NOTIFY_URL     e.g. http://100.x.x.x:8151
  NANOCLAW_NOTIFY_SECRET  shared secret matching NanoClaw's NOTIFY_SECRET
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import Dashboard

STATE_FILE = Path(__file__).parent / "alert_state.json"
NOTIFY_URL = os.environ.get("NANOCLAW_NOTIFY_URL", "").rstrip("/") + "/notify"
NOTIFY_SECRET = os.environ.get("NANOCLAW_NOTIFY_SECRET", "")

IP_FAIL_THRESHOLD = 3       # consecutive failed polls before alerting
DEVICE_OFFLINE_MINUTES = 180  # 3 hours


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"ip_devices": {}, "devices": {}}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"[alerts] Failed to save state: {e}")


# ── Notification push ─────────────────────────────────────────────────────────

def _push(text: str) -> None:
    if not NOTIFY_URL or NOTIFY_URL == "/notify":
        print(f"[alerts] NANOCLAW_NOTIFY_URL not set, cannot push: {text}")
        return
    if not NOTIFY_SECRET:
        print(f"[alerts] NANOCLAW_NOTIFY_SECRET not set, cannot push: {text}")
        return
    body = json.dumps({"secret": NOTIFY_SECRET, "text": text}).encode()
    req = urllib.request.Request(
        NOTIFY_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[alerts] Pushed alert ({resp.status}): {text[:80]}")
    except Exception as e:
        print(f"[alerts] Failed to push alert: {e} — {text[:80]}")


# ── Alert logic ───────────────────────────────────────────────────────────────

def check_and_notify(dash: Dashboard) -> None:
    """Check dashboard data against alert thresholds and push if needed."""
    state = _load_state()
    changed = False

    # ── IP Devices ────────────────────────────────────────────────────────────
    ip_states: dict = state.setdefault("ip_devices", {})
    for dev in dash.ip_devices:
        s = ip_states.setdefault(dev.name, {"consecutive_failures": 0, "notified": False})

        if not dev.ok:
            s["consecutive_failures"] += 1
            changed = True
            if s["consecutive_failures"] >= IP_FAIL_THRESHOLD and not s["notified"]:
                s["notified"] = True
                detail = f" ({dev.detail})" if dev.detail else ""
                _push(
                    f"*Stats Alert* \u2014 IP device *{dev.name}* has failed "
                    f"{s['consecutive_failures']} polls in a row{detail}."
                )
        else:
            if s["consecutive_failures"] > 0 or s["notified"]:
                print(f"[alerts] IP device {dev.name!r} recovered, resetting alert state")
                changed = True
            s["consecutive_failures"] = 0
            s["notified"] = False

    # ── Camera Devices ────────────────────────────────────────────────────────
    dev_states: dict = state.setdefault("devices", {})
    for dev in dash.devices:
        s = dev_states.setdefault(dev.name, {"notified_offline": False})

        age = dev.age_minutes if dev.age_minutes is not None else 0
        is_offline = age > DEVICE_OFFLINE_MINUTES

        if is_offline and not s["notified_offline"]:
            s["notified_offline"] = True
            changed = True
            hours, mins = divmod(age, 60)
            last_seen = f" Last seen: {dev.last_seen.isoformat()}." if dev.last_seen else ""
            _push(
                f"*Stats Alert* \u2014 Camera *{dev.name}* has been offline "
                f"for {hours}h {mins}m.{last_seen}"
            )
        elif not is_offline and s["notified_offline"]:
            print(f"[alerts] Camera {dev.name!r} back online, resetting alert state")
            s["notified_offline"] = False
            changed = True

    if changed:
        _save_state(state)
