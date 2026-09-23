"""Execution recording for reproducible test runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass
class ExecutionRecord:
    operation: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    success: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def finish(self, success: bool, **details: Any) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.success = success
        self.details.update(details)


class RunRecorder:
    def __init__(self, output_dir: str | Path = "artifacts") -> None:
        self.output_dir = Path(output_dir)
        self.records: list[ExecutionRecord] = []

    def start(self, operation: str) -> ExecutionRecord:
        record = ExecutionRecord(operation=operation)
        self.records.append(record)
        return record

    def write_json(self, filename: str = "run.json") -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / filename
        target.write_text(
            json.dumps([asdict(record) for record in self.records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

