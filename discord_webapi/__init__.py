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
from discord_webapi.auth import DiscordAuth, DiscordUser, SessionSummary, get_current_user
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
    install_guild_listing,
    install_member_lookup,
    single_process_lifespan,
    web_only_lifespan,
)
from discord_webapi.commands import (
    CommandOverride,
    CommandRegistry,
    CommandSpec,
    CommandStatus,
    build_commands_router,
    install_command_registry_bridge,
)
from discord_webapi.consent import ConsentRecord, build_consent_router
from discord_webapi.escalation import (
    EscalationEngine,
    EscalationRule,
    EscalationRuleStore,
    MemoryEscalationRuleStore,
    MemoryViolationStore,
    ViolationStore,
    build_escalation_router,
)
from discord_webapi.guilds import ManageableGuild, build_guilds_router
from discord_webapi.jobs import (
    InProcessJobQueue,
    JobQueue,
    JobStatus,
    build_jobs_router,
    run_worker,
)
from discord_webapi.members import MemberInfo, build_members_router, install_member_listing
from discord_webapi.ratelimits import GuildRateLimiter, RateLimitRule, build_ratelimits_router
from discord_webapi.storage import (
    AuditStore,
    AuthzStore,
    CommandConfigStore,
    ConsentStore,
    MemoryAuditStore,
    MemoryAuthzStore,
    MemoryCommandConfigStore,
    MemoryConsentStore,
    MemoryRateLimitStore,
    RateLimitStore,
)
from discord_webapi.transport import Event, InProcessTransport, Transport
from discord_webapi.web import (
    DEFAULT_COOKIE_CONSENT_MESSAGE,
    DEFAULT_COOKIE_CONSENT_VERSION,
    build_commands_websocket_router,
    build_default_dashboard_router,
)

if TYPE_CHECKING:
    from discord_webapi.escalation.sql import SQLEscalationRuleStore, SQLViolationStore
    from discord_webapi.jobs.redis import RedisJobQueue
    from discord_webapi.storage.sql import (
        SQLAuditStore,
        SQLAuthzStore,
        SQLCommandConfigStore,
        SQLConsentStore,
        SQLRateLimitStore,
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
    "EscalationEngine",
    "EscalationRule",
    "EscalationRuleStore",
    "Event",
    "GuildContext",
    "GuildMemberCache",
    "GuildRateLimiter",
    "InProcessJobQueue",
    "InProcessTransport",
    "JobQueue",
    "JobStatus",
    "ManageableGuild",
    "MemberInfo",
    "MemoryAuditStore",
    "MemoryAuthzStore",
    "MemoryCommandConfigStore",
    "MemoryConsentStore",
    "MemoryEscalationRuleStore",
    "MemoryRateLimitStore",
    "MemoryViolationStore",
    "RateLimitRule",
    "RateLimitStore",
    "RedisJobQueue",
    "RedisTransport",
    "SQLAuditStore",
    "SQLAuthzStore",
    "SQLCommandConfigStore",
    "SQLConsentStore",
    "SQLEscalationRuleStore",
    "SQLRateLimitStore",
    "SQLSessionStore",
    "SQLViolationStore",
    "SessionSummary",
    "Transport",
    "ViolationStore",
    "build_app_roles_router",
    "build_audit_log_router",
    "build_commands_router",
    "build_consent_router",
    "build_escalation_router",
    "build_guilds_router",
    "build_jobs_router",
    "build_members_router",
    "build_ratelimits_router",
    "get_current_user",
    "require_app_role",
    "require_channel_permission",
    "require_guild_permission",
    "require_role",
    "run_worker",
]


