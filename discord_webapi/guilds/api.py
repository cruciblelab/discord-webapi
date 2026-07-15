from __future__ import annotations

import discord
from fastapi import APIRouter, Depends, Request

from discord_webapi.auth.dependencies import get_current_user
from discord_webapi.auth.models import DiscordUser
from discord_webapi.authz.permissions import has_permission
from discord_webapi.bot.extension import COMMAND_LIST_MANAGEABLE_GUILDS
from discord_webapi.guilds.models import ManageableGuild
from discord_webapi.transport.base import Transport


def _get_transport(request: Request) -> Transport:
    transport: Transport = request.app.state.discord_webapi_transport
    return transport


def build_guilds_router() -> APIRouter:
    """`GET /api/guilds`: which of the logged-in user's own Discord guilds
    (from their session's `guild_ids` -- every server they're a member of,
    not just ones this bot is in) they can actually manage here -- the bot
    is in the guild, and they have "Manage Server" (or administrator)
    there. Lets a consumer build a "pick a server" screen without calling
    any other endpoint first.
    """
    router = APIRouter(prefix="/api/guilds", tags=["guilds"])

    @router.get("")
    async def list_manageable_guilds(
        request: Request,
        user: DiscordUser = Depends(get_current_user),
    ) -> list[ManageableGuild]:
        transport = _get_transport(request)
        response = await transport.request(
            COMMAND_LIST_MANAGEABLE_GUILDS,
            {"guild_ids": user.guild_ids, "user_id": user.id},
        )
        return [
            ManageableGuild(
                guild_id=guild["guild_id"], name=guild["name"], icon_url=guild["icon_url"]
            )
            for guild in response["guilds"]
            if has_permission(discord.Permissions(guild["permissions"]), "manage_guild")
        ]

    return router
