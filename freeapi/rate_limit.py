import threading
import time
from collections import defaultdict
from typing import Dict, List

import logging

logger = logging.getLogger('freeapi')


class SlidingWindowRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: Dict[str, List[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()

    def is_allowed(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._buckets[key]
            cutoff = now - window
            self._buckets[key] = [t for t in hits if t > cutoff]
            if len(self._buckets[key]) >= limit:
                return False
            self._buckets[key].append(now)
            if now - self._last_cleanup > 300:
                self._cleanup(now)
            return True

    def _cleanup(self, now: float):
        hour_ago = now - 3600
        for key in list(self._buckets.keys()):
            self._buckets[key] = [t for t in self._buckets[key] if t > hour_ago]
            if not self._buckets[key]:
                del self._buckets[key]
        self._last_cleanup = now


_limiter = SlidingWindowRateLimiter()


def check_rate_limit(ip: str, endpoint: str, limit: int, window: int) -> bool:
    return _limiter.is_allowed(f'{ip}:{endpoint}', limit, window)
