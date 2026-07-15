"""Exercises discord_webapi.builtins._shared directly -- these are meant to
be usable standalone by a consumer writing their own command from scratch,
not just internal glue for ban.py/kick.py/timeout.py."""

from unittest.mock import AsyncMock, MagicMock

import discord

from discord_webapi.builtins._shared import check_role_hierarchy, notify_member_best_effort


def _fake_ctx(*, author_top_role: int = 5, bot_top_role: int = 10) -> MagicMock:
    ctx = MagicMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.top_role = author_top_role
    ctx.guild.me.top_role = bot_top_role
    return ctx


def _fake_member(*, top_role: int = 1) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.top_role = top_role
    member.send = AsyncMock()
    return member


def test_check_role_hierarchy_allows_lower_ranked_target() -> None:
    ctx = _fake_ctx(author_top_role=5, bot_top_role=10)
    member = _fake_member(top_role=1)

    assert check_role_hierarchy(ctx, member) is None


def test_check_role_hierarchy_rejects_target_outranking_the_bot() -> None:
    ctx = _fake_ctx(bot_top_role=1)
    member = _fake_member(top_role=99)

    error = check_role_hierarchy(ctx, member)

    assert error is not None and "outranks mine" in error


def test_check_role_hierarchy_rejects_target_outranking_the_moderator() -> None:
    ctx = _fake_ctx(author_top_role=1, bot_top_role=100)
    member = _fake_member(top_role=99)

    error = check_role_hierarchy(ctx, member)

    assert error is not None and "outranks yours" in error


async def test_notify_member_best_effort_swallows_forbidden() -> None:
    member = _fake_member()
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), "blocked")

    await notify_member_best_effort(member, "hi")  # must not raise

    member.send.assert_called_once()


async def test_notify_member_best_effort_delivers_when_possible() -> None:
    member = _fake_member()

    await notify_member_best_effort(member, "hi")

    member.send.assert_called_once_with("hi")
