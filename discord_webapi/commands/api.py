from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from discord_webapi.audit.logger import AuditLogger
from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.commands.models import CommandOverridePatch, CommandStatus
from discord_webapi.commands.ratelimit import TokenBucketLimiter, rate_limit_dependency
from discord_webapi.commands.registry import CommandRegistry

_DEFAULT_PATCH_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


def _get_registry(request: Request) -> CommandRegistry:
    registry: CommandRegistry = request.app.state.discord_webapi_commands
    return registry


def _get_audit_logger(request: Request) -> AuditLogger | None:
    # Only present when enable_audit_log=True -- see DiscordWebAPI.install.
    return getattr(request.app.state, "discord_webapi_audit_logger", None)


def build_commands_router(*, patch_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Dashboard-facing command management API.

    Reads always come straight from the in-memory `CommandRegistry` (which
    is itself kept warm by Transport events, see `registry.py`) — the write
    path is web -> `CommandConfigStore` -> `command_config_changed` event,
    never a direct call into the bot process.
    """
    limiter = patch_rate_limiter or _DEFAULT_PATCH_LIMITER
    router = APIRouter(prefix="/api/guilds/{guild_id}/commands", tags=["commands"])

    @router.get("")
    async def list_commands(
        guild_id: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[CommandStatus]:
        return _get_registry(request).list_status(guild_id)

    @router.patch("/{command_name}")
    async def update_command(
        guild_id: int,
        command_name: str,
        body: CommandOverridePatch,
        request: Request,
        ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter)),
    ) -> CommandStatus:
        registry = _get_registry(request)
        try:
            status_result = await registry.set_override(
                guild_id,
                command_name,
                enabled=body.enabled,
                cooldown_seconds=body.cooldown_seconds,
                cooldown_uses=body.cooldown_uses,
                updated_by_user_id=ctx.user.id,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

        audit = _get_audit_logger(request)
        if audit is not None:
            await audit.record(
                guild_id=guild_id,
                actor_user_id=ctx.user.id,
                action="command.set_override",
                target=command_name,
                detail=body.model_dump(),
            )
        return status_result

    return router
