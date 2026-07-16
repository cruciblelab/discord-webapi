import pytest
from fastapi import HTTPException

from discord_webapi.dashboard_ratelimit import TokenBucketLimiter


def test_check_allows_up_to_max_calls_then_raises() -> None:
    limiter = TokenBucketLimiter(2, 60.0)

    limiter.check("user-1")
    limiter.check("user-1")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("user-1")
    assert exc_info.value.status_code == 429


def test_bucket_count_never_exceeds_max_tracked_keys() -> None:
    limiter = TokenBucketLimiter(5, 60.0, max_tracked_keys=10)

    for i in range(100):
        limiter.check(f"user-{i}")

    assert len(limiter._buckets) <= 10


def test_evicted_key_is_treated_as_a_fresh_bucket() -> None:
    """Evicting a stale entry must be harmless -- the key just comes back
    with a full bucket next time, same as any never-seen-before key."""
    limiter = TokenBucketLimiter(1, 60.0, max_tracked_keys=1)

    limiter.check("user-a")  # fills the only slot
    limiter.check("user-b")  # evicts user-a's entry (LRU)

    # user-a was evicted while its bucket still had 0 tokens left -- but
    # since eviction just means "forget this key ever existed", it comes
    # back with a full bucket rather than staying rate-limited forever.
    limiter.check("user-a")  # must not raise
