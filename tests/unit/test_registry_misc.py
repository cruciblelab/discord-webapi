"""Covers CommandRegistry paths not exercised by test_command_cooldown.py:
the `command_meta` decorator, the wrapped slash-command `interaction_check`
itself (not just `global_check`), and `_on_config_changed`'s cache-clear
branch when a store lookup comes back empty (override deleted).
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands as dpy_commands

from discord_webapi.commands.events import EVENT_TYPE_COMMAND_CONFIG_CHANGED, CommandConfigChanged
from discord_webapi.commands.models import CommandOverride
from discord_webapi.commands.registry import CommandRegistry
from discord_webapi.storage.memory import MemoryCommandConfigStore
from discord_webapi.transport.base import Event
from discord_webapi.transport.inprocess import InProcessTransport

GUILD_ID = 1
COMMAND_NAME = "kick"


def _fake_interaction(guild_id: int | None, user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        type=discord.InteractionType.application_command,
        guild_id=guild_id,
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        user=SimpleNamespace(id=user_id),
    )


async def _build_bot_and_registry() -> tuple[dpy_commands.Bot, CommandRegistry]:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.hybrid_command(name=COMMAND_NAME, description="Kick a member")
    async def kick(ctx: dpy_commands.Context, member: discord.Member) -> None: ...

    transport = InProcessTransport()
    await transport.start()
    registry = CommandRegistry(bot, transport=transport, store=MemoryCommandConfigStore())
    return bot, registry


async def test_command_meta_overrides_category_and_default_enabled() -> None:
    bot, registry = await _build_bot_and_registry()
    command = bot.get_command(COMMAND_NAME)
    registry.command_meta(category="moderation", default_enabled=False)(command)

    await registry.register_all()

    spec = registry._specs[COMMAND_NAME]
    assert spec.category == "moderation"
    assert spec.default_enabled is False
    assert registry.is_enabled(GUILD_ID, COMMAND_NAME) is False


def test_command_meta_rejects_objects_without_a_name() -> None:
    registry = CommandRegistry(
        dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default()),
        transport=InProcessTransport(),
        store=MemoryCommandConfigStore(),
    )

    with pytest.raises(TypeError, match="command_meta must decorate"):
        registry.command_meta()(object())


async def test_wrapped_interaction_check_rejects_disabled_command() -> None:
    _bot, registry = await _build_bot_and_registry()
    await registry.register_all()
    override = registry._override_cache
    override[(GUILD_ID, COMMAND_NAME)] = CommandOverride(
        guild_id=GUILD_ID,
        command_name=COMMAND_NAME,
        enabled=False,
        updated_at=datetime.now(UTC),
    )

    allowed = await _bot.tree.interaction_check(_fake_interaction(GUILD_ID, user_id=1))  # type: ignore[arg-type]

    assert allowed is False


async def test_wrapped_interaction_check_allows_enabled_command_and_counts_invocation() -> None:
    bot, registry = await _build_bot_and_registry()
    await registry.register_all()

    allowed = await bot.tree.interaction_check(_fake_interaction(GUILD_ID, user_id=1))  # type: ignore[arg-type]

    assert allowed is True
    assert registry._invocation_counts[(GUILD_ID, COMMAND_NAME)] == 1


async def test_wrapped_interaction_check_passes_through_dm_interactions() -> None:
    """No guild_id (a DM-context interaction) -- nothing to enforce against,
    so it must pass through untouched (matches global_check's own DM path)."""
    bot, registry = await _build_bot_and_registry()
    await registry.register_all()

    allowed = await bot.tree.interaction_check(_fake_interaction(None, user_id=1))  # type: ignore[arg-type]

    assert allowed is True


async def test_on_config_changed_clears_cache_when_override_deleted() -> None:
    _bot, registry = await _build_bot_and_registry()
    await registry.register_all()
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = CommandOverride(
        guild_id=GUILD_ID, command_name=COMMAND_NAME, enabled=False, updated_at=datetime.now(UTC)
    )
    # Store has nothing for this key -- simulates the override having been
    # deleted out from under an already-warm cache entry.
    change = CommandConfigChanged(guild_id=GUILD_ID, command_name=COMMAND_NAME)
    await registry._on_config_changed(
        Event(type=EVENT_TYPE_COMMAND_CONFIG_CHANGED, payload=change.model_dump())
    )

    assert (GUILD_ID, COMMAND_NAME) not in registry._override_cache
