from __future__ import annotations

import time

from discord_webapi.authz.models import AppRole
from discord_webapi.storage.base import AuthzStore


class AppRoleCache:
    """Web-side cache in front of an `AuthzStore`.

    Unlike `GuildMemberCache` (which must ask the bot process for Discord's
    own Gateway-cached role data via Transport), `AppRole`s are data this
    library owns outright -- the web process can read the store directly.
    A short TTL still avoids a store round-trip on every single request;
    writes invalidate immediately rather than waiting out the TTL.
    """

    def __init__(self, store: AuthzStore, *, ttl_seconds: float = 30.0) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds
        self._cache: dict[int, tuple[float, list[AppRole]]] = {}

    async def list_roles(self, guild_id: int) -> list[AppRole]:
        now = time.monotonic()
        cached = self._cache.get(guild_id)
        if cached is not None and now - cached[0] < self.ttl_seconds:
            return cached[1]

        roles = await self.store.get_all_app_roles(guild_id)
        self._cache[guild_id] = (now, roles)
        return roles

    async def user_has_role(
        self, guild_id: int, role_name: str, *, user_id: int, discord_role_ids: list[int]
    ) -> bool:
        for role in await self.list_roles(guild_id):
            if role.name != role_name:
                continue
            if user_id in role.user_ids:
                return True
            if any(role_id in role.discord_role_ids for role_id in discord_role_ids):
                return True
        return False

    async def set_app_role(self, role: AppRole) -> None:
        await self.store.set_app_role(role)
        self._cache.pop(role.guild_id, None)

    async def delete_app_role(self, guild_id: int, name: str) -> None:
        await self.store.delete_app_role(guild_id, name)
        self._cache.pop(guild_id, None)
