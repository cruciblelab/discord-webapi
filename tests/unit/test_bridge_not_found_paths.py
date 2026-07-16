"""Direct coverage of commands.bridge's "not cached" guard clauses --
these are exercised indirectly elsewhere (through bot/extension.py's RPC
handlers), but not the not-found branches specifically for every function.
"""

from types import SimpleNamespace

import discord

from discord_webapi.commands.bridge import (
    get_channel_permissions,
    get_member_permissions,
    get_member_roles,
    list_manageable_guilds,
)

GUILD_ID = 999
USER_ID = 42


def test_get_member_roles_unknown_guild_returns_none() -> None:
    bot = SimpleNamespace(get_guild=lambda gid: None)
    assert get_member_roles(bot, GUILD_ID, USER_ID) is None  # type: ignore[arg-type]


def test_get_member_roles_unknown_member_returns_none() -> None:
    guild = SimpleNamespace(get_member=lambda uid: None)
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    assert get_member_roles(bot, GUILD_ID, USER_ID) is None  # type: ignore[arg-type]


def test_get_member_permissions_unknown_guild_returns_none() -> None:
    bot = SimpleNamespace(get_guild=lambda gid: None)
    assert get_member_permissions(bot, GUILD_ID, USER_ID) is None  # type: ignore[arg-type]


def test_get_member_permissions_unknown_member_returns_none() -> None:
    guild = SimpleNamespace(get_member=lambda uid: None)
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    assert get_member_permissions(bot, GUILD_ID, USER_ID) is None  # type: ignore[arg-type]


def test_get_channel_permissions_unknown_guild_returns_none() -> None:
    bot = SimpleNamespace(get_guild=lambda gid: None)
    assert get_channel_permissions(bot, GUILD_ID, 1, USER_ID) is None  # type: ignore[arg-type]


def test_get_channel_permissions_unknown_member_returns_none() -> None:
    guild = SimpleNamespace(get_member=lambda uid: None)
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    assert get_channel_permissions(bot, GUILD_ID, 1, USER_ID) is None  # type: ignore[arg-type]


def test_get_channel_permissions_unknown_channel_returns_none() -> None:
    member = SimpleNamespace(guild_permissions=discord.Permissions.none())
    guild = SimpleNamespace(get_member=lambda uid: member, get_channel=lambda cid: None)
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    assert get_channel_permissions(bot, GUILD_ID, 1, USER_ID) is None  # type: ignore[arg-type]


def test_list_manageable_guilds_skips_guilds_the_bot_is_not_in() -> None:
    bot = SimpleNamespace(get_guild=lambda gid: None)
    assert list_manageable_guilds(bot, [GUILD_ID], USER_ID) == []  # type: ignore[arg-type]


def test_list_manageable_guilds_skips_guilds_the_user_is_not_a_member_of() -> None:
    guild = SimpleNamespace(get_member=lambda uid: None)
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    assert list_manageable_guilds(bot, [GUILD_ID], USER_ID) == []  # type: ignore[arg-type]
