from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from fastapi import FastAPI

from discord_webapi.audit import AuditLogger, build_audit_log_router
from discord_webapi.auth import DiscordAuth, DiscordUser, get_current_user
from discord_webapi.authz import (
    AppRole,
    AppRoleCache,
    AppRolePatch,
    ChannelContext,
    ChannelPermissionCache,
    GuildContext,
    GuildMemberCache,
    build_app_roles_router,
    require_app_role,
    require_channel_permission,
    require_guild_permission,
    require_role,
)
from discord_webapi.bot.extension import (
    install_channel_permission_lookup,
    install_member_lookup,
    single_process_lifespan,
)
from discord_webapi.commands import (
    CommandOverride,
    CommandRegistry,
    CommandSpec,
    CommandStatus,
    build_commands_router,
)
from discord_webapi.consent import ConsentRecord, build_consent_router
from discord_webapi.members import MemberInfo, build_members_router, install_member_listing
from discord_webapi.storage import (
    AuditStore,
    AuthzStore,
    CommandConfigStore,
    ConsentStore,
    MemoryAuditStore,
    MemoryAuthzStore,
    MemoryCommandConfigStore,
    MemoryConsentStore,
)
from discord_webapi.transport import Event, InProcessTransport, Transport
from discord_webapi.web import (
    DEFAULT_COOKIE_CONSENT_MESSAGE,
    DEFAULT_COOKIE_CONSENT_VERSION,
    build_commands_websocket_router,
    build_default_dashboard_router,
)

if TYPE_CHECKING:
    from discord_webapi.storage.sql import (
        SQLAuditStore,
        SQLAuthzStore,
        SQLCommandConfigStore,
        SQLConsentStore,
        SQLSessionStore,
    )
    from discord_webapi.transport.redis import RedisTransport

__all__ = [
    "AppRole",
    "AppRoleCache",
    "AppRolePatch",
    "AuditLogger",
    "AuditStore",
    "AuthzStore",
    "ChannelContext",
    "ChannelPermissionCache",
    "CommandConfigStore",
    "CommandOverride",
    "CommandRegistry",
    "CommandSpec",
    "CommandStatus",
    "ConsentRecord",
    "ConsentStore",
    "DiscordAuth",
    "DiscordUser",
    "DiscordWebAPI",
    "Event",
    "GuildContext",
    "GuildMemberCache",
    "InProcessTransport",
    "MemberInfo",
    "MemoryAuditStore",
    "MemoryAuthzStore",
    "MemoryCommandConfigStore",
    "MemoryConsentStore",
    "RedisTransport",
    "SQLAuditStore",
    "SQLAuthzStore",
    "SQLCommandConfigStore",
    "SQLConsentStore",
    "SQLSessionStore",
    "Transport",
    "build_app_roles_router",
    "build_audit_log_router",
    "build_commands_router",
    "build_consent_router",
    "build_members_router",
    "get_current_user",
    "require_app_role",
    "require_channel_permission",
    "require_guild_permission",
    "require_role",
]


