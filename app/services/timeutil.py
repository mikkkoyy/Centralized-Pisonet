"""Time utilities.

All timestamps in the system are integer Unix epoch seconds (UTC).
A single documented time model: the server's wall clock is the only
authoritative time source for billing; clients never supply billing time.
"""

from __future__ import annotations

import time
from typing import Callable

Clock = Callable[[], int]


def utcnow() -> int:
    """Current UTC time as integer epoch seconds."""
    return int(time.time())
