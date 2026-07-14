from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from discord.ext import commands
from fastapi import FastAPI

from discord_webapi.auth import DiscordAuth, DiscordUser, get_current_user
from discord_webapi.authz import (
    GuildContext,
    GuildMemberCache,
    require_guild_permission,
    require_role,
)
from discord_webapi.bot.extension import install_member_lookup, single_process_lifespan
from discord_webapi.commands import (
    CommandOverride,
    CommandRegistry,
    CommandSpec,
    CommandStatus,
    build_commands_router,
)
from discord_webapi.members import MemberInfo, build_members_router, install_member_listing
from discord_webapi.storage import CommandConfigStore, MemoryCommandConfigStore
from discord_webapi.transport import Event, InProcessTransport, Transport

if TYPE_CHECKING:
    from discord_webapi.transport.redis import RedisTransport

__all__ = [
    "CommandConfigStore",
    "CommandOverride",
    "CommandRegistry",
    "CommandSpec",
    "CommandStatus",
    "DiscordAuth",
    "DiscordUser",
    "DiscordWebAPI",
    "Event",
    "GuildContext",
    "GuildMemberCache",
    "InProcessTransport",
    "MemberInfo",
    "MemoryCommandConfigStore",
    "RedisTransport",
    "Transport",
    "build_commands_router",
    "build_members_router",
    "get_current_user",
    "require_guild_permission",
    "require_role",
]


def __getattr__(name: str) -> object:
    if name == "RedisTransport":
        from discord_webapi.transport.redis import RedisTransport

        return RedisTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class DiscordWebAPI:
    """Top-level facade wiring auth, authz, the command registry, and
    transport together. Mirrors discord.py's own layered API — this is
    ergonomic sugar over pieces that remain usable individually for
    power users who need to wire them by hand.

    ```python
    api = DiscordWebAPI(bot=bot, transport=InProcessTransport(), auth=auth)
    api.install(app)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with api.lifespan(DISCORD_BOT_TOKEN):
            yield

    app = FastAPI(lifespan=lifespan)
    ```
    """

    def __init__(
        self,
        *,
        bot: commands.Bot,
        transport: Transport,
        auth: DiscordAuth,
        command_store: CommandConfigStore | None = None,
        member_cache_ttl_seconds: float = 45.0,
    ) -> None:
        self.bot = bot
        self.transport = transport
        self.auth = auth
        self.command_store = command_store or MemoryCommandConfigStore()
        self.registry = CommandRegistry(bot, transport=transport, store=self.command_store)
        self.member_cache = GuildMemberCache(transport, ttl_seconds=member_cache_ttl_seconds)

        install_member_lookup(bot, transport)
        install_member_listing(bot, transport)
        bot.add_listener(self._on_ready, name="on_ready")

    async def _on_ready(self) -> None:
        await self.registry.register_all()

    def install(self, app: FastAPI) -> None:
        self.auth.install(app)
        app.state.discord_webapi_member_cache = self.member_cache
        app.state.discord_webapi_commands = self.registry
        app.state.discord_webapi_transport = self.transport
        app.include_router(build_commands_router())
        app.include_router(build_members_router())

    def lifespan(self, token: str) -> AbstractAsyncContextManager[None]:
        return single_process_lifespan(self.bot, self.transport, token)
