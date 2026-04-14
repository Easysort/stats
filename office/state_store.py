"""JSON-backed persistence for dashboard snapshots and section history."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stats.office.models import OfficeSnapshot, SECTION_NAMES, SectionName


class JsonStateStore:
  def __init__(self, root: Path, *, history_limit: int = 240):
    self.root = root
    self.history_limit = history_limit
    self.latest_path = root / "latest_status.json"
    self.history_dir = root / "history"

  def _ensure_dirs(self) -> None:
    self.root.mkdir(parents=True, exist_ok=True)
    self.history_dir.mkdir(parents=True, exist_ok=True)

  def _history_path(self, section_name: SectionName) -> Path:
    return self.history_dir / f"{section_name}.jsonl"

  def load_snapshot(self) -> OfficeSnapshot | None:
    if not self.latest_path.exists():
      return None
    try:
      raw = json.loads(self.latest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
      return None
    snapshot = OfficeSnapshot.from_storage_dict(raw)
    if snapshot is None:
      return None
    for section_name in SECTION_NAMES:
      snapshot.sections[section_name].history = self.load_history(section_name)
    return snapshot

  def load_history(self, section_name: SectionName, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = self._history_path(section_name)
    if not path.exists():
      return []

    history: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[-(limit or self.history_limit):]:
      if not line.strip():
        continue
      try:
        history.append(json.loads(line))
      except json.JSONDecodeError:
        continue
    return history

  def save_snapshot(self, snapshot: OfficeSnapshot) -> None:
    self._ensure_dirs()
    self.latest_path.write_text(
      json.dumps(snapshot.to_storage_dict(), indent=2),
      encoding="utf-8",
    )
    for section_name in SECTION_NAMES:
      self._append_history(section_name, snapshot)

  def _append_history(self, section_name: SectionName, snapshot: OfficeSnapshot) -> None:
    path = self._history_path(section_name)
    section = snapshot.sections[section_name]
    record = {
      "recorded_at": snapshot.to_dict(include_history=False)["generated_at"],
      "status": section.status,
      "checked_at": section.meta(include_history=False)["checked_at"],
      "data_updated_at": section.meta(include_history=False)["data_updated_at"],
      "last_ok_at": section.meta(include_history=False)["last_ok_at"],
      "last_error": section.last_error,
      "source": section.source,
      "summary": section.summary,
    }

    lines = []
    if path.exists():
      lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines.append(json.dumps(record))
    path.write_text("\n".join(lines[-self.history_limit:]) + "\n", encoding="utf-8")
