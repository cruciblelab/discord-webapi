from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from discord_webapi.audit.logger import AuditLogger
from discord_webapi.authz.app_roles import AppRoleCache
from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.authz.models import AppRole, AppRolePatch
from discord_webapi.dashboard_ratelimit import TokenBucketLimiter
from discord_webapi.dashboard_ratelimit_dependency import rate_limit_dependency

_DEFAULT_WRITE_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


def _get_app_role_cache(request: Request) -> AppRoleCache:
    cache: AppRoleCache = request.app.state.discord_webapi_app_role_cache
    return cache


def _get_audit_logger(request: Request) -> AuditLogger | None:
    # Only present when enable_audit_log=True -- see DiscordWebAPI.install.
    return getattr(request.app.state, "discord_webapi_audit_logger", None)


def build_app_roles_router(*, write_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Dashboard-facing management API for `AppRole`s -- managing who counts
    as e.g. "moderator" at the application level, independent of Discord's
    own roles. Gated the same way as the commands API: requires
    "Manage Server" in the target guild.
    """
    limiter = write_rate_limiter or _DEFAULT_WRITE_LIMITER
    router = APIRouter(prefix="/api/guilds/{guild_id}/app-roles", tags=["app-roles"])

    @router.get("")
    async def list_app_roles(
        guild_id: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[AppRole]:
        return await _get_app_role_cache(request).list_roles(guild_id)

    @router.put("/{name}")
    async def set_app_role(
        guild_id: int,
        name: str,
        body: AppRolePatch,
        request: Request,
        ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter)),
    ) -> AppRole:
        role = AppRole(
            guild_id=guild_id,
            name=name,
            discord_role_ids=body.discord_role_ids,
            user_ids=body.user_ids,
        )
        await _get_app_role_cache(request).set_app_role(role)

        audit = _get_audit_logger(request)
        if audit is not None:
            await audit.record(
                guild_id=guild_id,
                actor_user_id=ctx.user.id,
                action="app_role.set",
                target=name,
                detail=body.model_dump(),
            )
        return role

    @router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_app_role(
        guild_id: int,
        name: str,
        request: Request,
        ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter)),
    ) -> Response:
        await _get_app_role_cache(request).delete_app_role(guild_id, name)

        audit = _get_audit_logger(request)
        if audit is not None:
            await audit.record(
                guild_id=guild_id, actor_user_id=ctx.user.id, action="app_role.delete", target=name
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
