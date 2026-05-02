"""JSONL interaction logging for simulated eval sessions.

One file per eval run: evaluation/logs/<run_id>.jsonl
Each line is a self-contained event. Event kinds:
  - session_start  : metadata about a profile/note pairing
  - interaction    : one question->answer->eval cycle
  - hint           : a hint was generated (and optionally responded to)
  - session_end    : session-level aggregates + final mastery
  - run_end        : cross-session budget + totals

Kept as JSONL (not a DB) so runs stay inspectable by hand and diff-able in git.
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional


DEFAULT_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def _default_serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj).__name__}")


class RunLogger:
    """Appends events to a single JSONL file. Flushes on every write."""

    def __init__(self, run_id: Optional[str] = None, log_dir: str = DEFAULT_LOG_DIR):
        os.makedirs(log_dir, exist_ok=True)
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.path = os.path.join(log_dir, f"{self.run_id}.jsonl")
        self._fh = open(self.path, "a", encoding="utf-8")

    def log(self, kind: str, **fields):
        event = {
            "ts": datetime.now().isoformat(),
            "run_id": self.run_id,
            "kind": kind,
            **fields,
        }
        self._fh.write(json.dumps(event, default=_default_serialize) + "\n")
        self._fh.flush()

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


def read_run(path: str) -> list:
    """Load all events from a JSONL log."""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events
