"""A small fixed-window rate limiter for the endpoints worth protecting.

Deliberately in-process and in-memory. This guards one web process against
credential stuffing, which is the threat a single-node deployment actually
faces; it is not a distributed limiter, and behind more than one process each
would keep its own count. That trade-off is written down here rather than
discovered later: the fix for multiple processes is Redis, not a bigger dict.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    """Fixed window per key. Returns the seconds to wait, or 0 when allowed."""

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = [stamp for stamp in self._hits[key] if stamp > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return max(1, int(self.window - (now - hits[0])))
            hits.append(now)
            self._hits[key] = hits

            # Opportunistic sweep so a long-running process does not accumulate
            # a key per address that ever tried once.
            if len(self._hits) > 4096:
                for other, stamps in list(self._hits.items()):
                    if not any(stamp > cutoff for stamp in stamps):
                        del self._hits[other]
            return 0

    def reset(self, key: str | None = None) -> None:
        """Clear a key after a success, or everything (used by the tests)."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# Ten attempts a minute is generous for a shopkeeper mistyping a password and
# useless for guessing one.
login_limiter = RateLimiter(limit=10, window_seconds=60)
