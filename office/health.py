"""Device and runner health checks."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import json
import re
import urllib.request
from tqdm import tqdm

from supabase import create_client
from easysort.helpers import SUPABASE_KEY, SUPABASE_URL

SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png"}
TS_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})/(\d{2})/(\d{2})(\d{2})(\d{2})")
VERDIS_TS_RE = re.compile(r"(\d{8})_(\d{6})")  # YYYYMMDD_HHMMSS folder format
IP_DEVICE_HEALTH_TIMEOUT = 5
IP_DEVICE_TEMP_LIMIT_CELSIUS = 85

@dataclass
class DeviceStatus:
    name: str
    ok: bool
    age_minutes: int | None = None
    last_seen: datetime | None = None
    last_path: str | None = None
    error: str | None = None

@dataclass
class IPDeviceStatus:
    name: str
    ok: bool
    detail: str
    over_temp: bool = False  # True => show very red (temp > 85°C)

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


def get_ip_device_health(devices_txt_path: Path) -> list[IPDeviceStatus]:
    """Read devices.txt (lines: 'name ip'), call http://{ip}:5000/health, return status. Temp > 85°C => over_temp."""
    results: list[IPDeviceStatus] = []
    if not devices_txt_path.exists():
        return results
    lines = devices_txt_path.read_text().strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        name, ip = parts[0], parts[1].strip()
        url = f"http://{ip}:5000/health"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; Easysort-Stats/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=IP_DEVICE_HEALTH_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            camera = data.get("camera", "")
            status = data.get("status", "")
            temp = data.get("temperature_celsius")
            if temp is None:
                detail = "no temp"
                ok = False
                over_temp = False
            else:
                detail = f"{float(temp):.1f}°C"
                over_temp = float(temp) > IP_DEVICE_TEMP_LIMIT_CELSIUS
                ok = (camera == "ok" and status == "ok" and not over_temp)
            results.append(IPDeviceStatus(name=name, ok=ok, detail=detail, over_temp=over_temp))
        except Exception as e:
            results.append(IPDeviceStatus(name=name, ok=False, detail=str(e)[:40], over_temp=False))
    return results


def get_runner_health(registry_backend=None) -> list[RunnerStatus]:
    """Get health status for runners."""
    results = []
    
    # 1. Verdis uploader - check last folder
    results.append(_check_verdis_uploader(registry_backend))
    
    # 2. Verdis belt inference - check results
    results.append(_check_verdis_inference(registry_backend))
    
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
            week_parts.append(f"w{w}✓")
        else:
            week_parts.append(f"w{w}✗")
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
            month_parts.append(f"{month_name}✓")
        else:
            month_parts.append(f"{month_name}✗")
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

def _check_verdis_uploader(registry_backend) -> RunnerStatus:
    """Check verdis uploader health - last folder should be < 10 min old during active hours."""
    if registry_backend is None:
        return RunnerStatus("verdis-uploader", ok=False, detail="no backend")
    
    print("[verdis-uploader] Listing files...")
    try:
        files = list(tqdm(registry_backend.LIST("verdis/gadstrup/5/"), desc="Listing verdis files"))
    except Exception as e:
        return RunnerStatus("verdis-uploader", ok=False, detail=str(e)[:30])
    
    # Find all unique folders and their timestamps
    folder_ts: dict[str, datetime] = {}
    for f in tqdm(files, desc="Scanning folders"):
        parts = f.parts
        if len(parts) >= 4:  # verdis/gadstrup/5/YYYYMMDD_HHMMSS/...
            folder_name = parts[3]
            if folder_name not in folder_ts:
                if ts := _parse_verdis_folder_ts(folder_name):
                    folder_ts[folder_name] = ts
    
    if not folder_ts:
        return RunnerStatus("verdis-uploader", ok=False, detail="no folders found")
    
    # Find latest folder
    latest_folder = max(folder_ts.keys(), key=lambda k: folder_ts[k])
    latest_ts = folder_ts[latest_folder]
    age_min = int((datetime.now() - latest_ts).total_seconds() // 60)
    
    print(f"[verdis-uploader] Latest folder: {latest_folder} ({age_min}m ago)")
    
    # Check if we're in active hours
    if not _is_verdis_active_hours():
        return RunnerStatus("verdis-uploader", ok=True, warn=True, 
                          detail=f"outside hours ({age_min}m)", path=f"verdis/gadstrup/5/{latest_folder}")
    
    # During active hours, expect < 10 minutes
    ok = age_min <= 10
    return RunnerStatus("verdis-uploader", ok=ok, detail=f"{age_min}m ago", 
                       path=f"verdis/gadstrup/5/{latest_folder}")

def _parse_image_ts(filename: str) -> datetime | None:
    """Extract timestamp from image filename like 20260128_103000.png or 20260128_103000_001.png."""
    if m := VERDIS_TS_RE.search(filename):
        d, t = m[1], m[2]
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), int(t[:2]), int(t[2:4]), int(t[4:6]))
    return None

