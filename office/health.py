"""Device and runner health checks."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import json
import re
import urllib.request
import urllib.error
from tqdm import tqdm

from supabase import create_client
from easysort.helpers import SUPABASE_KEY, SUPABASE_URL

SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png"}
TS_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})/(\d{2})/(\d{2})(\d{2})(\d{2})")
VERDIS_TS_RE = re.compile(r"(\d{8})_(\d{6})")  # YYYYMMDD_HHMMSS folder format
IP_DEVICE_HEALTH_TIMEOUT = 15
IP_DEVICE_TEMP_LIMIT_CELSIUS = 85

@dataclass
class DeviceStatus:
    name: str
    ok: bool
    age_minutes: int | None = None
    last_seen: datetime | None = None
    last_path: str | None = None
    error: str | None = None

IP_DEVICE_TEMP_HISTORY_MAX = 1000

@dataclass
class IPDeviceStatus:
    name: str
    ok: bool
    detail: str
    over_temp: bool = False  # True => show very red (temp > 85°C)
    tmux_running: bool = False
    temp_history: list[tuple[datetime, float | None, bool]] | None = None  # (ts, temp_c, tmux_running), last 100

@dataclass
class RunnerStatus:
    name: str
    ok: bool  # True=green, False=red
    warn: bool = False  # True=yellow (not implemented or outside hours)
    detail: str = ""
    path: str | None = None
    pending: int = 0

def _parse_path_ts(path: Path) -> datetime | None:
    """Extract timestamp from path like argo/Device/2025/01/30/12/123456.mp4"""
    if m := TS_RE.search(str(path)):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        h, mi, s = int(m[5]), int(m[6]), int(m[7])
        return datetime(y, mo, d, h, mi, s)
    return None

def _parse_verdis_folder_ts(folder_name: str) -> datetime | None:
    """Extract timestamp from folder name like 20260128_103000."""
    if m := VERDIS_TS_RE.match(folder_name):
        d, t = m[1], m[2]
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), int(t[:2]), int(t[2:4]), int(t[4:6]))
    return None

def _is_verdis_active_hours() -> bool:
    """Check if we're in verdis active hours (weekdays 7-19)."""
    now = datetime.now()
    return now.weekday() < 5 and 7 <= now.hour < 19

