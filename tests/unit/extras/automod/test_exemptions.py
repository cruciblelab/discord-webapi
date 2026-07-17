from unittest.mock import MagicMock

import discord

from discord_webapi.extras.automod.exemptions import is_exempt

CHANNEL_ID = 1
ROLE_ID = 2


def _fake_message(
    *,
    channel_id: int = 99,
    has_manage_messages: bool = False,
    role_ids: list[int] | None = None,
    channel_manage_messages: bool | None = None,
) -> MagicMock:
    """`channel_manage_messages` defaults to mirroring `has_manage_messages`
    (no channel-specific override in play); pass it explicitly to set up
    a channel permission overwrite that diverges from the guild-wide
    permission."""
    message = MagicMock()
    message.channel = MagicMock(id=channel_id)
    message.author = MagicMock(spec=discord.Member)
    message.author.guild_permissions = discord.Permissions(manage_messages=has_manage_messages)
    message.author.roles = [MagicMock(id=rid) for rid in (role_ids or [])]
    effective = has_manage_messages if channel_manage_messages is None else channel_manage_messages
    message.channel.permissions_for.return_value = discord.Permissions(
        manage_messages=effective
    )
    return message


def test_exempt_channel_is_always_exempt() -> None:
    message = _fake_message(channel_id=CHANNEL_ID)

    assert is_exempt(
        message,
        exempt_role_ids=set(),
        exempt_channel_ids={CHANNEL_ID},
        bypass_if_manage_messages=False,
    )


def test_manage_messages_bypasses_by_default() -> None:
    message = _fake_message(has_manage_messages=True)

    assert is_exempt(
        message, exempt_role_ids=set(), exempt_channel_ids=set(), bypass_if_manage_messages=True
    )


def test_manage_messages_bypass_can_be_disabled() -> None:
    message = _fake_message(has_manage_messages=True)

    assert not is_exempt(
        message, exempt_role_ids=set(), exempt_channel_ids=set(), bypass_if_manage_messages=False
    )


def test_exempt_role_is_exempt() -> None:
    message = _fake_message(role_ids=[ROLE_ID])

    assert is_exempt(
        message,
        exempt_role_ids={ROLE_ID},
        exempt_channel_ids=set(),
        bypass_if_manage_messages=False,
    )


def test_ordinary_member_in_ordinary_channel_is_not_exempt() -> None:
    message = _fake_message()

    assert not is_exempt(
        message, exempt_role_ids=set(), exempt_channel_ids=set(), bypass_if_manage_messages=True
    )


def test_manage_messages_denied_in_this_channel_does_not_bypass() -> None:
    """Regression test: this function's own docstring says the bypass is
    for "anyone who can already manually delete messages in this
    channel" -- but the old check read `author.guild_permissions`, the
    guild-wide permission, ignoring this channel's own overwrites. A
    member with manage_messages guild-wide but explicitly *denied* it in
    this specific channel (e.g. a read-only announcements channel) can't
    actually delete messages here, so they must not be exempted here."""
    message = _fake_message(has_manage_messages=True, channel_manage_messages=False)

    assert not is_exempt(
        message, exempt_role_ids=set(), exempt_channel_ids=set(), bypass_if_manage_messages=True
    )


def test_manage_messages_granted_only_via_channel_overwrite_does_bypass() -> None:
    """The flip side: a member without manage_messages guild-wide, but
    granted it via a channel-specific permission overwrite (e.g. a
    helper role scoped to one channel), CAN manually delete messages
    here -- must be exempted here even though their guild-wide
    permission says no."""
    message = _fake_message(has_manage_messages=False, channel_manage_messages=True)

    assert is_exempt(
        message, exempt_role_ids=set(), exempt_channel_ids=set(), bypass_if_manage_messages=True
    )
