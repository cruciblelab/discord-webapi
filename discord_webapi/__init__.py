from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
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
from discord_webapi.web import build_default_dashboard_router

if TYPE_CHECKING:
    from discord_webapi.storage.sql import SQLCommandConfigStore, SQLSessionStore
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
    "SQLCommandConfigStore",
    "SQLSessionStore",
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
    if name in ("SQLSessionStore", "SQLCommandConfigStore"):
        from discord_webapi.storage import sql

        return getattr(sql, name)
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

    For the common single-process case, `DiscordWebAPI.quickstart(bot=bot)`
    collapses all of the above (env var reads, SQLite storage, auth,
    transport, the facade itself, the lifespan, and `FastAPI(...)`) into one
    call — see its docstring.
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

    def install(self, app: FastAPI, *, serve_dashboard: bool = True) -> None:
        self.auth.install(app)
        app.state.discord_webapi_member_cache = self.member_cache
        app.state.discord_webapi_commands = self.registry
        app.state.discord_webapi_transport = self.transport
        app.include_router(build_commands_router())
        app.include_router(build_members_router())
        if serve_dashboard:
            app.include_router(build_default_dashboard_router())

    def lifespan(self, token: str) -> AbstractAsyncContextManager[None]:
        return single_process_lifespan(self.bot, self.transport, token)

    @classmethod
    def quickstart(
        cls,
        *,
        bot: commands.Bot,
        bot_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        fernet_key: str | bytes | None = None,
        base_url: str | None = None,
        redirect_uri: str | None = None,
        db_path: str | Path | None = None,
        title: str = "discord-webapi",
        serve_dashboard: bool = True,
    ) -> FastAPI:
        """One-call setup for the single-process case: reads
        `DISCORD_BOT_TOKEN`/`DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`/
        `DWA_FERNET_KEY`/`DASHBOARD_BASE_URL` from the environment for
        whichever of these aren't passed explicitly, wires up
        `InProcessTransport` and SQLite-backed session/command storage at
        `db_path` (default: `dashboard.sqlite3` in the current directory),
        and returns a ready-to-run `FastAPI` app with the lifespan already
        attached -- `uvicorn mymodule:app` is all that's left to do.

        This is sugar for the common case, not a replacement for the
        composable API: construct `DiscordAuth`/`DiscordWebAPI` yourself
        (see the class docstring) for a different transport, a different
        storage backend, or multiple bots.
        """
        from sqlalchemy.ext.asyncio import create_async_engine

        from discord_webapi.storage.sql import (
            SQLCommandConfigStore,
            SQLSessionStore,
        )
        from discord_webapi.storage.sql import (
            create_all as create_all_tables,
        )

        bot_token = bot_token or os.environ["DISCORD_BOT_TOKEN"]
        client_id = client_id or os.environ["DISCORD_CLIENT_ID"]
        client_secret = client_secret or os.environ["DISCORD_CLIENT_SECRET"]
        base_url = base_url or os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")
        redirect_uri = redirect_uri or f"{base_url}/auth/discord/callback"
        key = fernet_key or os.environ["DWA_FERNET_KEY"]
        if isinstance(key, str):
            key = key.encode()

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(db_path) if db_path else 'dashboard.sqlite3'}"
        )
        auth = DiscordAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            encryption_keys=key,
            cookie_secure=base_url.startswith("https://"),
            session_store=SQLSessionStore(engine),
        )
        api = cls(
            bot=bot,
            transport=InProcessTransport(),
            auth=auth,
            command_store=SQLCommandConfigStore(engine),
        )

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            await create_all_tables(engine)
            async with api.lifespan(bot_token):
                yield

        app = FastAPI(title=title, lifespan=lifespan)
        api.install(app, serve_dashboard=serve_dashboard)
        return app
