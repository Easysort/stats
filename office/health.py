"""Device and runner health checks."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import re

SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png"}
TS_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})/(\d{2})/(\d{2})(\d{2})(\d{2})")

@dataclass
class DeviceStatus:
    name: str
    ok: bool
    age_minutes: int | None = None
    last_seen: datetime | None = None
    error: str | None = None

@dataclass
class RunnerStatus:
    name: str
    ok: bool
    jobs_pending: int = 0
    jobs_completed: int = 0
    last_run: datetime | None = None

def _parse_path_ts(path: Path) -> datetime | None:
    """Extract timestamp from path like argo/Device/2025/01/30/12/123456.mp4"""
    if m := TS_RE.search(str(path)):
        y, mo, d, h, mi, s = int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6])
        return datetime(y, mo, d, h, mi, s)
    return None

def get_device_health(registry_backend, max_age_minutes: int = 60) -> list[DeviceStatus]:
    """Get health status for all Argo devices using Registry backend."""
    try:
        files = registry_backend.LIST("argo/")
    except Exception as e:
        return [DeviceStatus("registry", False, error=str(e))]
    
    # Group files by device and find latest timestamp per device
    device_latest: dict[str, datetime] = defaultdict(lambda: datetime.min)
    
    for f in files:
        parts = f.parts
        if len(parts) < 2 or f.suffix.lower() not in SUFFIXES:
            continue
        device = parts[1]  # argo/<device>/...
        if device == "results":
            continue
        if ts := _parse_path_ts(f):
            if ts > device_latest[device]:
                device_latest[device] = ts
    
    now, results = datetime.now(), []
    for device in sorted(device_latest.keys(), key=str.lower):
        ts = device_latest[device]
        if ts == datetime.min:
            results.append(DeviceStatus(device, False, error="no media"))
        else:
            age = int((now - ts).total_seconds() // 60)
            results.append(DeviceStatus(device, age <= max_age_minutes, age, ts))
    
    return results

def get_runner_health() -> list[RunnerStatus]:
    """Get health status for runners (placeholder - returns mock data)."""
    # TODO: Implement actual runner health checks
    return [
        RunnerStatus("argo-processor", True, 3, 127, datetime.now()),
        RunnerStatus("verdis-uploader", True, 0, 45, datetime.now()),
        RunnerStatus("model-inference", False, 12, 89, datetime(2025, 1, 29, 14, 30)),
    ]
