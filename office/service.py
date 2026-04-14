"""Background refresh service for the hosted office dashboard."""
from __future__ import annotations

import copy
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from easysort.helpers import REGISTRY_LOCAL_IP
from easysort.registry import RegistryBase
from stats.office.alerts import check_and_notify
from stats.office.health import (
  DeviceStatus,
  IPDeviceStatus,
  RunnerStatus,
  get_device_health,
  get_ip_device_health,
  get_runner_health,
  get_tracking_health,
)
from stats.office.models import OfficeSnapshot, RefreshState, SectionName, SectionSnapshot, isoformat
from stats.office.state_store import JsonStateStore
from stats.office.storage import StorageHistory, get_all_storage

REFRESH_INTERVAL = int(os.environ.get("STATS_REFRESH_INTERVAL", "180"))
HEAVY_INTERVAL = int(os.environ.get("STATS_HEAVY_INTERVAL", "1800"))
STATS_STALE_MULTIPLIER = float(os.environ.get("STATS_STALE_MULTIPLIER", "2"))
MKV_VOLUME = os.environ.get("MKV_VOLUME", "/media/easysort/lenovo")
DEVICES_TXT = Path(__file__).parent / "devices.txt"
STATE_DIR = Path(__file__).parent / "state"


class OfficeMonitorService:
  def __init__(
    self,
    *,
    refresh_interval: int = REFRESH_INTERVAL,
    heavy_interval: int = HEAVY_INTERVAL,
    stale_multiplier: float = STATS_STALE_MULTIPLIER,
    devices_txt_path: Path = DEVICES_TXT,
    mkv_volume: str = MKV_VOLUME,
    state_store: JsonStateStore | None = None,
    registry_factory: Callable[[], RegistryBase] | None = None,
    device_collector: Callable[[Any], list[DeviceStatus]] | None = None,
    ip_device_collector: Callable[[Path], list[IPDeviceStatus]] | None = None,
    runner_collector: Callable[[Any], list[RunnerStatus]] | None = None,
    tracking_collector: Callable[[bool], list[RunnerStatus]] | None = None,
    storage_collector: Callable[[str, bool], tuple[StorageHistory, StorageHistory]] | None = None,
    alert_notifier: Callable[[OfficeSnapshot], None] | None = check_and_notify,
  ):
    self.refresh_interval = refresh_interval
    self.heavy_interval = heavy_interval
    self.stale_multiplier = stale_multiplier
    self.devices_txt_path = devices_txt_path
    self.mkv_volume = mkv_volume
    self.state_store = state_store or JsonStateStore(STATE_DIR)
    self.registry_factory = registry_factory or (lambda: RegistryBase(base=REGISTRY_LOCAL_IP))
    self.device_collector = device_collector or get_device_health
    self.ip_device_collector = ip_device_collector or get_ip_device_health
    self.runner_collector = runner_collector or get_runner_health
    self.tracking_collector = tracking_collector or get_tracking_health
    self.storage_collector = storage_collector or get_all_storage
    self.alert_notifier = alert_notifier

    self._registry: RegistryBase | None = None
    self._lock = threading.RLock()
    self._stop_event = threading.Event()
    self._thread: threading.Thread | None = None

    persisted = self.state_store.load_snapshot()
    self._snapshot = persisted or OfficeSnapshot.empty(
      light_interval_seconds=self.refresh_interval,
      heavy_interval_seconds=self.heavy_interval,
    )
    self._snapshot.refresh.light_interval_seconds = self.refresh_interval
    self._snapshot.refresh.heavy_interval_seconds = self.heavy_interval
    self._update_next_refresh_times(self._snapshot)

  def start(self) -> None:
    if self._thread and self._thread.is_alive():
      return
    self._stop_event.clear()
    self._thread = threading.Thread(target=self._run_loop, daemon=True, name="office-monitor")
    self._thread.start()

  def stop(self) -> None:
    self._stop_event.set()
    if self._thread and self._thread.is_alive():
      self._thread.join(timeout=5)

  def refresh_now(self, *, heavy: bool = False) -> OfficeSnapshot:
    return self._refresh_once(heavy=heavy)

  def get_snapshot(self) -> OfficeSnapshot:
    with self._lock:
      snapshot = copy.deepcopy(self._snapshot)
    return self._apply_staleness(snapshot)

  def get_snapshot_dict(self) -> dict[str, Any]:
    return self.get_snapshot().to_dict()

  def get_section_response(self, section_name: SectionName) -> dict[str, Any]:
    return self.get_snapshot().section_response(section_name)

  def _run_loop(self) -> None:
    first_pass = True
    while not self._stop_event.is_set():
      snapshot = self.get_snapshot()
      now = datetime.now()
      should_heavy = first_pass or self._is_due(snapshot.refresh.last_heavy_at, self.heavy_interval, now)
      should_refresh = should_heavy or first_pass or self._is_due(snapshot.refresh.last_refresh_at, self.refresh_interval, now)
      if should_refresh:
        self._refresh_once(heavy=should_heavy)
        first_pass = False
        continue
      self._stop_event.wait(timeout=1)

  def _refresh_once(self, *, heavy: bool = False) -> OfficeSnapshot:
    now = datetime.now()
    previous = self.get_snapshot()

    if heavy:
      self._sync_registry()

    sections: dict[SectionName, SectionSnapshot] = {
      "devices": self._collect_section(
        "devices",
        now,
        previous.sections["devices"],
        lambda: self._serialize_devices(self.device_collector(self._get_registry().backend)),
        _summarize_devices,
      ),
      "ip_devices": self._collect_section(
        "ip_devices",
        now,
        previous.sections["ip_devices"],
        lambda: self._serialize_ip_devices(self.ip_device_collector(self.devices_txt_path)),
        _summarize_ip_devices,
      ),
      "runners": self._collect_section(
        "runners",
        now,
        previous.sections["runners"],
        lambda: self._serialize_runners(self.runner_collector(self._get_registry().backend)),
        _summarize_runners,
      ),
      "tracking": self._collect_section(
        "tracking",
        now,
        previous.sections["tracking"],
        lambda: self._serialize_runners(self.tracking_collector(heavy)),
        _summarize_runners,
      ),
      "storage": self._collect_section(
        "storage",
        now,
        previous.sections["storage"],
        lambda: self._serialize_storage(*self.storage_collector(self.mkv_volume, heavy)),
        _summarize_storage,
      ),
    }

    snapshot = OfficeSnapshot(
      generated_at=now,
      refresh=RefreshState(
        light_interval_seconds=self.refresh_interval,
        heavy_interval_seconds=self.heavy_interval,
        last_refresh_at=now,
        last_heavy_at=now if heavy else previous.refresh.last_heavy_at,
      ),
      sections=sections,
      source="live",
    )
    self._update_next_refresh_times(snapshot)

    with self._lock:
      self.state_store.save_snapshot(snapshot)
      for section_name in snapshot.sections:
        snapshot.sections[section_name].history = self.state_store.load_history(section_name)
      self._snapshot = snapshot

    if self.alert_notifier:
      try:
        self.alert_notifier(snapshot)
      except Exception as exc:
        print(f"[alerts] Error during alert check: {exc}")

    return self.get_snapshot()

  def _collect_section(
    self,
    section_name: SectionName,
    now: datetime,
    previous: SectionSnapshot,
    fetcher: Callable[[], Any],
    summarizer: Callable[[Any], tuple[str, dict[str, Any]]],
  ) -> SectionSnapshot:
    try:
      payload = fetcher()
      status, summary = summarizer(payload)
      section = SectionSnapshot(
        name=section_name,
        payload=payload,
        status=status,
        checked_at=now,
        data_updated_at=now,
        last_ok_at=now if status == "ok" else previous.last_ok_at,
        last_error=None,
        source="live",
        summary=summary,
        history=previous.history,
      )
      if previous.last_ok_at and section.last_ok_at is None:
        section.last_ok_at = previous.last_ok_at
      return section
    except Exception as exc:
      summary = copy.deepcopy(previous.summary)
      return SectionSnapshot(
        name=section_name,
        payload=copy.deepcopy(previous.payload),
        status="stale" if previous.data_updated_at else "error",
        checked_at=now,
        data_updated_at=previous.data_updated_at,
        last_ok_at=previous.last_ok_at,
        last_error=str(exc)[:200],
        source="persisted",
        summary=summary,
        history=previous.history,
      )

  def _sync_registry(self) -> None:
    try:
      self._get_registry().SYNC()
    except Exception as exc:
      print(f"[registry] Sync error: {exc}")

  def _get_registry(self) -> RegistryBase:
    if self._registry is None:
      self._registry = self.registry_factory()
    return self._registry

  def _apply_staleness(self, snapshot: OfficeSnapshot) -> OfficeSnapshot:
    threshold_seconds = max(self.refresh_interval, int(self.refresh_interval * self.stale_multiplier))
    now = datetime.now()
    for section in snapshot.sections.values():
      if section.data_updated_at is None:
        section.status = "stale"
        continue
      age_seconds = (now - section.data_updated_at).total_seconds()
      if age_seconds > threshold_seconds:
        section.status = "stale"
    self._update_next_refresh_times(snapshot, reference_time=now)
    return snapshot

  def _update_next_refresh_times(self, snapshot: OfficeSnapshot, *, reference_time: datetime | None = None) -> None:
    reference = reference_time or datetime.now()
    last_refresh = snapshot.refresh.last_refresh_at or reference
    last_heavy = snapshot.refresh.last_heavy_at or reference
    snapshot.refresh.light_interval_seconds = self.refresh_interval
    snapshot.refresh.heavy_interval_seconds = self.heavy_interval
    snapshot.refresh.next_refresh_at = last_refresh + timedelta(seconds=self.refresh_interval)
    snapshot.refresh.next_heavy_at = last_heavy + timedelta(seconds=self.heavy_interval)

  @staticmethod
  def _is_due(last_run: datetime | None, interval_seconds: int, now: datetime) -> bool:
    if last_run is None:
      return True
    return (now - last_run).total_seconds() >= interval_seconds

  @staticmethod
  def _serialize_devices(devices: list[DeviceStatus]) -> list[dict[str, Any]]:
    return [
      {
        "name": device.name,
        "ok": device.ok,
        "age_minutes": device.age_minutes,
        "last_seen": isoformat(device.last_seen),
        "last_path": device.last_path,
        "error": device.error,
      }
      for device in devices
    ]

  @staticmethod
  def _serialize_ip_devices(devices: list[IPDeviceStatus]) -> list[dict[str, Any]]:
    return [
      {
        "name": device.name,
        "ok": device.ok,
        "detail": device.detail,
        "over_temp": device.over_temp,
        "tmux_running": device.tmux_running,
        "temp_history": [
          {
            "timestamp": isoformat(timestamp),
            "temp_c": temp_c,
            "tmux_running": tmux_running,
          }
          for timestamp, temp_c, tmux_running in (device.temp_history or [])
        ],
      }
      for device in devices
    ]

  @staticmethod
  def _serialize_runners(runners: list[RunnerStatus]) -> list[dict[str, Any]]:
    return [
      {
        "name": runner.name,
        "ok": runner.ok,
        "warn": runner.warn,
        "detail": runner.detail,
        "path": runner.path,
        "pending": runner.pending,
      }
      for runner in runners
    ]

  @staticmethod
  def _serialize_storage(local: StorageHistory, cloud: StorageHistory) -> dict[str, Any]:
    return {
      "local": _serialize_storage_history(local),
      "cloud": _serialize_storage_history(cloud),
    }


