from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends

from discord_webapi.auth.dependencies import get_current_user
from discord_webapi.auth.models import DiscordUser
from discord_webapi.ratelimit import TokenBucketLimiter

__all__ = ["TokenBucketLimiter", "rate_limit_dependency"]


def rate_limit_dependency(limiter: TokenBucketLimiter) -> Callable[..., Awaitable[None]]:
    async def _dependency(user: DiscordUser = Depends(get_current_user)) -> None:
        limiter.check(str(user.id))

    return _dependency