def get_device_health(registry_backend, max_age_minutes: int = 60) -> list[DeviceStatus]:
    """Get health status for all Argo devices using Registry backend."""
    print("[device-health] Listing argo files...")
    try:
        files = list(tqdm(registry_backend.LIST("argo/"), desc="Listing argo files"))
    except Exception as e:
        return [DeviceStatus("registry", False, error=str(e))]
    
    device_latest: dict[str, tuple[datetime, str]] = defaultdict(lambda: (datetime.min, ""))
    
    for f in tqdm(files, desc="Scanning devices"):
        parts = f.parts
        if len(parts) < 2 or f.suffix.lower() not in SUFFIXES:
            continue
        device = parts[1]
        if device == "results":
            continue
        if ts := _parse_path_ts(f):
            if ts > device_latest[device][0]:
                device_latest[device] = (ts, str(f))
    
    now, results = datetime.now(), []
    for device in sorted(device_latest.keys(), key=str.lower):
        ts, path = device_latest[device]
        if ts == datetime.min:
            results.append(DeviceStatus(device, False, error="no media"))
        else:
            age = int((now - ts).total_seconds() // 60)
            results.append(DeviceStatus(device, age <= max_age_minutes, age, ts, path))
    
    print(f"[device-health] Found {len(results)} devices")
    return results


def _load_ip_device_temp_history(history_path: Path) -> dict[str, list[dict]]:
    """Load per-device temp history from JSON. Keys: ts (ISO), temp_c (float or null), tmux_running (bool)."""
    if not history_path.exists():
        return {}
    try:
        raw = json.loads(history_path.read_text())
        return {k: v if isinstance(v, list) else [] for k, v in raw.items()}
    except Exception:
        return {}


def _save_ip_device_temp_history(history_path: Path, all_history: dict[str, list[dict]]) -> None:
    """Save per-device temp history to JSON."""
    out = {}
    for name, entries in all_history.items():
        out[name] = [
            {"ts": e["ts"].isoformat() if hasattr(e["ts"], "isoformat") else e["ts"], "temp_c": e["temp_c"], "tmux_running": e["tmux_running"]}
            for e in entries
        ]
    history_path.write_text(json.dumps(out, indent=0))


def _history_to_tuples(entries: list[dict]) -> list[tuple[datetime, float | None, bool]]:
    """Convert JSON entries to (datetime, temp_c|None, tmux_running) with last-known temp carried forward."""
    result: list[tuple[datetime, float | None, bool]] = []
    last_temp: float | None = None
    for e in entries:
        ts = e.get("ts")
        if hasattr(ts, "isoformat"):
            dt = ts
        elif isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            continue
        temp = e.get("temp_c")
        if temp is not None:
            try:
                last_temp = float(temp)
            except (TypeError, ValueError):
                pass
        tmux = bool(e.get("tmux_running", False))
        result.append((dt, last_temp, tmux))
    return result


def get_ip_device_health(devices_txt_path: Path) -> list[IPDeviceStatus]:
    """Read devices.txt (lines: 'name ip'), call http://{ip}:5000/health, return status. Temp > 85°C => over_temp.
    Persists last 100 (ts, temp_c, tmux_running) per device for the temp-over-time chart."""
    results: list[IPDeviceStatus] = []
    if not devices_txt_path.exists():
        return results
    history_path = devices_txt_path.parent / "ip_device_temp_history.json"
    all_history = _load_ip_device_temp_history(history_path)
    lines = devices_txt_path.read_text().strip().splitlines()
    now = datetime.now()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        name, ip = parts[0], parts[1].strip()
        url = f"http://{ip}:5000/health"
        data = None
        temp_val: float | None = None
        tmux_running = False
        over_temp = False
        detail = ""
        ok = False
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; Easysort-Stats/1.0)"}
            )
            try:
                with urllib.request.urlopen(req, timeout=IP_DEVICE_HEALTH_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 503 and e.fp:
                    try:
                        data = json.loads(e.read().decode())
                    except Exception:
                        data = None
                if data is None:
                    detail = f"HTTP {e.code}"
                    results.append(_ip_device_result(name, ok, detail, over_temp, tmux_running, all_history, now))
                    continue
            if data is None:
                results.append(_ip_device_result(name, ok, detail or "no data", over_temp, tmux_running, all_history, now))
                continue
            temps = data.get("temps") if isinstance(data.get("temps"), dict) else {}
            checks = data.get("checks") or {}
            if "temps" in data or "checks" in data:
                temp_val = (temps.get("cpu_c") if temps.get("cpu_c") is not None else temps.get("battery_c"))
                if temp_val is None and isinstance(data.get("battery"), dict):
                    bat = data.get("battery") or {}
                    temp_val = bat.get("temp_c") or bat.get("temperature")
                if temp_val is None:
                    temp_val = data.get("battery_c") or data.get("temperature_celsius")
                if temp_val is not None:
                    temp_val = float(temp_val)
                over_temp = temp_val is not None and temp_val > IP_DEVICE_TEMP_LIMIT_CELSIUS
                temps_ok = checks.get("temps_ok", True)
                if "tmux_running" in checks:
                    tmux_running = bool(checks["tmux_running"])
                else:
                    tmux_running = bool(data.get("healthy", False))
                if temp_val is not None:
                    temp_src = "batt" if temps.get("cpu_c") is None else ""
                    temp_str = f"{temp_val:.1f}°C" + (f" {temp_src}" if temp_src else "")
                else:
                    temp_str = "no temp"
                tmux_str = "tmux ok" if tmux_running else "tmux no"
                detail = f"{temp_str} · {tmux_str}"
                ok = not over_temp and temps_ok and tmux_running
            else:
                camera = data.get("camera", "")
                status = data.get("status", "")
                temp = data.get("temperature_celsius")
                if temp is None:
                    detail = "no temp"
                else:
                    temp_val = float(temp)
                    detail = f"{temp_val:.1f}°C"
                    over_temp = temp_val > IP_DEVICE_TEMP_LIMIT_CELSIUS
                    ok = (camera == "ok" and status == "ok" and not over_temp)
            results.append(_ip_device_result(name, ok, detail, over_temp, tmux_running, all_history, now, temp_val))
        except Exception as e:
            detail = str(e)[:40]
            results.append(_ip_device_result(name, False, detail, False, False, all_history, now))
    _save_ip_device_temp_history(history_path, all_history)
    return results


def _ip_device_result(
    name: str,
    ok: bool,
    detail: str,
    over_temp: bool,
    tmux_running: bool,
    all_history: dict[str, list[dict]],
    now: datetime,
    temp_val: float | None = None,
) -> IPDeviceStatus:
    """Append one sample to device history, trim to max, return IPDeviceStatus with temp_history."""
    entries = all_history.setdefault(name, [])
    entries.append({"ts": now, "temp_c": temp_val, "tmux_running": tmux_running})
    if len(entries) > IP_DEVICE_TEMP_HISTORY_MAX:
        entries[:] = entries[-IP_DEVICE_TEMP_HISTORY_MAX:]
    tuples = _history_to_tuples(entries)
    return IPDeviceStatus(name=name, ok=ok, detail=detail, over_temp=over_temp, tmux_running=tmux_running, temp_history=tuples)


def get_runner_health(registry_backend=None) -> list[RunnerStatus]:
    """Get health status for runners."""
    results = []

    # Verdis uploader - checks both cameras, red if either is stale
    results.append(_check_verdis_uploader(registry_backend))

    # Verdis inference - check results for each camera
    results.append(_check_verdis_inference(registry_backend, "verdis/gadstrup/5", "verdis-belt-inference"))
    results.append(_check_verdis_inference(registry_backend, "verdis/gadstrup/4", "verdis-bales-inference",
                                           cutoff_start=datetime(2026, 2, 16)))

    return results

def get_tracking_health(heavy: bool = False) -> list[RunnerStatus]:
    """Get health status for tracking services. Checks on every sync."""
    return _check_argo_weeks()

def _check_argo_weeks() -> list[RunnerStatus]:
    """Check argo week/month results in Supabase - returns status for last week and last month."""
    results = []
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        return [RunnerStatus("argo-tracking", ok=False, detail="no supabase config")]
    
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        bucket = client.storage.from_("easytrack")
        files = bucket.list("argo/tent")
        file_names = {f["name"] for f in files}
    except Exception as e:
        return [RunnerStatus("argo-tracking", ok=False, detail=str(e)[:30])]
    
    now = datetime.now()
    year, current_week, _ = now.isocalendar()
    
    # Check last 4 weeks
    week_status = []
    for i in range(1, 5):  # weeks 1-4 ago
        w = current_week - i
        y = year
        if w < 1:
            w += 52
            y -= 1
        week_file = f"week_{w}_{y}.json"
        has_week = week_file in file_names
        week_status.append((w, y, has_week))
    
    # Build week detail text
    week_parts = []
    missing_weeks = []
    for w, y, has in week_status:
        if has:
            week_parts.append(f"w{w}+")
        else:
            week_parts.append(f"w{w}-")
            missing_weeks.append(w)
    
    week_detail = " ".join(week_parts)
    week_ok = len(missing_weeks) == 0
    week_warn = len(missing_weeks) == 1 and missing_weeks[0] == week_status[0][0]  # Only last week missing is warn
    
    results.append(RunnerStatus(
        "argo-weeks", 
        ok=week_ok or week_warn,
        warn=week_warn,
        detail=week_detail
    ))
    
    # Check last 2 months
    month_status = []
    for i in range(1, 3):  # months 1-2 ago
        m = now.month - i
        y = year
        if m < 1:
            m += 12
            y -= 1
        month_file = f"month_{m}_{y}.json"
        has_month = month_file in file_names
        month_status.append((m, y, has_month))
    
    # Build month detail text
    month_parts = []
    missing_months = []
    for m, y, has in month_status:
        month_name = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m-1]
        if has:
            month_parts.append(f"{month_name}+")
        else:
            month_parts.append(f"{month_name}-")
            missing_months.append(m)
    
    month_detail = " ".join(month_parts)
    month_ok = len(missing_months) == 0
    month_warn = len(missing_months) == 1 and missing_months[0] == month_status[0][0]  # Only last month missing is warn
    
    results.append(RunnerStatus(
        "argo-months",
        ok=month_ok or month_warn,
        warn=month_warn,
        detail=month_detail
    ))
    
    return results

