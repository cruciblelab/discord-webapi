"""FastAPI dependency wrapper around `dashboard_ratelimit.TokenBucketLimiter`,
kept in its own module (separate from `dashboard_ratelimit.py`) purely to
avoid an import cycle: this needs `auth.dependencies.get_current_user`,
and `auth.oauth` itself needs `TokenBucketLimiter` directly (for its own
login-endpoint throttling) -- if this file's `auth` import lived in
`dashboard_ratelimit.py` too, `auth.oauth` importing from it would import
this file, which imports `auth.dependencies`, which imports `auth.oauth`
again, mid-initialization.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends

from discord_webapi.auth.dependencies import get_current_user
from discord_webapi.auth.models import DiscordUser
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter


def rate_limit_dependency(limiter: TokenBucketLimiter) -> Callable[..., Awaitable[None]]:
    """Drop into any state-changing router's `Depends(...)` list, e.g.
    `commands.api`/`ratelimits.api`/`escalation.api`'s PATCH/PUT/DELETE
    endpoints -- keyed by the authenticated user's id.
    """

    async def _dependency(user: DiscordUser = Depends(get_current_user)) -> None:
        limiter.check(str(user.id))

    return _dependency
