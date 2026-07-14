from __future__ import annotations

import time
from dataclasses import dataclass

import discord

from discord_webapi.transport.base import Event, Transport

EVENT_TYPE_MEMBER_UPDATED = "member_updated"
COMMAND_GET_MEMBER = "get_member"


@dataclass
class GuildMemberInfo:
    role_ids: list[int]
    permissions: discord.Permissions


class GuildMemberCache:
    """Web-side cache in front of a Transport RPC call to the bot process.

    The web process never calls Discord's REST API to answer "is this user
    a member of this guild with these roles" — it asks the bot process
    (which answers from its already-resident Gateway cache, no rate limit)
    and caches the result briefly to absorb request bursts. The bot
    publishes `member_updated` when its own Gateway cache changes, which
    invalidates the corresponding cache entry here.
    """

    def __init__(self, transport: Transport, *, ttl_seconds: float = 45.0) -> None:
        self.transport = transport
        self.ttl_seconds = ttl_seconds
        self._cache: dict[tuple[int, int], tuple[float, GuildMemberInfo]] = {}
        self.transport.subscribe(EVENT_TYPE_MEMBER_UPDATED, self._on_member_updated)

    async def get(self, guild_id: int, user_id: int) -> GuildMemberInfo | None:
        key = (guild_id, user_id)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self.ttl_seconds:
            return cached[1]

        response = await self.transport.request(
            COMMAND_GET_MEMBER, {"guild_id": guild_id, "user_id": user_id}
        )
        if not response.get("found"):
            self._cache.pop(key, None)
            return None

        info = GuildMemberInfo(
            role_ids=response["role_ids"],
            permissions=discord.Permissions(response["permissions"]),
        )
        self._cache[key] = (now, info)
        return info

    async def _on_member_updated(self, event: Event) -> None:
        guild_id = event.payload.get("guild_id")
        user_id = event.payload.get("user_id")
        if guild_id is not None and user_id is not None:
            self._cache.pop((guild_id, user_id), None)