UPLOADER_PREFIXES = ["verdis/gadstrup/5", "verdis/gadstrup/4"]

def _check_verdis_uploader(registry_backend) -> RunnerStatus:
    """Check verdis uploader health - both cameras should have folders < 10 min old during active hours."""
    if registry_backend is None:
        return RunnerStatus("verdis-uploader", ok=False, detail="no backend")

    cam_ages: dict[str, tuple[int, str]] = {}  # prefix -> (age_min, latest_path)
    for prefix in UPLOADER_PREFIXES:
        cam_label = prefix.rsplit("/", 1)[-1]
        print(f"[verdis-uploader] Listing {prefix}...")
        try:
            files = list(tqdm(registry_backend.LIST(f"{prefix}/"), desc=f"Listing {prefix}"))
        except Exception as e:
            cam_ages[cam_label] = (-1, str(e)[:20])
            continue

        folder_ts: dict[str, datetime] = {}
        for f in files:
            parts = f.parts
            if len(parts) >= 4:
                folder_name = parts[3]
                if folder_name not in folder_ts:
                    if ts := _parse_verdis_folder_ts(folder_name):
                        folder_ts[folder_name] = ts

        if not folder_ts:
            cam_ages[cam_label] = (-1, "no folders")
            continue

        latest_folder = max(folder_ts.keys(), key=lambda k: folder_ts[k])
        latest_ts = folder_ts[latest_folder]
        age_min = int((datetime.now() - latest_ts).total_seconds() // 60)
        cam_ages[cam_label] = (age_min, f"{prefix}/{latest_folder}")

    detail_parts = []
    worst_age = 0
    worst_path = None
    for cam, (age, path) in cam_ages.items():
        if age < 0:
            detail_parts.append(f"cam{cam}: {path}")
            worst_age = 999999
        else:
            detail_parts.append(f"cam{cam}: {age}m")
            if age > worst_age:
                worst_age = age
                worst_path = path

    detail = " | ".join(detail_parts)

    if not _is_verdis_active_hours():
        return RunnerStatus("verdis-uploader", ok=True, warn=True,
                          detail=f"outside hours ({detail})", path=worst_path)

    ok = worst_age <= 10
    return RunnerStatus("verdis-uploader", ok=ok, detail=detail, path=worst_path)

def _parse_image_ts(filename: str) -> datetime | None:
    """Extract timestamp from image filename like 20260128_103000.png or 20260128_103000_001.png."""
    if m := VERDIS_TS_RE.search(filename):
        d, t = m[1], m[2]
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), int(t[:2]), int(t[2:4]), int(t[4:6]))
    return None

