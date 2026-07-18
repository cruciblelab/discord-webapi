from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import discord

from discord_webapi.authz.cache import (
    COMMAND_GET_CHANNEL_PERMISSIONS,
    COMMAND_GET_MEMBER,
    EVENT_TYPE_MEMBER_UPDATED,
)
from discord_webapi.bot.types import AnyBot
from discord_webapi.commands.bridge import (
    get_channel_permissions,
    get_member_permissions,
    get_member_roles,
    list_manageable_guilds,
)
from discord_webapi.transport.base import Event, Transport

COMMAND_LIST_MANAGEABLE_GUILDS = "list_manageable_guilds"


def default_intents() -> discord.Intents:
    """`Intents.default()` plus `members=True` and `message_content=True` --
    almost every dashboard bot needs the member cache (see
    `authz.GuildMemberCache` and `members.install_member_listing`), and
    prefix/hybrid commands (`!ping`) silently never fire without
    `message_content` (discord.py can't read a message's text to match it
    against `command_prefix` otherwise -- slash-only commands don't need
    it, but this saves you from that trap the moment you add a prefix
    command). Also remember to enable both the "Server Members Intent" and
    "Message Content Intent" toggles for the bot in the Discord Developer
    Portal -- this call alone isn't enough, Discord enforces both
    server-side too.
    """
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    return intents


def install_member_lookup(bot: AnyBot, transport: Transport) -> None:
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


def install_channel_permission_lookup(bot: AnyBot, transport: Transport) -> None:
    """Bot-process wiring for `authz.ChannelPermissionCache`: answers
    `get_channel_permissions` RPC requests from the bot's own warm Gateway
    cache (never a REST call) -- see `commands.bridge.get_channel_permissions`
    for what "effective permissions" means here (role permissions folded
    together with the channel's own overwrites).
    """

    async def handle_get_channel_permissions(payload: dict[str, Any]) -> dict[str, Any]:
        guild_id, channel_id, user_id = (
            payload["guild_id"],
            payload["channel_id"],
            payload["user_id"],
        )
        permissions = get_channel_permissions(bot, guild_id, channel_id, user_id)
        if permissions is None:
            return {"found": False}
        return {"found": True, "permissions": permissions.value}

    transport.register_handler(COMMAND_GET_CHANNEL_PERMISSIONS, handle_get_channel_permissions)


def install_guild_listing(bot: AnyBot, transport: Transport) -> None:
    """Bot-process wiring for `GET /api/guilds`: answers
    `list_manageable_guilds` RPC requests from the bot's own warm Gateway
    cache -- see `commands.bridge.list_manageable_guilds`.
    """

    async def handle_list_manageable_guilds(payload: dict[str, Any]) -> dict[str, Any]:
        guilds = list_manageable_guilds(bot, payload["guild_ids"], payload["user_id"])
        return {"guilds": guilds}

    transport.register_handler(COMMAND_LIST_MANAGEABLE_GUILDS, handle_list_manageable_guilds)


@asynccontextmanager
async def single_process_lifespan(
    bot: AnyBot, transport: Transport, token: str
) -> AsyncIterator[None]:
    """FastAPI lifespan context for the v0.1 default deployment shape: bot
    and web share one process and one asyncio event loop. Starts the bot as
    a background task, waits for its Gateway cache to warm up
    (`wait_until_ready`) before yielding so routes never see empty guild
    data, and tears both down cleanly on shutdown.
    """
    await transport.start()
    bot_task = asyncio.create_task(bot.start(token))
    ready_task = asyncio.create_task(bot.wait_until_ready())

    done, pending = await asyncio.wait(
        {bot_task, ready_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if ready_task not in done:
        # bot_task ended (crashed, e.g. bad token or missing privileged
        # intents) before the bot ever became ready. wait_until_ready()'s
        # own error in that case is a confusing, unrelated-looking
        # RuntimeError -- surface the real cause from bot_task instead.
        ready_task.cancel()
        exc = bot_task.exception()
        if exc is not None:
            raise exc
        raise RuntimeError("Bot process exited before becoming ready")

    try:
        yield
    finally:
        await bot.close()
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task
        await transport.stop()


@asynccontextmanager
async def web_only_lifespan(transport: Transport) -> AsyncIterator[None]:
    """FastAPI lifespan for a web-only process in a split bot/web
    deployment (see `DiscordWebAPI.for_web_process`) -- no discord.py bot
    here at all. Just starts/stops this process's own connection to the
    shared Transport (e.g. RedisTransport's Redis connection) around the
    app's lifetime; the bot itself runs in a separate process started via
    `run_bot_process`/`DiscordWebAPI.for_bot_process`.
    """
    await transport.start()
    try:
        yield
    finally:
        await transport.stop()


async def run_bot_process(bot: AnyBot, transport: Transport, token: str) -> None:
    """Entry point for a standalone bot-only process in a split bot/web
    deployment: connects to Discord and to the shared Transport (typically
    `RedisTransport`, so it can be reached by any number of separate
    `for_web_process` FastAPI replicas/machines), then blocks until
    interrupted (Ctrl+C / SIGINT/SIGTERM cancels the enclosing
    `asyncio.run`). No FastAPI involved at all -- run exactly one of these
    per bot account/token.
    """
    async with single_process_lifespan(bot, transport, token):
        await asyncio.Event().wait()