def __getattr__(name: str) -> object:
    if name == "RedisTransport":
        from discord_webapi.transport.redis import RedisTransport

        return RedisTransport
    if name in (
        "SQLSessionStore",
        "SQLCommandConfigStore",
        "SQLAuthzStore",
        "SQLAuditStore",
        "SQLConsentStore",
    ):
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
        authz_store: AuthzStore | None = None,
        audit_store: AuditStore | None = None,
        consent_store: ConsentStore | None = None,
        member_cache_ttl_seconds: float = 45.0,
        channel_permission_cache_ttl_seconds: float = 30.0,
        sync_commands: bool = True,
        sync_guild_id: int | None = None,
    ) -> None:
        self.bot = bot
        self.transport = transport
        self.auth = auth
        self._sync_commands = sync_commands
        self._sync_guild_id = sync_guild_id
        self._commands_synced = False
        self.command_store = command_store or MemoryCommandConfigStore()
        self.authz_store = authz_store or MemoryAuthzStore()
        self.audit_store = audit_store or MemoryAuditStore()
        self.consent_store = consent_store or MemoryConsentStore()
        self.registry = CommandRegistry(bot, transport=transport, store=self.command_store)
        self.member_cache = GuildMemberCache(transport, ttl_seconds=member_cache_ttl_seconds)
        self.channel_permission_cache = ChannelPermissionCache(
            transport, ttl_seconds=channel_permission_cache_ttl_seconds
        )
        self.app_role_cache = AppRoleCache(self.authz_store)

        install_member_lookup(bot, transport)
        install_channel_permission_lookup(bot, transport)
        install_member_listing(bot, transport)
        bot.add_listener(self._on_ready, name="on_ready")

    async def _on_ready(self) -> None:
        await self.registry.register_all()
        if self._sync_commands and not self._commands_synced:
            # discord.py never pushes slash commands to Discord on its own
            # -- without this, /commands you define never show up in
            # Discord's own UI at all, silently. Guarded so a Gateway
            # reconnect (on_ready can fire more than once) doesn't re-sync
            # every time.
            if self._sync_guild_id is not None:
                guild = discord.Object(id=self._sync_guild_id)
                self.bot.tree.copy_global_to(guild=guild)
                await self.bot.tree.sync(guild=guild)
            else:
                await self.bot.tree.sync()
            self._commands_synced = True

    def install(
        self,
        app: FastAPI,
        *,
        serve_dashboard: bool = True,
        enable_websocket: bool = False,
        enable_audit_log: bool = False,
        enable_cookie_consent: bool = False,
        cookie_consent_message: str = DEFAULT_COOKIE_CONSENT_MESSAGE,
        cookie_consent_version: str = DEFAULT_COOKIE_CONSENT_VERSION,
    ) -> None:
        self.auth.install(app)
        app.state.discord_webapi_member_cache = self.member_cache
        app.state.discord_webapi_channel_permission_cache = self.channel_permission_cache
        app.state.discord_webapi_commands = self.registry
        app.state.discord_webapi_transport = self.transport
        app.state.discord_webapi_app_role_cache = self.app_role_cache
        app.include_router(build_commands_router())
        app.include_router(build_members_router())
        app.include_router(build_app_roles_router())
        if serve_dashboard:
            app.include_router(
                build_default_dashboard_router(
                    enable_cookie_consent=enable_cookie_consent,
                    cookie_consent_message=cookie_consent_message,
                    cookie_consent_version=cookie_consent_version,
                )
            )
        if enable_websocket:
            app.include_router(build_commands_websocket_router(self.transport))
        if enable_audit_log:
            app.state.discord_webapi_audit_store = self.audit_store
            app.state.discord_webapi_audit_logger = AuditLogger(self.audit_store)
            app.include_router(build_audit_log_router())
        if enable_cookie_consent:
            app.state.discord_webapi_consent_store = self.consent_store
            app.include_router(build_consent_router())

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
        mobile_redirect_uri: str | None = None,
        db_path: str | Path | None = None,
        database_url: str | None = None,
        title: str = "discord-webapi",
        serve_dashboard: bool = True,
        enable_websocket: bool = False,
        enable_audit_log: bool = False,
        enable_cookie_consent: bool = False,
        cookie_consent_message: str = DEFAULT_COOKIE_CONSENT_MESSAGE,
        cookie_consent_version: str = DEFAULT_COOKIE_CONSENT_VERSION,
        sync_commands: bool = True,
        sync_guild_id: int | None = None,
    ) -> FastAPI:
        """One-call setup for the single-process case: reads
        `DISCORD_BOT_TOKEN`/`DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`/
        `DWA_FERNET_KEY`/`DASHBOARD_BASE_URL` from the environment for
        whichever of these aren't passed explicitly, wires up
        `InProcessTransport` and SQL-backed session/command/authz storage,
        and returns a ready-to-run `FastAPI` app with the lifespan already
        attached -- `uvicorn mymodule:app` is all that's left to do.

        Storage defaults to a local SQLite file at `db_path` (default:
        `dashboard.sqlite3` in the current directory) -- zero setup, fine
        for a single instance. Pass `database_url` (or set `DATABASE_URL`),
        e.g. `"postgresql+asyncpg://user:pass@host/db"` or
        `"mysql+aiomysql://user:pass@host/db"`, to point at Postgres/MySQL
        instead; `discord_webapi.storage.sql` doesn't care which -- install
        the matching extra (`discord-webapi[sql-postgres]` /
        `[sql-mysql]` / `[sql-sqlite]`) for the DBAPI driver.

        This is sugar for the common case, not a replacement for the
        composable API: construct `DiscordAuth`/`DiscordWebAPI` yourself
        (see the class docstring) for a different transport, a different
        storage backend, or multiple bots.

        `mobile_redirect_uri`, if set, enables `/auth/discord/login?mobile=true`
        (see `DiscordAuth`'s docstring) -- useful for testing without ever
        having to read a cookie out of a browser: after completing the
        Discord login, the browser lands on `mobile_redirect_uri` with
        `session_id` right there in the URL's query string to copy, which
        you then send as `Authorization: Bearer <session_id>` on every
        request instead of a cookie.

        `sync_commands=True` (the default) pushes your slash commands to
        Discord once the bot is ready -- discord.py never does this on its
        own, so without it your `/commands` silently never appear in
        Discord's UI at all. Global sync (`sync_guild_id=None`) can take
        up to an hour to propagate everywhere; pass your test server's
        guild ID as `sync_guild_id` while developing for near-instant
        propagation to just that one guild instead.
        """
        from sqlalchemy.ext.asyncio import create_async_engine

        from discord_webapi.storage.sql import (
            SQLAuditStore,
            SQLAuthzStore,
            SQLCommandConfigStore,
            SQLConsentStore,
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

        database_url = database_url or os.environ.get("DATABASE_URL")
        if not database_url:
            sqlite_path = Path(db_path) if db_path else Path("dashboard.sqlite3")
            database_url = f"sqlite+aiosqlite:///{sqlite_path}"
        engine = create_async_engine(database_url)
        auth = DiscordAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            encryption_keys=key,
            cookie_secure=base_url.startswith("https://"),
            session_store=SQLSessionStore(engine),
            mobile_redirect_uri=mobile_redirect_uri,
        )
        api = cls(
            bot=bot,
            transport=InProcessTransport(),
            auth=auth,
            command_store=SQLCommandConfigStore(engine),
            authz_store=SQLAuthzStore(engine),
            audit_store=SQLAuditStore(engine),
            consent_store=SQLConsentStore(engine),
            sync_commands=sync_commands,
            sync_guild_id=sync_guild_id,
        )

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            await create_all_tables(engine)
            async with api.lifespan(bot_token):
                yield

        app = FastAPI(title=title, lifespan=lifespan)
        api.install(
            app,
            serve_dashboard=serve_dashboard,
            enable_websocket=enable_websocket,
            enable_audit_log=enable_audit_log,
            enable_cookie_consent=enable_cookie_consent,
            cookie_consent_message=cookie_consent_message,
            cookie_consent_version=cookie_consent_version,
        )
        return app
