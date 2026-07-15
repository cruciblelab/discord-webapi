"""Per-command cooldown enforcement (CommandOverride.cooldown_seconds/
cooldown_uses), using discord.py's own Cooldown/CooldownMapping primitives.
Exercises the actual installed discord.py version's cooldown mechanics
directly (not mocked) since this is exactly the kind of thing that has
silently broken across versions before -- see commands/bridge.py's
docstring on the same risk class.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands as dpy_commands

from discord_webapi.commands.models import CommandOverride
from discord_webapi.commands.registry import CommandRegistry
from discord_webapi.storage.memory import MemoryCommandConfigStore
from discord_webapi.transport import InProcessTransport

GUILD_ID = 1
COMMAND_NAME = "kick"


def _fake_context(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(author=SimpleNamespace(id=user_id), interaction=None)


def _fake_interaction(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=user_id))


async def _build_registry() -> CommandRegistry:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.hybrid_command(name=COMMAND_NAME, description="Kick a member")
    async def kick(ctx: dpy_commands.Context, member: discord.Member) -> None:
        ...

    transport = InProcessTransport()
    await transport.start()
    registry = CommandRegistry(bot, transport=transport, store=MemoryCommandConfigStore())
    await registry.register_all()
    return registry


def _set_cooldown(registry: CommandRegistry, *, uses: int, seconds: float) -> None:
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = CommandOverride(
        guild_id=GUILD_ID,
        command_name=COMMAND_NAME,
        enabled=True,
        cooldown_seconds=seconds,
        cooldown_uses=uses,
        updated_at=datetime.now(UTC),
    )


async def test_no_cooldown_configured_never_throttles() -> None:
    registry = await _build_registry()

    for _ in range(10):
        assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_context(1)) is None


async def test_cooldown_allows_up_to_configured_uses_then_blocks() -> None:
    registry = await _build_registry()
    _set_cooldown(registry, uses=2, seconds=60)
    ctx = _fake_context(user_id=42)

    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx) is None
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx) is None
    retry_after = registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx)

    assert retry_after is not None
    assert retry_after > 0


async def test_cooldown_bucket_is_per_user() -> None:
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)

    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_context(1)) is None
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_context(1)) is not None
    # A different user has their own, unused bucket.
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_context(2)) is None


async def test_cooldown_works_for_interaction_objects_too() -> None:
    """discord.Interaction has `.user`, not `.author` -- BucketType.user's
    own get_key() would raise AttributeError on it directly; this is
    exactly the gap _per_user_bucket_key exists to close."""
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)

    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_interaction(1)) is None
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_interaction(1)) is not None


async def test_cooldown_shared_bucket_across_context_and_interaction() -> None:
    """The same Discord user is the same bucket whether they invoked via
    the prefix/hybrid path (Context) or the slash path (Interaction)."""
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)

    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_context(7)) is None
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, _fake_interaction(7)) is not None


async def test_global_check_raises_command_on_cooldown() -> None:
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        author=SimpleNamespace(id=42),
        interaction=None,
    )

    assert await registry.global_check(ctx) is True  # first use consumes the token
    with pytest.raises(dpy_commands.CommandOnCooldown):
        await registry.global_check(ctx)


async def test_disabled_command_short_circuits_before_cooldown_check() -> None:
    """A disabled command must reject before ever touching the cooldown
    bucket -- otherwise re-enabling it would find tokens already spent."""
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = registry._override_cache[
        (GUILD_ID, COMMAND_NAME)
    ].model_copy(update={"enabled": False})
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        author=SimpleNamespace(id=42),
        interaction=None,
    )

    assert await registry.global_check(ctx) is False
    # Cooldown bucket untouched -- re-enabling immediately still allows a use.
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = registry._override_cache[
        (GUILD_ID, COMMAND_NAME)
    ].model_copy(update={"enabled": True})
    assert await registry.global_check(ctx) is True


async def test_updating_cooldown_params_resets_the_bucket() -> None:
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)
    ctx = _fake_context(1)
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx) is None
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx) is not None

    _set_cooldown(registry, uses=5, seconds=30)  # dashboard changes the limit

    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx) is None


async def test_successful_invocation_increments_counter() -> None:
    registry = await _build_registry()
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        author=SimpleNamespace(id=42),
        interaction=None,
    )

    await registry.global_check(ctx)
    await registry.global_check(ctx)

    status = registry._status_for(GUILD_ID, COMMAND_NAME)
    assert status.invocation_count == 2


async def test_global_check_is_a_noop_for_slash_invoked_hybrid_commands() -> None:
    """Regression test for a real bug found via physical testing: discord.py
    invokes *both* our wrapped `tree.interaction_check` *and* `global_check`
    (via `HybridCommand._check_can_run` -> `bot.can_run(ctx)`) for a single
    hybrid command invoked as a slash command -- `ctx.interaction` is set
    in that case. Without this early return, cooldown tokens and
    `invocation_count` would both be consumed/incremented twice per real
    invocation (exactly what happened: enabling a 1-use cooldown made the
    command appear permanently stuck, and invocation_count counted 2 per
    `/ping`)."""
    registry = await _build_registry()
    _set_cooldown(registry, uses=1, seconds=60)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        author=SimpleNamespace(id=42),
        interaction=SimpleNamespace(user=SimpleNamespace(id=42)),
    )

    # Called twice, as discord.py really does for one slash invocation of
    # a hybrid command -- must not raise CommandOnCooldown and must not
    # double-count.
    assert await registry.global_check(ctx) is True
    assert await registry.global_check(ctx) is True

    status = registry._status_for(GUILD_ID, COMMAND_NAME)
    assert status.invocation_count == 0  # global_check never counts here
    # The cooldown bucket itself was never touched by global_check either.
    assert registry._check_cooldown(GUILD_ID, COMMAND_NAME, ctx.interaction) is None


async def test_disabled_command_does_not_increment_counter() -> None:
    registry = await _build_registry()
    registry._override_cache[(GUILD_ID, COMMAND_NAME)] = CommandOverride(
        guild_id=GUILD_ID,
        command_name=COMMAND_NAME,
        enabled=False,
        updated_at=datetime.now(UTC),
    )
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        command=SimpleNamespace(qualified_name=COMMAND_NAME),
        author=SimpleNamespace(id=42),
        interaction=None,
    )

    await registry.global_check(ctx)

    status = registry._status_for(GUILD_ID, COMMAND_NAME)
    assert status.invocation_count == 0
