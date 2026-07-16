from __future__ import annotations

import time

from discord_webapi.authz.events import EVENT_TYPE_APP_ROLE_CHANGED, AppRoleChanged
from discord_webapi.authz.models import AppRole
from discord_webapi.storage.base import AuthzStore
from discord_webapi.transport.base import Event, Transport


class AppRoleCache:
    """Web-side cache in front of an `AuthzStore`.

    Unlike `GuildMemberCache` (which must ask the bot process for Discord's
    own Gateway-cached role data via Transport), `AppRole`s are data this
    library owns outright -- any process can read the store directly. A
    short TTL still avoids a store round-trip on every single request;
    a write publishes `app_role_changed` over `Transport` (same pattern as
    `GuildRateLimiter`/`EscalationEngine`/`GuildMemberCache`) so every
    process sharing that Transport -- not just the one that made the
    write -- invalidates its cached copy immediately, instead of a
    revoked-just-now role staying effective on other processes for up to
    `ttl_seconds` (this matters most for exactly the deployment topology
    `for_bot_process`/`for_web_process` support: the bot process enforcing
    `required_app_role` and each web replica enforcing `require_app_role`
    each hold their own independent `AppRoleCache` instance).
    """

    def __init__(
        self, transport: Transport, store: AuthzStore, *, ttl_seconds: float = 30.0
    ) -> None:
        self.transport = transport
        self.store = store
        self.ttl_seconds = ttl_seconds
        self._cache: dict[int, tuple[float, list[AppRole]]] = {}
        transport.subscribe(EVENT_TYPE_APP_ROLE_CHANGED, self._on_app_role_changed)

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
        await self._publish_changed(role.guild_id, role.name)

    async def delete_app_role(self, guild_id: int, name: str) -> None:
        await self.store.delete_app_role(guild_id, name)
        self._cache.pop(guild_id, None)
        await self._publish_changed(guild_id, name)

    async def _publish_changed(self, guild_id: int, name: str) -> None:
        await self.transport.publish(
            Event(
                type=EVENT_TYPE_APP_ROLE_CHANGED,
                payload=AppRoleChanged(guild_id=guild_id, name=name).model_dump(),
            )
        )

    async def _on_app_role_changed(self, event: Event) -> None:
        change = AppRoleChanged.model_validate(event.payload)
        self._cache.pop(change.guild_id, None)
