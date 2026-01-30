"""Storage monitoring for minikeyvalue and Supabase."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json, os, shutil

@dataclass
class StoragePoint:
    timestamp: datetime
    used_gb: float
    total_gb: float
    
    @property
    def free_gb(self) -> float: return self.total_gb - self.used_gb
    @property
    def percent_used(self) -> float: return (self.used_gb / self.total_gb * 100) if self.total_gb > 0 else 0

@dataclass  
class StorageHistory:
    name: str
    current: StoragePoint
    history: list[StoragePoint]
    
    def week_data(self) -> list[StoragePoint]:
        cutoff = datetime.now() - timedelta(days=7)
        return [p for p in self.history if p.timestamp >= cutoff]
    
    def month_data(self, months: int = 2) -> list[StoragePoint]:
        cutoff = datetime.now() - timedelta(days=30 * months)
        return [p for p in self.history if p.timestamp >= cutoff]

HISTORY_FILE = Path(__file__).parent / ".storage_history.json"

def _load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"minikeyvalue": [], "supabase": []}

def _save_history(data: dict):
    HISTORY_FILE.write_text(json.dumps(data, default=str))

def _add_point(name: str, point: StoragePoint):
    data = _load_history()
    data.setdefault(name, []).append({"ts": point.timestamp.isoformat(), "used": point.used_gb, "total": point.total_gb})
    # Keep last 90 days max
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    data[name] = [p for p in data[name] if p["ts"] >= cutoff]
    _save_history(data)

def _get_history(name: str) -> list[StoragePoint]:
    data = _load_history().get(name, [])
    return [StoragePoint(datetime.fromisoformat(p["ts"]), p["used"], p["total"]) for p in data]

def get_minikeyvalue_storage(volume_path: str = "/media/easysort/lenovo") -> StorageHistory:
    """Get minikeyvalue storage from local volume."""
    path = Path(volume_path)
    # Find the actual mount point (e.g., /media/.../lenovo)
    if path.exists():
        try:
            usage = shutil.disk_usage(path)
            current = StoragePoint(datetime.now(), usage.used / 1e9, usage.total / 1e9)
            _add_point("minikeyvalue", current)
        except OSError:
            current = StoragePoint(datetime.now(), 0, 0)
    else:
        current = StoragePoint(datetime.now(), 0, 0)
    
    return StorageHistory("MiniKeyValue", current, _get_history("minikeyvalue"))

def get_supabase_storage() -> StorageHistory:
    """Get Supabase storage usage (placeholder - needs API integration)."""
    # TODO: Implement actual Supabase storage API call
    # For now, return mock data that simulates realistic usage
    current = StoragePoint(datetime.now(), 45.2, 100.0)
    _add_point("supabase", current)
    return StorageHistory("Supabase", current, _get_history("supabase"))

def get_all_storage(mkv_path: str = "/media/easysort/lenovo") -> tuple[StorageHistory, StorageHistory]:
    """Get all storage metrics."""
    return get_minikeyvalue_storage(mkv_path), get_supabase_storage()
