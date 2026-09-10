"""RateLimiter — the interface between "is this key over its limit right
now" and whatever actually tracks that (Phase 5). InMemoryRateLimiter is
the first, replaceable implementation: a plain per-process sliding
window, fine for a single-instance deployment (this codebase's current
production target — see docs/architecture.md) but explicitly NOT correct
across multiple instances, since each process would track its own,
independent count. A future RedisRateLimiter/CloudflareKVRateLimiter
implements this same interface once a real distributed backend exists;
nothing calling `check` needs to change.
"""

import time
from abc import ABC, abstractmethod
from collections import deque
from threading import Lock


class RateLimitExceededError(Exception):
    """Raised by `check` when `key` has already used its full quota for
    the current window. Callers (FastAPI dependencies) turn this into a
    429 — never a silent pass-through."""

    def __init__(self, *, retry_after_seconds: float) -> None:
        super().__init__(f"Rate limit exceeded; retry after {retry_after_seconds:.1f}s")
        self.retry_after_seconds = retry_after_seconds


class RateLimiter(ABC):
    @abstractmethod
    def check(self, key: str, *, limit: int, window_seconds: float) -> None:
        """Records one attempt for `key` and raises RateLimitExceededError
        if that pushes it over `limit` attempts within the trailing
        `window_seconds`. Returns normally (no value) when still within
        budget."""


class InMemoryRateLimiter(RateLimiter):
    """A sliding-window counter kept in a plain dict, guarded by one lock
    — correct for the single worker process this API runs as today
    (see app.publishing.build's own "no queue" precedent for the same
    single-process assumption elsewhere in this codebase). Old
    timestamps are pruned lazily on each `check` call for `key`, so
    memory only grows with the number of *distinct* keys seen, not the
    number of requests.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, *, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = window_seconds - (now - hits[0])
                raise RateLimitExceededError(retry_after_seconds=max(retry_after, 0.0))
            hits.append(now)