def _check_verdis_inference(registry_backend) -> RunnerStatus:
    """Check verdis belt inference - find oldest folder missing results (last 7 days only)."""
    if registry_backend is None:
        return RunnerStatus("verdis-belt-inference", ok=False, detail="no backend")

    print("[verdis-belt-inference] Listing files...")
    try:
        files = list(registry_backend.LIST("verdis/gadstrup/5/"))
    except Exception as e:
        return RunnerStatus("verdis-belt-inference", ok=False, detail=str(e)[:30])

    # Registry stores results at verdis/gadstrup/5/FOLDER/IMAGE_STEM/<type_hash>.json (type_hash = sha256, not UUID)
    # Build set of (folder_name, image_stem) that have at least one result file
    has_result_keys: set[tuple[str, str]] = set()
    for f in files:
        parts = f.parts
        if len(parts) != 6 or parts[:3] != ("verdis", "gadstrup", "5"):
            continue
        if f.suffix != ".json" or "schema" in f.name:
            continue
        # path is verdis/gadstrup/5/FOLDER/STEM/hash.json
        has_result_keys.add((parts[3], parts[4]))

    # Only check images from the past 7 days (based on image filename timestamp)
    cutoff = datetime.now() - timedelta(days=7)

    # Collect recent images and check results in one pass
    print("[verdis-belt-inference] Scanning recent images...")
    folder_info: dict[str, tuple[datetime, bool, str]] = {}  # folder -> (ts, has_result, img_path)
    skipped_old = 0

    for f in files:
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        parts = f.parts
        if len(parts) < 5:  # verdis/gadstrup/5/FOLDER/image.jpg
            continue

        folder_name = parts[3]
        if folder_name in folder_info:
            continue  # Only check first image per folder

        # Parse timestamp from image filename
        ts = _parse_image_ts(f.name)
        if ts is None:
            # Fallback to folder name
            ts = _parse_verdis_folder_ts(folder_name)
        if ts is None:
            continue

        # Skip images older than cutoff
        if ts < cutoff:
            skipped_old += 1
            continue

        # Check if this image has a result (any .json under folder/stem, matching registry layout)
        has_result = (folder_name, f.stem) in has_result_keys

        folder_info[folder_name] = (ts, has_result, str(f))
    
    if not folder_info:
        return RunnerStatus("verdis-belt-inference", ok=True, detail=f"no recent (skipped {skipped_old} old)")
    
    # Count pending (no results)
    pending_folders = [(name, info) for name, info in folder_info.items() if not info[1]]
    pending_count = len(pending_folders)
    
    print(f"[verdis-belt-inference] Checked {len(folder_info)} recent, {pending_count} pending (skipped {skipped_old} old)")
    
    if pending_count == 0:
        # All done - find the most recent processed folder
        latest = max(folder_info.keys(), key=lambda k: folder_info[k][0])
        latest_ts = folder_info[latest][0]
        age_min = int((datetime.now() - latest_ts).total_seconds() // 60)
        return RunnerStatus("verdis-belt-inference", ok=True, 
                          detail=f"all done, latest {age_min}m ago", 
                          path=f"verdis/gadstrup/5/{latest}", pending=0)
    
    # Find oldest folder missing results
    oldest_pending = min(pending_folders, key=lambda x: x[1][0])
    oldest_name, (oldest_ts, _, oldest_img) = oldest_pending
    age_min = int((datetime.now() - oldest_ts).total_seconds() // 60)
    
    # Expect processing within 30 minutes
    ok = age_min <= 30
    return RunnerStatus("verdis-belt-inference", ok=ok,
                       detail=f"{pending_count} pending, oldest {age_min}m",
                       path=f"verdis/gadstrup/5/{oldest_name}", pending=pending_count)
