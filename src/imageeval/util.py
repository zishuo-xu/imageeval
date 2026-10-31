from __future__ import annotations

import math
from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def round_half_up(value: float) -> int:
    return int(math.floor(float(value) + 0.5))