def _serialize_storage_history(history: StorageHistory | None) -> dict[str, Any] | None:
  if history is None:
    return None
  return {
    "name": history.name,
    "current": {
      "used_gb": round(history.current.used_gb, 2),
      "total_gb": round(history.current.total_gb, 2),
      "free_gb": round(history.current.free_gb, 2),
      "percent_used": round(history.current.percent_used, 1),
    },
    "history": [
      {
        "timestamp": isoformat(point.timestamp),
        "used_gb": round(point.used_gb, 2),
        "total_gb": round(point.total_gb, 2),
      }
      for point in history.history
    ],
  }


def _summarize_devices(devices: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
  ok_count = sum(1 for device in devices if device.get("ok"))
  total = len(devices)
  error_count = total - ok_count
  status = "error" if error_count else "ok"
  return status, {
    "total": total,
    "ok": ok_count,
    "error": error_count,
  }


def _summarize_ip_devices(devices: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
  ok_count = sum(1 for device in devices if device.get("ok"))
  total = len(devices)
  error_count = total - ok_count
  hot_count = sum(1 for device in devices if device.get("over_temp"))
  status = "error" if error_count else "ok"
  return status, {
    "total": total,
    "ok": ok_count,
    "error": error_count,
    "over_temp": hot_count,
  }


def _summarize_runners(runners: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
  total = len(runners)
  warn_count = sum(1 for runner in runners if runner.get("warn"))
  error_count = sum(1 for runner in runners if not runner.get("ok") and not runner.get("warn"))
  ok_count = total - warn_count - error_count
  if error_count:
    status = "error"
  elif warn_count:
    status = "warn"
  else:
    status = "ok"
  return status, {
    "total": total,
    "ok": ok_count,
    "warn": warn_count,
    "error": error_count,
  }


def _summarize_storage(storage: dict[str, Any]) -> tuple[str, dict[str, Any]]:
  percents = []
  volumes = 0
  for volume_name in ("local", "cloud"):
    current = ((storage.get(volume_name) or {}).get("current") or {})
    percent_used = current.get("percent_used")
    if percent_used is None:
      continue
    volumes += 1
    percents.append(float(percent_used))

  max_percent = round(max(percents, default=0.0), 1)
  if not volumes:
    status = "stale"
  elif max_percent >= 95:
    status = "error"
  elif max_percent >= 85:
    status = "warn"
  else:
    status = "ok"

  return status, {
    "volumes": volumes,
    "max_percent_used": max_percent,
  }
