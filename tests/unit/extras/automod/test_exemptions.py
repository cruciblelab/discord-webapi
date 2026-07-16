from unittest.mock import MagicMock

import discord

from discord_webapi.extras.automod.exemptions import is_exempt

CHANNEL_ID = 1
ROLE_ID = 2


def _fake_message(
    *, channel_id: int = 99, has_manage_messages: bool = False, role_ids: list[int] | None = None
) -> MagicMock:
    message = MagicMock()
    message.channel = MagicMock(id=channel_id)
    message.author = MagicMock(spec=discord.Member)
    message.author.guild_permissions = discord.Permissions(manage_messages=has_manage_messages)
    message.author.roles = [MagicMock(id=rid) for rid in (role_ids or [])]
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
