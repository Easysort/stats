"""Lightweight JSON API that exposes dashboard data over HTTP."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import Dashboard

API_PORT = int(__import__("os").environ.get("STATS_API_PORT", "8150"))


def _dt(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def _serialize_dashboard(dash: Dashboard) -> dict:
    devices = [
        {
            "name": d.name,
            "ok": d.ok,
            "age_minutes": d.age_minutes,
            "last_seen": _dt(d.last_seen),
            "last_path": d.last_path,
            "error": d.error,
        }
        for d in dash.devices
    ]

    ip_devices = [
        {
            "name": d.name,
            "ok": d.ok,
            "detail": d.detail,
            "over_temp": d.over_temp,
            "tmux_running": d.tmux_running,
            "temp_history": (
                [
                    {"timestamp": _dt(ts), "temp_c": temp, "tmux_running": tmux}
                    for ts, temp, tmux in d.temp_history
                ]
                if d.temp_history
                else []
            ),
        }
        for d in dash.ip_devices
    ]

    runners = [
        {
            "name": r.name,
            "ok": r.ok,
            "warn": r.warn,
            "detail": r.detail,
            "path": r.path,
            "pending": r.pending,
        }
        for r in dash.runners
    ]

    tracking = [
        {
            "name": t.name,
            "ok": t.ok,
            "warn": t.warn,
            "detail": t.detail,
            "path": t.path,
            "pending": t.pending,
        }
        for t in dash.tracking
    ]

    def _storage(sh) -> dict | None:
        if sh is None:
            return None
        return {
            "name": sh.name,
            "current": {
                "used_gb": round(sh.current.used_gb, 2),
                "total_gb": round(sh.current.total_gb, 2),
                "free_gb": round(sh.current.free_gb, 2),
                "percent_used": round(sh.current.percent_used, 1),
            },
            "history": [
                {
                    "timestamp": _dt(p.timestamp),
                    "used_gb": round(p.used_gb, 2),
                    "total_gb": round(p.total_gb, 2),
                }
                for p in sh.history
            ],
        }

    return {
        "timestamp": datetime.now().isoformat(),
        "devices": devices,
        "ip_devices": ip_devices,
        "runners": runners,
        "tracking": tracking,
        "storage": {
            "local": _storage(dash.mkv_storage),
            "cloud": _storage(dash.supabase_storage),
        },
    }


class _Handler(BaseHTTPRequestHandler):
    dashboard: Dashboard

    def do_GET(self):
        if self.path == "/api/status" or self.path == "/api/status/":
            body = json.dumps(
                _serialize_dashboard(self.dashboard), indent=2
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.write(body)
            return

        # Sub-sections
        section = self.path.strip("/").removeprefix("api/").removeprefix("status/")
        full = _serialize_dashboard(self.dashboard)
        if section in full:
            body = json.dumps(full[section], indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.write(body)
            return

        self.send_error(404, "Not found. Try /api/status")

    def write(self, data: bytes):
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def log_message(self, fmt, *args):
        pass  # silence request logging


def start_api(dash: Dashboard, port: int = API_PORT) -> HTTPServer:
    _Handler.dashboard = dash
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[api] JSON API running on http://0.0.0.0:{port}/api/status")
    return server
