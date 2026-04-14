"""Snapshot models for the hosted office dashboard."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

StatusLevel = Literal["ok", "warn", "error", "stale"]
SectionName = Literal["devices", "ip_devices", "runners", "tracking", "storage"]
SECTION_NAMES = tuple(get_args(SectionName))
STATUS_PRIORITY: dict[StatusLevel, int] = {
  "ok": 0,
  "warn": 1,
  "error": 2,
  "stale": 3,
}


def isoformat(value: datetime | None) -> str | None:
  return value.isoformat() if value else None


def parse_datetime(value: str | None) -> datetime | None:
  if not value:
    return None
  try:
    return datetime.fromisoformat(value)
  except ValueError:
    return None


def age_minutes(value: datetime | None, now: datetime | None = None) -> int | None:
  if value is None:
    return None
  current = now or datetime.now()
  return max(0, int((current - value).total_seconds() // 60))


def worst_status(statuses: list[StatusLevel]) -> StatusLevel:
  if not statuses:
    return "stale"
  return max(statuses, key=STATUS_PRIORITY.__getitem__)


def default_payload(section_name: SectionName) -> Any:
  if section_name == "storage":
    return {"local": None, "cloud": None}
  return []


@dataclass
class RefreshState:
  light_interval_seconds: int
  heavy_interval_seconds: int
  last_refresh_at: datetime | None = None
  last_heavy_at: datetime | None = None
  next_refresh_at: datetime | None = None
  next_heavy_at: datetime | None = None

  def to_dict(self) -> dict[str, Any]:
    return {
      "light_interval_seconds": self.light_interval_seconds,
      "heavy_interval_seconds": self.heavy_interval_seconds,
      "last_refresh_at": isoformat(self.last_refresh_at),
      "last_heavy_at": isoformat(self.last_heavy_at),
      "next_refresh_at": isoformat(self.next_refresh_at),
      "next_heavy_at": isoformat(self.next_heavy_at),
    }

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> RefreshState:
    return cls(
      light_interval_seconds=int(data.get("light_interval_seconds", 180)),
      heavy_interval_seconds=int(data.get("heavy_interval_seconds", 1800)),
      last_refresh_at=parse_datetime(data.get("last_refresh_at")),
      last_heavy_at=parse_datetime(data.get("last_heavy_at")),
      next_refresh_at=parse_datetime(data.get("next_refresh_at")),
      next_heavy_at=parse_datetime(data.get("next_heavy_at")),
    )


@dataclass
class SectionSnapshot:
  name: SectionName
  payload: Any
  status: StatusLevel = "stale"
  checked_at: datetime | None = None
  data_updated_at: datetime | None = None
  last_ok_at: datetime | None = None
  last_error: str | None = None
  source: str = "persisted"
  summary: dict[str, Any] = field(default_factory=dict)
  history: list[dict[str, Any]] = field(default_factory=list)

  def meta(self, now: datetime | None = None, *, include_history: bool = True) -> dict[str, Any]:
    current = now or datetime.now()
    meta = {
      "status": self.status,
      "checked_at": isoformat(self.checked_at),
      "checked_age_minutes": age_minutes(self.checked_at, current),
      "data_updated_at": isoformat(self.data_updated_at),
      "data_age_minutes": age_minutes(self.data_updated_at, current),
      "last_ok_at": isoformat(self.last_ok_at),
      "last_error": self.last_error,
      "source": self.source,
      "stale": self.status == "stale",
      "summary": deepcopy(self.summary),
    }
    if include_history:
      meta["history"] = deepcopy(self.history)
    return meta

  def to_storage_dict(self) -> dict[str, Any]:
    return {
      "payload": deepcopy(self.payload),
      "status": self.status,
      "checked_at": isoformat(self.checked_at),
      "data_updated_at": isoformat(self.data_updated_at),
      "last_ok_at": isoformat(self.last_ok_at),
      "last_error": self.last_error,
      "source": self.source,
      "summary": deepcopy(self.summary),
    }

  @classmethod
  def from_storage_dict(cls, name: SectionName, data: dict[str, Any] | None) -> SectionSnapshot:
    if not data:
      return cls(name=name, payload=default_payload(name))
    return cls(
      name=name,
      payload=deepcopy(data.get("payload", default_payload(name))),
      status=data.get("status", "stale"),
      checked_at=parse_datetime(data.get("checked_at")),
      data_updated_at=parse_datetime(data.get("data_updated_at")),
      last_ok_at=parse_datetime(data.get("last_ok_at")),
      last_error=data.get("last_error"),
      source=data.get("source", "persisted"),
      summary=deepcopy(data.get("summary", {})),
    )


@dataclass
class OfficeSnapshot:
  generated_at: datetime
  refresh: RefreshState
  sections: dict[SectionName, SectionSnapshot] = field(default_factory=dict)
  source: str = "persisted"

  def __post_init__(self) -> None:
    normalized: dict[SectionName, SectionSnapshot] = {}
    for name in SECTION_NAMES:
      section = self.sections.get(name)
      if section is None:
        section = SectionSnapshot(name=name, payload=default_payload(name))
      normalized[name] = section
    self.sections = normalized

  @property
  def status(self) -> StatusLevel:
    return worst_status([self.sections[name].status for name in SECTION_NAMES])

  def summary(self) -> dict[str, Any]:
    statuses = [self.sections[name].status for name in SECTION_NAMES]
    return {
      "sections_total": len(SECTION_NAMES),
      "healthy_sections": sum(1 for status in statuses if status == "ok"),
      "warn_sections": sum(1 for status in statuses if status == "warn"),
      "error_sections": sum(1 for status in statuses if status == "error"),
      "stale_sections": sum(1 for status in statuses if status == "stale"),
      "devices_total": self.sections["devices"].summary.get("total", 0),
      "devices_down": self.sections["devices"].summary.get("error", 0),
      "ip_devices_total": self.sections["ip_devices"].summary.get("total", 0),
      "ip_devices_down": self.sections["ip_devices"].summary.get("error", 0),
      "runner_issues": self.sections["runners"].summary.get("error", 0) + self.sections["runners"].summary.get("warn", 0),
      "tracking_issues": self.sections["tracking"].summary.get("error", 0) + self.sections["tracking"].summary.get("warn", 0),
      "max_storage_percent": self.sections["storage"].summary.get("max_percent_used", 0),
    }

  def to_dict(self, now: datetime | None = None, *, include_history: bool = True) -> dict[str, Any]:
    current = now or datetime.now()
    meta = {
      name: self.sections[name].meta(current, include_history=include_history)
      for name in SECTION_NAMES
    }
    return {
      "timestamp": isoformat(self.generated_at),
      "generated_at": isoformat(self.generated_at),
      "status": self.status,
      "source": self.source,
      "summary": self.summary(),
      "refresh": self.refresh.to_dict(),
      "meta": meta,
      "devices": deepcopy(self.sections["devices"].payload),
      "ip_devices": deepcopy(self.sections["ip_devices"].payload),
      "runners": deepcopy(self.sections["runners"].payload),
      "tracking": deepcopy(self.sections["tracking"].payload),
      "storage": deepcopy(self.sections["storage"].payload),
    }

  def section_response(self, section_name: SectionName, now: datetime | None = None) -> dict[str, Any]:
    section = self.sections[section_name]
    return {
      "section": section_name,
      "status": section.status,
      "meta": section.meta(now, include_history=True),
      "data": deepcopy(section.payload),
    }

  def to_storage_dict(self) -> dict[str, Any]:
    return {
      "generated_at": isoformat(self.generated_at),
      "source": self.source,
      "refresh": self.refresh.to_dict(),
      "sections": {
        name: self.sections[name].to_storage_dict()
        for name in SECTION_NAMES
      },
    }

  @classmethod
  def empty(
    cls,
    *,
    generated_at: datetime | None = None,
    light_interval_seconds: int = 180,
    heavy_interval_seconds: int = 1800,
  ) -> OfficeSnapshot:
    return cls(
      generated_at=generated_at or datetime.now(),
      refresh=RefreshState(
        light_interval_seconds=light_interval_seconds,
        heavy_interval_seconds=heavy_interval_seconds,
      ),
      sections={},
      source="persisted",
    )

  @classmethod
  def from_storage_dict(cls, data: dict[str, Any] | None) -> OfficeSnapshot | None:
    if not data:
      return None
    sections_data = data.get("sections", {})
    sections: dict[SectionName, SectionSnapshot] = {}
    for name in SECTION_NAMES:
      sections[name] = SectionSnapshot.from_storage_dict(name, sections_data.get(name))
    return cls(
      generated_at=parse_datetime(data.get("generated_at")) or datetime.now(),
      refresh=RefreshState.from_dict(data.get("refresh", {})),
      sections=sections,
      source=data.get("source", "persisted"),
    )
