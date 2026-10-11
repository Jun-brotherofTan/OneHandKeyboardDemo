"""Non-persistent console usage logging for test sessions."""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from threading import Lock
from typing import TextIO


class UsageLogger:
    def __init__(self, stream: TextIO | None = None):
        self.stream = stream or sys.stdout
        self.writer = csv.writer(self.stream)
        self.writer.writerow(
            ("timestamp_utc", "profile", "mode", "physical_key", "emitted_output")
        )
        self.stream.flush()
        self._closed = False
        self._lock = Lock()

    def record(self, profile: str, mode: str, physical_key: str, output: str) -> None:
        with self._lock:
            if self._closed:
                return
            self.writer.writerow(
                (
                    datetime.now(timezone.utc).isoformat(),
                    profile,
                    mode,
                    physical_key,
                    output,
                )
            )
            self.stream.flush()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self.stream.flush()
                self._closed = True