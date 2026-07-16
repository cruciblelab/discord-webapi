import asyncio

from discord_webapi.authz.app_roles import AppRoleCache
from discord_webapi.authz.models import AppRole
from discord_webapi.storage.memory import MemoryAuthzStore
from discord_webapi.transport import InProcessTransport


def _role(guild_id: int = 1, name: str = "moderator", **kwargs: object) -> AppRole:
    return AppRole(guild_id=guild_id, name=name, **kwargs)  # type: ignore[arg-type]


async def test_memory_authz_store_set_and_list() -> None:
    store = MemoryAuthzStore()
    role = _role(discord_role_ids=[10], user_ids=[42])

    await store.set_app_role(role)
    roles = await store.get_all_app_roles(1)

    assert len(roles) == 1
    assert roles[0].name == "moderator"
    assert roles[0].user_ids == [42]


async def test_memory_authz_store_filters_by_guild() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role(guild_id=1))
    await store.set_app_role(_role(guild_id=2))

    assert len(await store.get_all_app_roles(1)) == 1
    assert len(await store.get_all_app_roles(2)) == 1


async def test_memory_authz_store_set_overwrites_same_name() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role(user_ids=[1]))
    await store.set_app_role(_role(user_ids=[2]))

    roles = await store.get_all_app_roles(1)
    assert len(roles) == 1
    assert roles[0].user_ids == [2]


async def test_memory_authz_store_delete() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role())

    await store.delete_app_role(1, "moderator")

    assert await store.get_all_app_roles(1) == []


async def test_cache_user_has_role_via_user_id() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role(user_ids=[42]))
    cache = AppRoleCache(InProcessTransport(), store)

    assert await cache.user_has_role(1, "moderator", user_id=42, discord_role_ids=[]) is True
    assert await cache.user_has_role(1, "moderator", user_id=99, discord_role_ids=[]) is False


async def test_cache_user_has_role_via_discord_role_id() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role(discord_role_ids=[555]))
    cache = AppRoleCache(InProcessTransport(), store)

    assert await cache.user_has_role(1, "moderator", user_id=1, discord_role_ids=[555]) is True
    assert await cache.user_has_role(1, "moderator", user_id=1, discord_role_ids=[1]) is False


async def test_cache_unknown_role_name_is_false() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role())
    cache = AppRoleCache(InProcessTransport(), store)

    assert await cache.user_has_role(1, "does-not-exist", user_id=1, discord_role_ids=[]) is False


async def test_cache_caches_list_within_ttl() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role())
    cache = AppRoleCache(InProcessTransport(), store, ttl_seconds=60)

    first = await cache.list_roles(1)
    await store.set_app_role(_role(user_ids=[999]))  # bypass cache, write directly
    second = await cache.list_roles(1)

    assert first == second  # still cached, store write not yet visible


async def test_cache_set_app_role_invalidates_immediately() -> None:
    store = MemoryAuthzStore()
    cache = AppRoleCache(InProcessTransport(), store, ttl_seconds=60)
    await cache.list_roles(1)  # warm the cache with an empty result

    await cache.set_app_role(_role(user_ids=[42]))

    roles = await cache.list_roles(1)
    assert roles[0].user_ids == [42]


async def test_cache_delete_app_role_invalidates_immediately() -> None:
    store = MemoryAuthzStore()
    cache = AppRoleCache(InProcessTransport(), store, ttl_seconds=60)
    await cache.set_app_role(_role())

    await cache.delete_app_role(1, "moderator")

    assert await cache.list_roles(1) == []


async def test_a_second_cache_sharing_the_same_transport_sees_live_updates() -> None:
    """Regression: AppRoleCache used to only invalidate its own in-process
    dict on write, with no Transport event -- a bot process (enforcing
    required_app_role) and a web replica (enforcing require_app_role) each
    hold their own instance in `for_bot_process`/`for_web_process`
    deployments, so a revoke made through one used to stay invisible to
    the other for up to `ttl_seconds`. Same live-update guarantee as
    GuildRateLimiter/EscalationEngine/GuildMemberCache."""
    transport = InProcessTransport()
    store = MemoryAuthzStore()
    writer = AppRoleCache(transport, store, ttl_seconds=60)
    reader = AppRoleCache(transport, store, ttl_seconds=60)

    # reader warms its cache with the (currently empty) role list
    assert await reader.list_roles(1) == []

    await writer.set_app_role(_role(user_ids=[42]))
    await asyncio.sleep(0.05)  # let InProcessTransport's fire-and-forget dispatch run

    roles = await reader.list_roles(1)
    assert roles[0].user_ids == [42]
