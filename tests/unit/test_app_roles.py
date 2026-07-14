from discord_webapi.authz.app_roles import AppRoleCache
from discord_webapi.authz.models import AppRole
from discord_webapi.storage.memory import MemoryAuthzStore


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
    cache = AppRoleCache(store)

    assert await cache.user_has_role(1, "moderator", user_id=42, discord_role_ids=[]) is True
    assert await cache.user_has_role(1, "moderator", user_id=99, discord_role_ids=[]) is False


async def test_cache_user_has_role_via_discord_role_id() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role(discord_role_ids=[555]))
    cache = AppRoleCache(store)

    assert await cache.user_has_role(1, "moderator", user_id=1, discord_role_ids=[555]) is True
    assert await cache.user_has_role(1, "moderator", user_id=1, discord_role_ids=[1]) is False


async def test_cache_unknown_role_name_is_false() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role())
    cache = AppRoleCache(store)

    assert await cache.user_has_role(1, "does-not-exist", user_id=1, discord_role_ids=[]) is False


async def test_cache_caches_list_within_ttl() -> None:
    store = MemoryAuthzStore()
    await store.set_app_role(_role())
    cache = AppRoleCache(store, ttl_seconds=60)

    first = await cache.list_roles(1)
    await store.set_app_role(_role(user_ids=[999]))  # bypass cache, write directly
    second = await cache.list_roles(1)

    assert first == second  # still cached, store write not yet visible


async def test_cache_set_app_role_invalidates_immediately() -> None:
    store = MemoryAuthzStore()
    cache = AppRoleCache(store, ttl_seconds=60)
    await cache.list_roles(1)  # warm the cache with an empty result

    await cache.set_app_role(_role(user_ids=[42]))

    roles = await cache.list_roles(1)
    assert roles[0].user_ids == [42]


async def test_cache_delete_app_role_invalidates_immediately() -> None:
    store = MemoryAuthzStore()
    cache = AppRoleCache(store, ttl_seconds=60)
    await cache.set_app_role(_role())

    await cache.delete_app_role(1, "moderator")

    assert await cache.list_roles(1) == []
