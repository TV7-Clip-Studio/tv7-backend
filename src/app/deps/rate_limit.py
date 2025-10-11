from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, status

WINDOW_SECONDS = 60
MAX_REQUESTS = 30

_buckets: defaultdict[str, list[float]] = defaultdict(list)


def check_rate(key: str) -> None:
    now = time.time()
    queue = _buckets[key]
    # Drop stale timestamps
    while queue and now - queue[0] > WINDOW_SECONDS:
        queue.pop(0)
    if len(queue) >= MAX_REQUESTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit")
    queue.append(now)
