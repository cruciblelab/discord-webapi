from functools import total_ordering
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.extras.role_assign import setup as setup_role_assign


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


@total_ordering
class _FakeRole:
    """Discord's own `discord.Role` orders by `.position`; a plain
    comparable stand-in is far less brittle here than trying to make a
    `MagicMock(spec=discord.Role)` reproduce that ordering."""

    def __init__(self, position: int, name: str = "Verified") -> None:
        self.position = position
        self.name = name
        self.id = position

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FakeRole) and self.position == other.position

    def __lt__(self, other: "_FakeRole") -> bool:
        return self.position < other.position

    def __hash__(self) -> int:
        return hash(self.position)


def _fake_ctx(*, author_top_role: int = 5, bot_top_role: int = 10) -> MagicMock:
    ctx = MagicMock()
    ctx.reply = AsyncMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.top_role = _FakeRole(author_top_role)
    ctx.guild.me.top_role = _FakeRole(bot_top_role)
    return ctx


def _fake_member(*, roles: list[_FakeRole] | None = None) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.roles = roles or []
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


def test_setup_registers_both_commands() -> None:
    bot = _build_bot()

    role_add, role_remove = setup_role_assign(bot)

    assert role_add.name == "role-add"
    assert role_remove.name == "role-remove"
    assert bot.get_command("role-add") is role_add
    assert bot.get_command("role-remove") is role_remove


async def test_role_add_works_without_a_reason_by_default() -> None:
    bot = _build_bot()
    role_add, _remove = setup_role_assign(bot)
    ctx = _fake_ctx()
    member = _fake_member()
    role = _FakeRole(1)

    await role_add.callback(ctx, member, role, None)

    member.add_roles.assert_called_once()


async def test_role_add_requires_reason_when_configured() -> None:
    bot = _build_bot()
    role_add, _remove = setup_role_assign(bot, require_reason=True)
    ctx = _fake_ctx()
    member = _fake_member()
    role = _FakeRole(1)

    await role_add.callback(ctx, member, role, None)

    member.add_roles.assert_not_called()


async def test_role_add_refuses_a_role_that_outranks_the_moderator() -> None:
    bot = _build_bot()
    role_add, _remove = setup_role_assign(bot)
    ctx = _fake_ctx(author_top_role=5, bot_top_role=100)
    member = _fake_member()
    role = _FakeRole(50)

    await role_add.callback(ctx, member, role, "promotion")

    member.add_roles.assert_not_called()
    assert "outranks" in ctx.reply.call_args.args[0]


async def test_role_add_refuses_a_role_that_outranks_the_bot() -> None:
    bot = _build_bot()
    role_add, _remove = setup_role_assign(bot)
    ctx = _fake_ctx(author_top_role=100, bot_top_role=5)
    member = _fake_member()
    role = _FakeRole(50)

    await role_add.callback(ctx, member, role, "promotion")

    member.add_roles.assert_not_called()
    assert "outranks" in ctx.reply.call_args.args[0]


async def test_role_add_skips_if_member_already_has_the_role() -> None:
    bot = _build_bot()
    role_add, _remove = setup_role_assign(bot)
    ctx = _fake_ctx()
    role = _FakeRole(1)
    member = _fake_member(roles=[role])

    await role_add.callback(ctx, member, role, None)

    member.add_roles.assert_not_called()
    assert "already has" in ctx.reply.call_args.args[0]


async def test_role_remove_removes_a_role_the_member_has() -> None:
    bot = _build_bot()
    _add, role_remove = setup_role_assign(bot)
    ctx = _fake_ctx()
    role = _FakeRole(1)
    member = _fake_member(roles=[role])

    await role_remove.callback(ctx, member, role, "cleanup")

    member.remove_roles.assert_called_once()


async def test_role_remove_skips_if_member_does_not_have_the_role() -> None:
    bot = _build_bot()
    _add, role_remove = setup_role_assign(bot)
    ctx = _fake_ctx()
    role = _FakeRole(1)
    member = _fake_member(roles=[])

    await role_remove.callback(ctx, member, role, None)

    member.remove_roles.assert_not_called()
    assert "doesn't have" in ctx.reply.call_args.args[0]


async def test_role_add_forbidden_from_discord_replies_cleanly() -> None:
    bot = _build_bot()
    role_add, _remove = setup_role_assign(bot)
    ctx = _fake_ctx()
    member = _fake_member()
    member.add_roles.side_effect = discord.Forbidden(MagicMock(status=403), "missing permissions")
    role = _FakeRole(1)

    await role_add.callback(ctx, member, role, None)

    assert "permission" in ctx.reply.call_args.args[0].lower()


async def test_role_remove_not_found_from_discord_replies_cleanly() -> None:
    bot = _build_bot()
    _add, role_remove = setup_role_assign(bot)
    ctx = _fake_ctx()
    role = _FakeRole(1)
    member = _fake_member(roles=[role])
    member.remove_roles.side_effect = discord.NotFound(MagicMock(status=404), "unknown member")

    await role_remove.callback(ctx, member, role, "cleanup")

    assert "no longer in the server" in ctx.reply.call_args.args[0].lower()


async def test_audit_logger_records_role_add_and_remove_with_distinct_actions() -> None:
    bot = _build_bot()
    audit_logger = MagicMock()
    audit_logger.record = AsyncMock()
    role_add, role_remove = setup_role_assign(bot, audit_logger=audit_logger)
    ctx = _fake_ctx()
    role = _FakeRole(1)

    await role_add.callback(ctx, _fake_member(), role, None)
    await role_remove.callback(ctx, _fake_member(roles=[role]), role, None)

    actions = [call.kwargs["action"] for call in audit_logger.record.call_args_list]
    assert actions == ["role_assign.add", "role_assign.remove"]
