"""CommandOverride.required_app_role enforcement -- previously a dead
field: defined on the model, persisted by SQL/Memory stores, but never
settable through set_override/the PATCH endpoint and never checked by
CommandRegistry's own enforcement (global_check / interaction_check).
This exercises the now-real enforcement path end to end.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands as dpy_commands

from discord_webapi.authz.app_roles import AppRoleCache
from discord_webapi.authz.models import AppRole
from discord_webapi.commands.models import CommandOverride
from discord_webapi.commands.registry import CommandRegistry
from discord_webapi.storage.memory import MemoryAuthzStore, MemoryCommandConfigStore
from discord_webapi.transport import InProcessTransport

GUILD_ID = 1
COMMAND_NAME = "kick"
MOD_ROLE_ID = 999


async def _build_registry(*, app_role_cache: AppRoleCache | None) -> CommandRegistry:
    bot = dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )

    @bot.hybrid_command(name=COMMAND_NAME, description="Kick a member")
    async def kick(ctx: dpy_commands.Context, member: discord.Member) -> None:
        ...

    transport = InProcessTransport()
    await transport.start()
    registry = CommandRegistry(
        bot, transport=transport, store=MemoryCommandConfigStore(), app_role_cache=app_role_cache
    )
    await registry.register_all()
    return registry


def _set_required_app_role(registry: CommandRegistry, role_name: str | None) -> None:
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = CommandOverride(
        guild_id=GUILD_ID,
        command_name=COMMAND_NAME,
        enabled=True,
        required_app_role=role_name,
        updated_at=datetime.now(UTC),
    )


def _fake_ctx(*, user_id: int, role_ids: list[int]) -> SimpleNamespace:
    return SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        author=SimpleNamespace(id=user_id, roles=[SimpleNamespace(id=r) for r in role_ids]),
        interaction=None,
    )


async def test_no_required_app_role_always_allows() -> None:
    registry = await _build_registry(app_role_cache=None)
    _set_required_app_role(registry, None)

    assert await registry.global_check(_fake_ctx(user_id=1, role_ids=[])) is True


async def test_required_app_role_denies_without_an_app_role_cache(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fails closed: a required_app_role configured but no AppRoleCache
    wired into the registry is a misconfiguration, not a free pass -- and
    it's logged as a warning so it doesn't look like a silent "why is my
    command always rejected?" bug."""
    registry = await _build_registry(app_role_cache=None)
    _set_required_app_role(registry, "moderator")

    with caplog.at_level("WARNING", logger="discord_webapi.commands"):
        assert await registry.global_check(_fake_ctx(user_id=1, role_ids=[])) is False

    assert any("app_role_cache" in r.message for r in caplog.records)


async def test_user_with_matching_discord_role_is_allowed() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(
        AppRole(name="moderator", guild_id=GUILD_ID, discord_role_ids=[MOD_ROLE_ID], user_ids=[])
    )
    cache = AppRoleCache(store)
    registry = await _build_registry(app_role_cache=cache)
    _set_required_app_role(registry, "moderator")

    ctx = _fake_ctx(user_id=1, role_ids=[MOD_ROLE_ID])
    assert await registry.global_check(ctx) is True


async def test_user_without_matching_role_is_denied() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(
        AppRole(name="moderator", guild_id=GUILD_ID, discord_role_ids=[MOD_ROLE_ID], user_ids=[])
    )
    cache = AppRoleCache(store)
    registry = await _build_registry(app_role_cache=cache)
    _set_required_app_role(registry, "moderator")

    ctx = _fake_ctx(user_id=1, role_ids=[111])  # some unrelated role
    assert await registry.global_check(ctx) is False


async def test_user_granted_by_explicit_user_id_is_allowed() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(
        AppRole(name="moderator", guild_id=GUILD_ID, discord_role_ids=[], user_ids=[42])
    )
    cache = AppRoleCache(store)
    registry = await _build_registry(app_role_cache=cache)
    _set_required_app_role(registry, "moderator")

    ctx = _fake_ctx(user_id=42, role_ids=[])
    assert await registry.global_check(ctx) is True


async def test_app_role_check_short_circuits_before_cooldown() -> None:
    """A denied app-role check must reject before ever touching the
    cooldown bucket, same reasoning as the disabled-command short circuit."""
    store = MemoryAuthzStore()
    await store.set_app_role(
        AppRole(name="moderator", guild_id=GUILD_ID, discord_role_ids=[MOD_ROLE_ID], user_ids=[])
    )
    cache = AppRoleCache(store)
    registry = await _build_registry(app_role_cache=cache)
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = CommandOverride(
        guild_id=GUILD_ID,
        command_name=COMMAND_NAME,
        enabled=True,
        cooldown_seconds=60.0,
        cooldown_uses=1,
        required_app_role="moderator",
        updated_at=datetime.now(UTC),
    )
    ctx = _fake_ctx(user_id=1, role_ids=[])

    assert await registry.global_check(ctx) is False
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx) is None  # bucket untouched


async def test_set_override_persists_required_app_role() -> None:
    registry = await _build_registry(app_role_cache=None)

    status = await registry.set_override(
        GUILD_ID, COMMAND_NAME, enabled=True, required_app_role="moderator"
    )

    assert status.required_app_role == "moderator"
    stored = await registry.store.get_override(GUILD_ID, COMMAND_NAME)
    assert stored is not None
    assert stored.required_app_role == "moderator"


async def test_slash_interaction_check_also_enforces_required_app_role() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(
        AppRole(name="moderator", guild_id=GUILD_ID, discord_role_ids=[MOD_ROLE_ID], user_ids=[])
    )
    cache = AppRoleCache(store)
    registry = await _build_registry(app_role_cache=cache)
    _set_required_app_role(registry, "moderator")

    interaction = SimpleNamespace(
        guild_id=GUILD_ID,
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        user=SimpleNamespace(id=1, roles=[]),
    )
    assert await registry.bot.tree.interaction_check(interaction) is False

    interaction_allowed = SimpleNamespace(
        guild_id=GUILD_ID,
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        user=SimpleNamespace(id=1, roles=[SimpleNamespace(id=MOD_ROLE_ID)]),
    )
    assert await registry.bot.tree.interaction_check(interaction_allowed) is True
