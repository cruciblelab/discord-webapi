"""Exercises discord_webapi.extras._shared directly -- these are meant to
be usable standalone by a consumer writing their own command from scratch,
not just internal glue for ban.py/kick.py/timeout.py."""

from unittest.mock import AsyncMock, MagicMock

import discord

from discord_webapi.extras._shared import (
    check_role_assignable,
    check_role_hierarchy,
    notify_member_best_effort,
)


def _fake_ctx(*, author_top_role: int = 5, bot_top_role: int = 10, author_id: int = 1) -> MagicMock:
    ctx = MagicMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.top_role = author_top_role
    ctx.author.id = author_id
    ctx.guild.me.top_role = bot_top_role
    return ctx


def _fake_member(*, top_role: int = 1, member_id: int = 2) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.top_role = top_role
    member.id = member_id
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


def test_check_role_hierarchy_rejects_targeting_yourself_with_a_clear_message() -> None:
    """Regression: a moderator's own role is always == their own role, so
    the equal-rank branch used to fire with a generic "outranks yours"
    message even for a self-target -- misleading, since it isn't actually
    higher. Self-targeting gets its own clearer message instead."""
    ctx = _fake_ctx(author_top_role=5, bot_top_role=100, author_id=42)
    member = _fake_member(top_role=5, member_id=42)

    error = check_role_hierarchy(ctx, member)

    assert error is not None
    assert "yourself" in error


def test_check_role_assignable_allows_a_role_below_both() -> None:
    ctx = _fake_ctx(author_top_role=50, bot_top_role=100)

    assert check_role_assignable(ctx, 10) is None  # type: ignore[arg-type]


def test_check_role_assignable_rejects_a_role_outranking_the_bot() -> None:
    ctx = _fake_ctx(author_top_role=50, bot_top_role=5)

    error = check_role_assignable(ctx, 10)  # type: ignore[arg-type]

    assert error is not None and "outranks (or matches) my" in error


def test_check_role_assignable_rejects_a_role_outranking_the_moderator() -> None:
    ctx = _fake_ctx(author_top_role=5, bot_top_role=100)

    error = check_role_assignable(ctx, 10)  # type: ignore[arg-type]

    assert error is not None and "outranks (or matches) your" in error


def test_check_role_assignable_rejects_a_role_matching_the_moderators_own() -> None:
    ctx = _fake_ctx(author_top_role=10, bot_top_role=100)

    error = check_role_assignable(ctx, 10)  # type: ignore[arg-type]

    assert error is not None and "outranks (or matches) your" in error


async def test_notify_member_best_effort_swallows_forbidden() -> None:
    member = _fake_member()
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), "blocked")

    await notify_member_best_effort(member, "hi")  # must not raise

    member.send.assert_called_once()


async def test_notify_member_best_effort_delivers_when_possible() -> None:
    member = _fake_member()

    await notify_member_best_effort(member, "hi")

    member.send.assert_called_once_with("hi")
