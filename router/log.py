"""Yonlendirme kararlarinin kalici kaydi: data/logs/routing.jsonl (satir basina bir JSON)."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


class RoutingLog:
    def __init__(self, path: Path | str | None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def write(self, kind: str, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        row = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "kind": kind, **record}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(row, ensure_ascii=False, default=str)
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            logger.error(f"[router] routing.jsonl yazilamadi: {exc}")

    def read(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
