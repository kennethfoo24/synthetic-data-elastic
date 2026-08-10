from __future__ import annotations

import itertools
import random
from datetime import datetime

from synthgen import GLOBAL_SEED

# Hourly diurnal anchor points (UTC), linearly interpolated between.
_DIURNAL = {0: 0.25, 2: 0.20, 5: 0.25, 7: 0.50, 10: 1.00, 16: 1.00, 19: 0.60, 23: 0.30}
_ANCHORS = sorted(_DIURNAL)


def _diurnal(t: datetime) -> float:
    h = t.hour + t.minute / 60.0
    pts = _ANCHORS + [_ANCHORS[0] + 24]
    for lo, hi in itertools.pairwise(pts):
        if lo <= h < hi:
            v_lo, v_hi = _DIURNAL[lo % 24], _DIURNAL[hi % 24]
            return v_lo + (v_hi - v_lo) * (h - lo) / (hi - lo)
    return _DIURNAL[_ANCHORS[-1]]


def _weekly(t: datetime, flow_class: str) -> float:
    if flow_class == "user" and t.weekday() >= 5:
        return 0.30
    return 1.0


def _jitter(t: datetime, key: str, seed: int) -> float:
    minute_bucket = int(t.timestamp()) // 60
    rng = random.Random(f"{seed}|{key}|{minute_bucket}")
    return rng.uniform(0.85, 1.15)


def rate_multiplier(t: datetime, flow_class: str, key: str, seed: int = GLOBAL_SEED) -> float:
    if t.tzinfo is None:
        raise ValueError("t must be timezone-aware")
    return _diurnal(t) * _weekly(t, flow_class) * _jitter(t, key, seed)


def in_backup_window(t: datetime) -> bool:
    if t.tzinfo is None:
        raise ValueError("t must be timezone-aware")
    return 1 <= t.hour < 3
