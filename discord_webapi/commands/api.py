from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from discord_webapi.audit.logger import AuditLogger
from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.commands.models import CommandOverridePatch, CommandStatus
from discord_webapi.commands.ratelimit import TokenBucketLimiter, rate_limit_dependency
from discord_webapi.commands.registry import (
    COMMAND_LIST_COMMAND_STATUS,
    COMMAND_SET_COMMAND_OVERRIDE,
)
from discord_webapi.transport.base import Transport

_DEFAULT_PATCH_LIMITER = TokenBucketLimiter(max_calls=20, per_seconds=60.0)


def _get_transport(request: Request) -> Transport:
    transport: Transport = request.app.state.discord_webapi_transport
    return transport


def _get_audit_logger(request: Request) -> AuditLogger | None:
    # Only present when enable_audit_log=True -- see DiscordWebAPI.install.
    return getattr(request.app.state, "discord_webapi_audit_logger", None)


def build_commands_router(*, patch_rate_limiter: TokenBucketLimiter | None = None) -> APIRouter:
    """Dashboard-facing command management API.

    Both reads and writes go through Transport RPC to whichever process
    owns the live `CommandRegistry` (see
    `commands.registry.install_command_registry_bridge`) -- this is what
    lets this router run in a web process with no `CommandRegistry`
    object of its own (e.g. `DiscordWebAPI.for_web_process`, a separate
    process/replica from the bot, talking over `RedisTransport`) as well
    as the default single-process deployment (`InProcessTransport`, where
    the RPC call loops back in-memory to the same object).
    """
    limiter = patch_rate_limiter or _DEFAULT_PATCH_LIMITER
    router = APIRouter(prefix="/api/guilds/{guild_id}/commands", tags=["commands"])

    @router.get("")
    async def list_commands(
        guild_id: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[CommandStatus]:
        response = await _get_transport(request).request(
            COMMAND_LIST_COMMAND_STATUS, {"guild_id": guild_id}
        )
        return [CommandStatus.model_validate(s) for s in response["statuses"]]

    @router.patch("/{command_name}")
    async def update_command(
        guild_id: int,
        command_name: str,
        body: CommandOverridePatch,
        request: Request,
        ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
        _rate_limited: None = Depends(rate_limit_dependency(limiter)),
    ) -> CommandStatus:
        response = await _get_transport(request).request(
            COMMAND_SET_COMMAND_OVERRIDE,
            {
                "guild_id": guild_id,
                "command_name": command_name,
                "enabled": body.enabled,
                "cooldown_seconds": body.cooldown_seconds,
                "cooldown_uses": body.cooldown_uses,
                "updated_by_user_id": ctx.user.id,
            },
        )
        if "error" in response:
            raise HTTPException(status.HTTP_404_NOT_FOUND, response["error"])
        status_result = CommandStatus.model_validate(response["status"])

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
