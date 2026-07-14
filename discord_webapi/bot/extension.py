from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import discord
from discord.ext import commands

from discord_webapi.authz.cache import COMMAND_GET_MEMBER, EVENT_TYPE_MEMBER_UPDATED
from discord_webapi.commands.bridge import get_member_permissions, get_member_roles
from discord_webapi.transport.base import Event, Transport


def install_member_lookup(bot: commands.Bot, transport: Transport) -> None:
    """Bot-process wiring for `authz.GuildMemberCache`: answers `get_member`
    RPC requests from the bot's own warm Gateway cache (never a REST call),
    and publishes `member_updated` whenever that cache changes so the
    web-side cache invalidates instead of going stale.

    Uses `bot.add_listener` rather than `@bot.event` so it never clobbers an
    `on_member_update`/`on_member_remove` handler the bot author already
    defined elsewhere — discord.py supports many listeners per event only
    through `add_listener`, not through `@bot.event`.
    """

    async def handle_get_member(payload: dict[str, Any]) -> dict[str, Any]:
        guild_id, user_id = payload["guild_id"], payload["user_id"]
        role_ids = get_member_roles(bot, guild_id, user_id)
        permissions = get_member_permissions(bot, guild_id, user_id)
        if role_ids is None or permissions is None:
            return {"found": False}
        return {"found": True, "role_ids": role_ids, "permissions": permissions.value}

    transport.register_handler(COMMAND_GET_MEMBER, handle_get_member)

    async def on_member_update(before: discord.Member, after: discord.Member) -> None:
        if before.roles != after.roles:
            await transport.publish(
                Event(
                    type=EVENT_TYPE_MEMBER_UPDATED,
                    payload={"guild_id": after.guild.id, "user_id": after.id},
                )
            )

    async def on_member_remove(member: discord.Member) -> None:
        await transport.publish(
            Event(
                type=EVENT_TYPE_MEMBER_UPDATED,
                payload={"guild_id": member.guild.id, "user_id": member.id},
            )
        )

    bot.add_listener(on_member_update, name="on_member_update")
    bot.add_listener(on_member_remove, name="on_member_remove")


@asynccontextmanager
async def single_process_lifespan(
    bot: commands.Bot, transport: Transport, token: str
) -> AsyncIterator[None]:
    """FastAPI lifespan context for the v0.1 default deployment shape: bot
    and web share one process and one asyncio event loop. Starts the bot as
    a background task, waits for its Gateway cache to warm up
    (`wait_until_ready`) before yielding so routes never see empty guild
    data, and tears both down cleanly on shutdown.
    """
    await transport.start()
    bot_task = asyncio.create_task(bot.start(token))
    await bot.wait_until_ready()
    try:
        yield
    finally:
        await bot.close()
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task
        await transport.stop()
