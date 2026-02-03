"""Device and runner health checks."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import re
from tqdm import tqdm

SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png"}
TS_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})/(\d{2})/(\d{2})(\d{2})(\d{2})")
VERDIS_TS_RE = re.compile(r"(\d{8})_(\d{6})")  # YYYYMMDD_HHMMSS folder format

@dataclass
class DeviceStatus:
    name: str
    ok: bool
    age_minutes: int | None = None
    last_seen: datetime | None = None
    last_path: str | None = None
    error: str | None = None

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

def get_runner_health(registry_backend=None) -> list[RunnerStatus]:
    """Get health status for runners."""
    results = []
    
    # 1. Argo processor - not implemented (yellow)
    results.append(RunnerStatus("argo-processor", ok=True, warn=True, detail="not implemented"))
    
    # 2. Verdis uploader - check last folder
    results.append(_check_verdis_uploader(registry_backend))
    
    # 3. Verdis belt inference - check results
    results.append(_check_verdis_inference(registry_backend))
    
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

def _check_verdis_inference(registry_backend) -> RunnerStatus:
    """Check verdis belt inference - find oldest folder missing results (last 7 days only)."""
    if registry_backend is None:
        return RunnerStatus("verdis-belt-inference", ok=False, detail="no backend")
    
    print("[verdis-belt-inference] Listing files...")
    try:
        files = list(registry_backend.LIST("verdis/gadstrup/5/"))
    except Exception as e:
        return RunnerStatus("verdis-belt-inference", ok=False, detail=str(e)[:30])
    
    # Get result hash - using the known ID for VejebodRunnerJob.RegistryResult
    # Hash is in the filename like: image.jpg -> folder/image/HASH.json
    result_hash = "94733505"  # First 8 chars of the RegistryResult id
    
    # Only check folders from the past 7 days
    cutoff = datetime.now() - timedelta(days=7)
    
    # Collect image files from recent folders only
    print("[verdis-belt-inference] Collecting recent image files...")
    image_files: list[tuple[Path, str, datetime]] = []  # (path, folder_name, ts)
    seen_folders: set[str] = set()
    skipped_old = 0
    
    for f in files:
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        parts = f.parts
        if len(parts) < 5:  # verdis/gadstrup/5/FOLDER/image.jpg
            continue
        
        folder_name = parts[3]
        if folder_name in seen_folders:
            continue  # Only check first image per folder
        
        ts = _parse_verdis_folder_ts(folder_name)
        if ts is None:
            continue
        
        seen_folders.add(folder_name)
        
        # Skip folders older than cutoff
        if ts < cutoff:
            skipped_old += 1
            continue
        
        image_files.append((f, folder_name, ts))
    
    if not image_files:
        return RunnerStatus("verdis-belt-inference", ok=True, detail=f"no recent folders (skipped {skipped_old} old)")
    
    # Build expected result paths for recent images only
    print(f"[verdis-belt-inference] Checking {len(image_files)} recent folders (skipped {skipped_old} older than 7d)...")
    result_paths = [
        f"verdis/gadstrup/5/{folder}/{img.stem}/{result_hash}.json"
        for img, folder, _ in image_files
    ]
    
    # Use EXISTS_MULTIPLE for efficient batch checking
    exists_results = registry_backend.EXISTS_MULTIPLE(result_paths)
    
    # Build folder info with results
    folder_info: dict[str, tuple[datetime, bool, str]] = {}
    for (img, folder, ts), has_result in tqdm(
        zip(image_files, exists_results), 
        total=len(image_files), 
        desc="Processing results"
    ):
        folder_info[folder] = (ts, has_result, str(img))
    
    # Count pending (no results)
    pending_folders = [(name, info) for name, info in folder_info.items() if not info[1]]
    pending_count = len(pending_folders)
    
    print(f"[verdis-belt-inference] Found {pending_count} pending folders out of {len(folder_info)}")
    
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
