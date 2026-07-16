from __future__ import annotations

import time
from collections import OrderedDict

from fastapi import HTTPException, status


class TokenBucketLimiter:
    """Minimal in-memory token bucket, per key (typically a dashboard user id).

    Protects state-changing endpoints (e.g. PATCH command overrides, DELETE
    a session) from a stolen session being used for abuse/brute force.
    In-memory is sufficient for the InProcessTransport deployment shape; a
    Redis-backed limiter is a drop-in swap for multi-process deployments,
    not required for v0.1.

    Deliberately dependency-free (no FastAPI `Depends`/auth imports) so it
    can be used both by `commands.ratelimit.rate_limit_dependency` (which
    does depend on auth) and directly by `auth.oauth` itself, without
    creating an import cycle between the two.

    Bounded by `max_tracked_keys` (default 10,000, LRU-evicted) so a
    long-running process with many distinct users/sessions over its
    lifetime doesn't accumulate one bucket entry per key forever --
    evicting a stale entry is harmless, it just resets that key back to a
    full bucket next time it's seen (equivalent to it never having been
    rate-limited yet, which is already true for any new key).
    """

    def __init__(
        self, max_calls: int, per_seconds: float, *, max_tracked_keys: int = 10_000
    ) -> None:
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.max_tracked_keys = max_tracked_keys
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def check(self, key: str) -> None:
        now = time.monotonic()
        tokens, last_refill = self._buckets.pop(key, (float(self.max_calls), now))
        refill_rate = self.max_calls / self.per_seconds
        tokens = min(self.max_calls, tokens + (now - last_refill) * refill_rate)

        if tokens < 1:
            self._buckets[key] = (tokens, now)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")

        self._buckets[key] = (tokens - 1, now)
        if len(self._buckets) > self.max_tracked_keys:
            self._buckets.popitem(last=False)
