"""
Simulated clock.

Every time-dependent part of the app (forgetting, connection decay, cognitive
debt) reads time from here instead of datetime.now(). That lets the demo
"time travel": fast-forward N days to watch memories and connections fade,
then review and watch them recover.

- offset_days: a persistent shift applied to real time (driven by the UI slider)
- frozen_at(): a context manager used when seeding back-dated review history
"""

from contextlib import contextmanager
from datetime import datetime, timedelta

_offset_days = 0.0
_frozen = None


def now():
    if _frozen is not None:
        return _frozen
    return datetime.now() + timedelta(days=_offset_days)


def get_offset_days():
    return _offset_days


def set_offset_days(days):
    global _offset_days
    _offset_days = max(0.0, float(days))
    return _offset_days


@contextmanager
def frozen_at(moment):
    """Pin now() to a specific datetime (used to replay seeded history)."""
    global _frozen
    previous = _frozen
    _frozen = moment
    try:
        yield
    finally:
        _frozen = previous
