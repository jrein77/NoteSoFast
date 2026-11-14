"""
JSON persistence for the in-memory app state, so review history (and the
graph it drives) survives server restarts.

Datetimes are round-tripped as {"__dt__": iso_string}.
"""

import json
import os
from datetime import datetime
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "state.json"


def _default(obj):
    if isinstance(obj, datetime):
        return {"__dt__": obj.isoformat()}
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Not serializable: {type(obj)}")


def _hook(obj):
    if "__dt__" in obj and len(obj) == 1:
        return datetime.fromisoformat(obj["__dt__"])
    return obj


def save(payload):
    DATA_PATH.parent.mkdir(exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, default=_default))
    os.replace(tmp, DATA_PATH)


def load():
    try:
        return json.loads(DATA_PATH.read_text(), object_hook=_hook)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
