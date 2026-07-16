from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.dashboard_ratelimit_dependency import rate_limit_dependency
from discord_webapi.ratelimits.limiter import GuildRateLimiter
from discord_webapi.ratelimits.models import RateLimitRule, RateLimitRulePatch

_DEFAULT_WRITE_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


def _get_limiter(request: Request) -> GuildRateLimiter:
    limiter: GuildRateLimiter = request.app.state.discord_webapi_ratelimiter
    return limiter


def build_ratelimits_router(*, write_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Dashboard-facing management API for `GuildRateLimiter` rules --
    letting a server owner tune (or reset back to the library/bot's own
    default) the threshold for any `key` your code checks against with
    `GuildRateLimiter.check(guild_id, key)`, not just discord.py commands.
    """
    limiter_dep = write_rate_limiter or _DEFAULT_WRITE_LIMITER
    router = APIRouter(prefix="/api/guilds/{guild_id}/ratelimits", tags=["ratelimits"])

    @router.get("")
    async def list_rules(
        guild_id: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[RateLimitRule]:
        return await _get_limiter(request).list_rules(guild_id)

    @router.put("/{key}")
    async def set_rule(
        guild_id: int,
        key: str,
        body: RateLimitRulePatch,
        request: Request,
        ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter_dep)),
    ) -> RateLimitRule:
        return await _get_limiter(request).set_rule(
            guild_id,
            key,
            max_calls=body.max_calls,
            per_seconds=body.per_seconds,
            updated_by_user_id=ctx.user.id,
        )

    @router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_rule(
        guild_id: int,
        key: str,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter_dep)),
    ) -> Response:
        await _get_limiter(request).delete_rule(guild_id, key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
