"""Append-only JSONL files (decisions log, trade ledger)."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        line = json.dumps(record, default=str, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