def __getattr__(name: str) -> object:
    if name == "RedisTransport":
        from discord_webapi.transport.redis import RedisTransport

        return RedisTransport
    if name == "RedisJobQueue":
        from discord_webapi.jobs.redis import RedisJobQueue

        return RedisJobQueue
    if name in (
        "SQLSessionStore",
        "SQLCommandConfigStore",
        "SQLAuthzStore",
        "SQLAuditStore",
        "SQLConsentStore",
        "SQLRateLimitStore",
    ):
        from discord_webapi.storage import sql

        return getattr(sql, name)
    if name in ("SQLEscalationRuleStore", "SQLViolationStore"):
        from discord_webapi.escalation import sql as escalation_sql

        return getattr(escalation_sql, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@asynccontextmanager
async def _with_job_queue(
    inner: AbstractAsyncContextManager[None], job_queue: JobQueue | None
) -> AsyncIterator[None]:
    if job_queue is None:
        async with inner:
            yield
        return
    started = False
    try:
        await job_queue.start()
        started = True
        async with inner:
            yield
    finally:
        if started:
            await job_queue.stop()


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

    For large bots that want the bot process and the FastAPI dashboard
    running as entirely separate processes/machines (so the web side can
    be scaled horizontally behind a load balancer, independent of the
    single Discord Gateway connection), see `DiscordWebAPI.for_bot_process`
    and `DiscordWebAPI.for_web_process` instead — both talk over the same
    `RedisTransport`, and require no code changes to any route/dependency
    in this package (they were already written only against `Transport`,
    never a concrete bot object).
    """

    def __init__(
        self,
        *,
        transport: Transport,
        bot: commands.Bot | None = None,
        auth: DiscordAuth | None = None,
        command_store: CommandConfigStore | None = None,
        authz_store: AuthzStore | None = None,
        audit_store: AuditStore | None = None,
        consent_store: ConsentStore | None = None,
        rate_limit_store: RateLimitStore | None = None,
        escalation_rule_store: EscalationRuleStore | None = None,
        violation_store: ViolationStore | None = None,
        job_queue: JobQueue | None = None,
        member_cache_ttl_seconds: float = 45.0,
        channel_permission_cache_ttl_seconds: float = 30.0,
        default_rate_limit_max_calls: int = 5,
        default_rate_limit_per_seconds: float = 10.0,
        sync_commands: bool = True,
        sync_guild_id: int | None = None,
    ) -> None:
        self.bot = bot
        self.transport = transport
        self.auth = auth
        self.job_queue = job_queue
        self._sync_commands = sync_commands
        self._sync_guild_id = sync_guild_id
        self._commands_synced = False
        self.command_store = command_store or MemoryCommandConfigStore()
        self.authz_store = authz_store or MemoryAuthzStore()
        self.audit_store = audit_store or MemoryAuditStore()
        self.consent_store = consent_store or MemoryConsentStore()
        self.rate_limit_store = rate_limit_store or MemoryRateLimitStore()
        self.escalation_rule_store = escalation_rule_store or MemoryEscalationRuleStore()
        self.violation_store = violation_store or MemoryViolationStore()
        self.member_cache = GuildMemberCache(transport, ttl_seconds=member_cache_ttl_seconds)
        self.channel_permission_cache = ChannelPermissionCache(
            transport, ttl_seconds=channel_permission_cache_ttl_seconds
        )
        self.app_role_cache = AppRoleCache(self.authz_store)
        # Usable in any process (bot-side, e.g. from an automod check;
        # web-side, e.g. protecting a dashboard endpoint) -- unlike the
        # CommandRegistry's RPC handlers, subscribing to a Transport event
        # has no "exactly one process" constraint, so this is always
        # constructed, never gated on `bot is not None`.
        self.rate_limiter = GuildRateLimiter(
            transport,
            self.rate_limit_store,
            default_max_calls=default_rate_limit_max_calls,
            default_per_seconds=default_rate_limit_per_seconds,
        )
        # Same reasoning: escalation actions (timeout/kick/ban) are usually
        # applied from bot-process code (extras.warn, extras.automod's
        # on_violation hook, your own commands), so this is always
        # constructed too -- enable_escalation_api only gates the
        # dashboard CRUD endpoints, not the object itself.
        self.escalation_engine = EscalationEngine(
            transport, self.escalation_rule_store, self.violation_store
        )

        self.registry: CommandRegistry | None = None
        if bot is not None:
            # All bot-process-only wiring: a web-only process (see
            # `for_web_process`) must NOT own a `CommandRegistry` or
            # register any of these RPC handlers -- RedisTransport's plain
            # pub/sub has undefined behavior if two processes both
            # `register_handler()` the same command name (see its
            # docstring), so exactly the one process that actually owns
            # the live bot may do this.
            self.registry = CommandRegistry(bot, transport=transport, store=self.command_store)
            install_command_registry_bridge(self.registry, transport)
            install_member_lookup(bot, transport)
            install_channel_permission_lookup(bot, transport)
            install_member_listing(bot, transport)
            install_guild_listing(bot, transport)
            bot.add_listener(self._on_ready, name="on_ready")

    @classmethod
    def for_bot_process(
        cls,
        *,
        bot: commands.Bot,
        transport: Transport,
        command_store: CommandConfigStore | None = None,
        rate_limit_store: RateLimitStore | None = None,
        escalation_rule_store: EscalationRuleStore | None = None,
        violation_store: ViolationStore | None = None,
        job_queue: JobQueue | None = None,
        sync_commands: bool = True,
        sync_guild_id: int | None = None,
    ) -> DiscordWebAPI:
        """Construct the bot-side half of a split bot/web deployment: owns
        the live `CommandRegistry` and answers every bot-process RPC
        (member/channel-permission/guild-listing lookups, command status/
        overrides) — no FastAPI here at all. Run its `.lifespan(token)` (or
        `bot.extension.run_bot_process`) in a standalone process, pointed
        at a `RedisTransport` so any number of `for_web_process` FastAPI
        replicas/machines can reach it.

        Pass `job_queue=...` (with `register_worker()` already called on
        it) if any of your job handlers need live bot/Gateway access (e.g.
        "bulk-DM every member") -- `.lifespan(token)` starts/stops it
        alongside the bot, same as `for_web_process`. Job handlers with no
        such need don't have to run here at all; a plain standalone
        `run_worker()` process works just as well for those.
        """
        return cls(
            transport=transport,
            bot=bot,
            command_store=command_store,
            rate_limit_store=rate_limit_store,
            escalation_rule_store=escalation_rule_store,
            violation_store=violation_store,
            job_queue=job_queue,
            sync_commands=sync_commands,
            sync_guild_id=sync_guild_id,
        )

    @classmethod
    def for_web_process(
        cls,
        *,
        transport: Transport,
        auth: DiscordAuth,
        authz_store: AuthzStore | None = None,
        audit_store: AuditStore | None = None,
        consent_store: ConsentStore | None = None,
        rate_limit_store: RateLimitStore | None = None,
        escalation_rule_store: EscalationRuleStore | None = None,
        violation_store: ViolationStore | None = None,
        job_queue: JobQueue | None = None,
        member_cache_ttl_seconds: float = 45.0,
        channel_permission_cache_ttl_seconds: float = 30.0,
    ) -> DiscordWebAPI:
        """Construct the web-side half of a split bot/web deployment: no
        `discord.Bot` object at all — every dashboard route already talks
        only to `Transport`/the shared stores, never to a concrete bot, so
        this is simply the same facade with the bot-only pieces skipped.
        Run as many of these as you want (separate processes, separate
        machines, behind a load balancer), all pointed at the same
        `RedisTransport` and database as the one `for_bot_process`.
        """
        return cls(
            transport=transport,
            auth=auth,
            authz_store=authz_store,
            audit_store=audit_store,
            consent_store=consent_store,
            rate_limit_store=rate_limit_store,
            escalation_rule_store=escalation_rule_store,
            violation_store=violation_store,
            job_queue=job_queue,
            member_cache_ttl_seconds=member_cache_ttl_seconds,
            channel_permission_cache_ttl_seconds=channel_permission_cache_ttl_seconds,
        )

    async def _on_ready(self) -> None:
        assert self.bot is not None and self.registry is not None  # only a listener when bot is set
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
        enable_jobs: bool = False,
        enable_ratelimits_api: bool = False,
        enable_escalation_api: bool = False,
    ) -> None:
        if self.auth is None:
            raise RuntimeError(
                "install() needs auth=... -- this DiscordWebAPI was built via "
                "for_bot_process(), which has no FastAPI app to install onto"
            )
        self.auth.install(app)
        app.state.discord_webapi_member_cache = self.member_cache
        app.state.discord_webapi_channel_permission_cache = self.channel_permission_cache
        app.state.discord_webapi_transport = self.transport
        app.state.discord_webapi_app_role_cache = self.app_role_cache
        # Always set, unlike the dashboard endpoints below it (opt-in via
        # enable_ratelimits_api) -- GuildRateLimiter is meant to be usable
        # directly from your own routes/commands (request.app.state...,
        # or the DiscordWebAPI instance's own `.rate_limiter` attribute)
        # even if you never expose the dashboard API for editing it.
        app.state.discord_webapi_ratelimiter = self.rate_limiter
        # Same reasoning as the rate limiter above -- always reachable
        # from your own code, dashboard CRUD is the opt-in part.
        app.state.discord_webapi_escalation_engine = self.escalation_engine
        app.include_router(build_commands_router())
        app.include_router(build_members_router())
        app.include_router(build_app_roles_router())
        app.include_router(build_guilds_router())
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
        if enable_jobs:
            if self.job_queue is None:
                raise RuntimeError(
                    "enable_jobs=True needs job_queue=... passed to DiscordWebAPI(...) -- "
                    "construct one (e.g. InProcessJobQueue()), register your job_type "
                    "handlers on it with register_worker(), then pass it in"
                )
            app.state.discord_webapi_job_queue = self.job_queue
            app.include_router(build_jobs_router())
        if enable_ratelimits_api:
            app.include_router(build_ratelimits_router())
        if enable_escalation_api:
            app.include_router(build_escalation_router())

    def lifespan(self, token: str) -> AbstractAsyncContextManager[None]:
        if self.bot is None:
            raise RuntimeError(
                "lifespan(token) needs a bot -- this DiscordWebAPI was built via "
                "for_web_process(), which has no bot to start. Use web_lifespan() "
                "instead (or run_bot_process()/for_bot_process().lifespan(token) "
                "in the separate bot process)."
            )
        return _with_job_queue(
            single_process_lifespan(self.bot, self.transport, token), self.job_queue
        )

    def web_lifespan(self) -> AbstractAsyncContextManager[None]:
        """FastAPI lifespan for a web-only process in a split bot/web
        deployment (see `for_web_process`) -- starts/stops this process's
        own connection to the shared Transport, with no bot involved."""
        return _with_job_queue(web_only_lifespan(self.transport), self.job_queue)

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
        enable_ratelimits_api: bool = False,
        enable_escalation_api: bool = False,
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

        from discord_webapi.escalation.sql import SQLEscalationRuleStore, SQLViolationStore
        from discord_webapi.storage.sql import (
            SQLAuditStore,
            SQLAuthzStore,
            SQLCommandConfigStore,
            SQLConsentStore,
            SQLRateLimitStore,
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
        escalation_rule_store = SQLEscalationRuleStore(engine)
        violation_store = SQLViolationStore(engine)
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
            rate_limit_store=SQLRateLimitStore(engine),
            escalation_rule_store=escalation_rule_store,
            violation_store=violation_store,
            sync_commands=sync_commands,
            sync_guild_id=sync_guild_id,
        )

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            await create_all_tables(engine)
            await escalation_rule_store.create_all()
            await violation_store.create_all()
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
            enable_ratelimits_api=enable_ratelimits_api,
            enable_escalation_api=enable_escalation_api,
        )
        return app
