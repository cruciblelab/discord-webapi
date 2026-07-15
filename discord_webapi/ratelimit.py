from __future__ import annotations

import time

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
    """

    def __init__(self, max_calls: int, per_seconds: float) -> None:
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
        tokens, last_refill = self._buckets.get(key, (float(self.max_calls), now))
        refill_rate = self.max_calls / self.per_seconds
        tokens = min(self.max_calls, tokens + (now - last_refill) * refill_rate)

        if tokens < 1:
            self._buckets[key] = (tokens, now)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")

        self._buckets[key] = (tokens - 1, now)
