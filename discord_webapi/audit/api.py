from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from discord_webapi.audit.models import AuditLogEntry
from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.storage.base import AuditStore


def _get_audit_store(request: Request) -> AuditStore:
    store: AuditStore = request.app.state.discord_webapi_audit_store
    return store


def build_audit_log_router() -> APIRouter:
    """Read-only dashboard API for the audit trail. Only mounted when
    `enable_audit_log=True` — see `DiscordWebAPI.install`."""
    router = APIRouter(prefix="/api/guilds/{guild_id}/audit-log", tags=["audit-log"])

    @router.get("")
    async def list_audit_log(
        guild_id: int,
        request: Request,
        limit: int = 100,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[AuditLogEntry]:
        return await _get_audit_store(request).list_entries(guild_id, limit=limit)

    return router
