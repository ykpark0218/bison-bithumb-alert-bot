from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bison_bot.models import Signal


class AlertState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"sent_signals": {}, "rotate_offset": 0}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            self.data.update(loaded)
        if not isinstance(self.data.get("sent_signals"), dict):
            self.data["sent_signals"] = {}
        if not isinstance(self.data.get("rotate_offset"), int):
            self.data["rotate_offset"] = 0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def is_duplicate(self, signal: Signal, suppression_hours: int) -> bool:
        self.prune(suppression_hours)
        return signal.signal_id() in self.data["sent_signals"]

    def record(self, signal: Signal) -> None:
        self.data["sent_signals"][signal.signal_id()] = datetime.now(UTC).isoformat()

    def prune(self, suppression_hours: int) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=suppression_hours)
        kept: dict[str, str] = {}
        for signal_id, timestamp in self.data["sent_signals"].items():
            try:
                parsed = datetime.fromisoformat(timestamp)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if parsed >= cutoff:
                kept[signal_id] = timestamp
        self.data["sent_signals"] = kept

    def rotation_slice(self, symbols: list[str], batch_size: int) -> list[str]:
        if not symbols or batch_size <= 0:
            return []
        offset = int(self.data.get("rotate_offset", 0)) % len(symbols)
        doubled = symbols + symbols
        selected = doubled[offset : offset + min(batch_size, len(symbols))]
        self.data["rotate_offset"] = (offset + batch_size) % len(symbols)
        return selected
