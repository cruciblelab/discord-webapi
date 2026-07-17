"""Exercises discord_webapi.commands.bridge against every parameter type the
dashboard needs to render (str/int/bool/Member/Role/Channel/Attachment).

This file is run in CI against a matrix of pinned discord.py versions (see
.github/workflows/ci.yml) — the flagship command-introspection feature has
silently broken across discord.py minor releases before by changing how
`Parameter`/annotation internals are stored, so this suite is the concrete
guard against that regression class (risk #6 in the architecture plan).
"""

import discord
from discord import app_commands
from discord.ext import commands as dpy_commands

from discord_webapi.commands.bridge import extract_command_specs


def _build_bot_with_slash_command() -> dpy_commands.Bot:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.tree.command(name="moderate", description="Moderate a member")
    @app_commands.describe(member="who to act on", count="how many times", silent="no announcement")
    async def moderate(
        interaction: discord.Interaction,
        member: discord.Member,
        count: int,
        silent: bool,
        note: str,
        channel: discord.TextChannel,
        role: discord.Role,
        attachment: discord.Attachment,
    ) -> None:
        ...

    return bot


def test_extracts_slash_command_basic_fields() -> None:
    bot = _build_bot_with_slash_command()

    specs = extract_command_specs(bot)

    assert len(specs) == 1
    spec = specs[0]
    assert spec.name == "moderate"
    assert spec.description == "Moderate a member"
    assert spec.is_slash is True
    assert spec.is_prefix is False


def test_extracts_every_slash_param_type_correctly() -> None:
    bot = _build_bot_with_slash_command()

    spec = extract_command_specs(bot)[0]
    params_by_name = {p.name: p for p in spec.params}

    assert params_by_name["member"].type == "user"
    assert params_by_name["count"].type == "integer"
    assert params_by_name["silent"].type == "boolean"
    assert params_by_name["note"].type == "string"
    assert params_by_name["channel"].type == "channel"
    assert params_by_name["role"].type == "role"
    assert params_by_name["attachment"].type == "attachment"
    assert all(p.required for p in spec.params)


def test_extracts_prefix_command_params() -> None:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.command(name="warn")
    async def warn(
        ctx: dpy_commands.Context, member: discord.Member, *, reason: str = "none"
    ) -> None:
        ...

    spec = extract_command_specs(bot)[0]

    assert spec.is_prefix is True
    assert spec.is_slash is False
    params_by_name = {p.name: p for p in spec.params}
    assert params_by_name["member"].type == "member"
    assert params_by_name["reason"].required is False


def test_a_greedy_typed_prefix_command_does_not_abort_introspection_of_the_whole_bot() -> None:
    """Regression test: `commands.Greedy[int]` subclasses `List[T]` and
    inherits its unhashability -- `_prefix_param_type_name` used to do
    `annotation in _PYTHON_TYPE_NAMES` (a dict membership test, which
    hashes the key), raising an uncaught `TypeError: unhashable type:
    'Greedy'`. Since `extract_command_specs` iterates every command
    inline with no per-command try/except, ONE Greedy-typed parameter
    anywhere in the bot used to abort introspection of every other
    command too -- `CommandRegistry.register_all()` never completed, so
    the dashboard enable/disable check never got installed at all."""
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.command(name="greedy-cmd")
    async def greedy_cmd(ctx: dpy_commands.Context, numbers: dpy_commands.Greedy[int]) -> None:
        ...

    @bot.command(name="other-cmd")
    async def other_cmd(ctx: dpy_commands.Context, member: discord.Member) -> None:
        ...

    specs = extract_command_specs(bot)

    assert {s.name for s in specs} == {"greedy-cmd", "other-cmd"}
    greedy_spec = next(s for s in specs if s.name == "greedy-cmd")
    assert greedy_spec.params[0].type == "integer"  # the Greedy's element type


def test_hybrid_command_merges_into_single_spec() -> None:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.hybrid_command(name="kick", description="Kick a member")
    async def kick(ctx: dpy_commands.Context, member: discord.Member) -> None:
        ...

    specs = extract_command_specs(bot)

    assert len(specs) == 1
    assert specs[0].is_slash is True
    assert specs[0].is_prefix is True


def test_hidden_prefix_commands_are_excluded() -> None:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.command(name="secret", hidden=True)
    async def secret(ctx: dpy_commands.Context) -> None:
        ...

    specs = extract_command_specs(bot)

    assert specs == []


def test_no_commands_returns_empty_list() -> None:
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    assert extract_command_specs(bot) == []