def _check_verdis_inference(registry_backend, prefix: str, name: str, cutoff_start: datetime | None = None) -> RunnerStatus:
    """Check verdis inference - find oldest folder missing results (last 7 days only, optionally after cutoff_start)."""
    if registry_backend is None:
        return RunnerStatus(name, ok=False, detail="no backend")

    prefix_parts = tuple(prefix.split("/"))  # e.g. ("verdis", "gadstrup", "5")

    print(f"[{name}] Listing files...")
    try:
        files = list(registry_backend.LIST(f"{prefix}/"))
    except Exception as e:
        return RunnerStatus(name, ok=False, detail=str(e)[:30])

    has_result_keys: set[tuple[str, str]] = set()
    for f in files:
        parts = f.parts
        if len(parts) != len(prefix_parts) + 3 or parts[:len(prefix_parts)] != prefix_parts:
            continue
        if f.suffix != ".json" or "schema" in f.name:
            continue
        has_result_keys.add((parts[len(prefix_parts)], parts[len(prefix_parts) + 1]))

    cutoff = max(datetime.now() - timedelta(days=7), cutoff_start) if cutoff_start else datetime.now() - timedelta(days=7)

    print(f"[{name}] Scanning recent images...")
    folder_info: dict[str, tuple[datetime, bool, str]] = {}
    skipped_old = 0

    for f in files:
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        parts = f.parts
        if len(parts) < len(prefix_parts) + 2:
            continue

        folder_name = parts[len(prefix_parts)]
        if folder_name in folder_info:
            continue

        ts = _parse_image_ts(f.name)
        if ts is None:
            ts = _parse_verdis_folder_ts(folder_name)
        if ts is None:
            continue

        if ts < cutoff:
            skipped_old += 1
            continue

        has_result = (folder_name, f.stem) in has_result_keys
        folder_info[folder_name] = (ts, has_result, str(f))

    if not folder_info:
        return RunnerStatus(name, ok=True, detail=f"no recent (skipped {skipped_old} old)")

    pending_folders = [(fname, info) for fname, info in folder_info.items() if not info[1]]
    pending_count = len(pending_folders)

    print(f"[{name}] Checked {len(folder_info)} recent, {pending_count} pending (skipped {skipped_old} old)")

    if pending_count == 0:
        latest = max(folder_info.keys(), key=lambda k: folder_info[k][0])
        latest_ts = folder_info[latest][0]
        age_min = int((datetime.now() - latest_ts).total_seconds() // 60)
        return RunnerStatus(name, ok=True,
                          detail=f"all done, latest {age_min}m ago",
                          path=f"{prefix}/{latest}", pending=0)

    oldest_pending = min(pending_folders, key=lambda x: x[1][0])
    oldest_name, (oldest_ts, _, oldest_img) = oldest_pending
    age_min = int((datetime.now() - oldest_ts).total_seconds() // 60)

    ok = age_min <= 10
    return RunnerStatus(name, ok=ok,
                       detail=f"{pending_count} pending, oldest {age_min}m",
                       path=f"{prefix}/{oldest_name}", pending=pending_count)
