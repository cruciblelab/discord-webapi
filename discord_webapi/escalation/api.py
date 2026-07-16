from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.dashboard_ratelimit_dependency import rate_limit_dependency
from discord_webapi.escalation.engine import EscalationEngine
from discord_webapi.escalation.models import EscalationRule, EscalationRulePatch

_DEFAULT_WRITE_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


def _get_engine(request: Request) -> EscalationEngine:
    engine: EscalationEngine = request.app.state.discord_webapi_escalation_engine
    return engine


def build_escalation_router(*, write_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Dashboard-facing management API for `EscalationEngine` ladders --
    letting a server owner define/edit/remove the rungs ("at N violations
    for `key`, do this") your code checks against with
    `EscalationEngine.record_violation(member, key)`.
    """
    limiter_dep = write_rate_limiter or _DEFAULT_WRITE_LIMITER
    router = APIRouter(prefix="/api/guilds/{guild_id}/escalation-rules", tags=["escalation"])

    @router.get("")
    async def list_all_rules(
        guild_id: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[EscalationRule]:
        return await _get_engine(request).list_all_rules(guild_id)

    @router.get("/{key}")
    async def list_rules_for_key(
        guild_id: int,
        key: str,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[EscalationRule]:
        return await _get_engine(request).list_rules(guild_id, key)

    @router.put("/{key}/{threshold}")
    async def set_rule(
        guild_id: int,
        key: str,
        threshold: int,
        body: EscalationRulePatch,
        request: Request,
        ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter_dep)),
    ) -> EscalationRule:
        return await _get_engine(request).set_rule(
            guild_id,
            key,
            threshold,
            action=body.action,
            action_minutes=body.action_minutes,
            reason=body.reason,
            updated_by_user_id=ctx.user.id,
        )

    @router.delete("/{key}/{threshold}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_rule(
        guild_id: int,
        key: str,
        threshold: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter_dep)),
    ) -> Response:
        await _get_engine(request).delete_rule(guild_id, key, threshold)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
