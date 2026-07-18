"""Guild member listing: view members and their roles on a dashboard.

Separate from `commands.bridge` because it reads only stable, long-standing
discord.py public APIs (`guild.members`, `member.roles`, `member.display_avatar`)
rather than the Parameter/annotation internals that module isolates against —
this doesn't need the same version-fragility guard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from discord_webapi.authz.dependencies import GuildContext, require_guild_permission
from discord_webapi.bot.types import AnyBot
from discord_webapi.transport.base import Transport

COMMAND_LIST_MEMBERS = "list_members"


class MemberInfo(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: str | None
    role_ids: list[int]
    role_names: list[str]
    joined_at: str | None


def install_member_listing(bot: AnyBot, transport: Transport) -> None:
    """Bot-process wiring: answers `list_members` RPC requests from the
    bot's warm Gateway cache (never a REST call) — mirrors
    `bot.extension.install_member_lookup`'s single-member lookup, but for
    the whole guild roster at once."""

    async def handle_list_members(payload: dict[str, Any]) -> dict[str, Any]:
        guild = bot.get_guild(payload["guild_id"])
        if guild is None:
            return {"found": False, "members": []}

        members = [
            {
                "id": member.id,
                "username": str(member),
                "display_name": member.display_name,
                "avatar_url": member.display_avatar.url if member.display_avatar else None,
                "role_ids": [role.id for role in member.roles if not role.is_default()],
                "role_names": [role.name for role in member.roles if not role.is_default()],
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            }
            for member in guild.members
        ]
        return {"found": True, "members": members}

    transport.register_handler(COMMAND_LIST_MEMBERS, handle_list_members)


def build_members_router() -> APIRouter:
    router = APIRouter(prefix="/api/guilds/{guild_id}/members", tags=["members"])

    @router.get("")
    async def list_members(
        guild_id: int,
        request: Request,
        _ctx: GuildContext = Depends(require_guild_permission("manage_guild")),
    ) -> list[MemberInfo]:
        transport: Transport = request.app.state.discord_webapi_transport
        response = await transport.request(COMMAND_LIST_MEMBERS, {"guild_id": guild_id})
        if not response.get("found"):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Guild not found, or the bot isn't a member of it"
            )
        return [MemberInfo(**member) for member in response["members"]]

    return router
