import discord
import pytest

from discord_webapi.authz.cache import GuildMemberCache
from discord_webapi.authz.permissions import has_permission
from discord_webapi.transport import Event, InProcessTransport


def test_has_permission_administrator_shortcuts_everything() -> None:
    perms = discord.Permissions(administrator=True)
    assert has_permission(perms, "manage_guild") is True
    assert has_permission(perms, "kick_members") is True


def test_has_permission_checks_specific_flag() -> None:
    perms = discord.Permissions(manage_guild=True)
    assert has_permission(perms, "manage_guild") is True
    assert has_permission(perms, "kick_members") is False


def test_has_permission_unknown_name_is_false() -> None:
    perms = discord.Permissions()
    assert has_permission(perms, "not_a_real_permission") is False


@pytest.fixture
async def transport() -> InProcessTransport:
    t = InProcessTransport()
    await t.start()
    return t


async def test_cache_hits_transport_and_caches_result(transport: InProcessTransport) -> None:
    call_count = 0

    async def handle_get_member(payload: dict) -> dict:
        nonlocal call_count
        call_count += 1
        return {
            "found": True,
            "role_ids": [1, 2],
            "permissions": discord.Permissions(manage_guild=True).value,
        }

    transport.register_handler("get_member", handle_get_member)
    cache = GuildMemberCache(transport, ttl_seconds=60)

    info1 = await cache.get(guild_id=1, user_id=2)
    info2 = await cache.get(guild_id=1, user_id=2)

    assert call_count == 1
    assert info1 is not None
    assert info1.role_ids == [1, 2]
    assert info2 is info1


async def test_cache_returns_none_for_non_member(transport: InProcessTransport) -> None:
    async def handle_get_member(payload: dict) -> dict:
        return {"found": False}

    transport.register_handler("get_member", handle_get_member)
    cache = GuildMemberCache(transport)

    assert await cache.get(guild_id=1, user_id=999) is None


async def test_member_updated_event_invalidates_cache(transport: InProcessTransport) -> None:
    call_count = 0

    async def handle_get_member(payload: dict) -> dict:
        nonlocal call_count
        call_count += 1
        return {"found": True, "role_ids": [call_count], "permissions": 0}

    transport.register_handler("get_member", handle_get_member)
    cache = GuildMemberCache(transport, ttl_seconds=60)

    first = await cache.get(guild_id=1, user_id=2)
    assert first is not None
    assert first.role_ids == [1]

    await transport.publish(Event(type="member_updated", payload={"guild_id": 1, "user_id": 2}))
    import asyncio

    await asyncio.sleep(0.05)

    second = await cache.get(guild_id=1, user_id=2)
    assert second is not None
    assert second.role_ids == [2]
