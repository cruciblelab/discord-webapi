from datetime import UTC, datetime, timedelta

import pytest

import discord_webapi.storage as storage_module
from discord_webapi.storage import MemorySessionStore, Session


def _make_session(session_id: str = "sess-1") -> Session:
    now = datetime.now(UTC)
    return Session(
        session_id=session_id,
        user_id=123,
        username="testuser",
        created_at=now,
        expires_at=now + timedelta(days=30),
        encrypted_access_token=b"enc-access",
        encrypted_refresh_token=b"enc-refresh",
        discord_token_expires_at=now + timedelta(minutes=10),
    )


async def test_create_and_get_round_trips() -> None:
    store = MemorySessionStore()
    session = _make_session()

    await store.create(session)
    fetched = await store.get(session.session_id)

    assert fetched == session


async def test_get_missing_session_returns_none() -> None:
    store = MemorySessionStore()

    assert await store.get("does-not-exist") is None


async def test_update_overwrites_existing_session() -> None:
    store = MemorySessionStore()
    session = _make_session()
    await store.create(session)

    updated = session.model_copy(update={"encrypted_access_token": b"new-access"})
    await store.update(updated)

    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.encrypted_access_token == b"new-access"


async def test_delete_removes_session() -> None:
    store = MemorySessionStore()
    session = _make_session()
    await store.create(session)

    await store.delete(session.session_id)

    assert await store.get(session.session_id) is None


async def test_list_by_user_returns_only_that_users_sessions() -> None:
    store = MemorySessionStore()
    mine_1 = _make_session("sess-1")
    mine_2 = _make_session("sess-2")
    other = _make_session("sess-3").model_copy(update={"user_id": 456})
    await store.create(mine_1)
    await store.create(mine_2)
    await store.create(other)

    sessions = await store.list_by_user(123)

    assert {s.session_id for s in sessions} == {"sess-1", "sess-2"}


def test_lazy_getattr_resolves_sql_stores() -> None:
    assert storage_module.SQLSessionStore is not None
    assert storage_module.SQLCommandConfigStore is not None
    assert storage_module.SQLAuthzStore is not None
    assert storage_module.SQLAuditStore is not None
    assert storage_module.SQLConsentStore is not None


def test_lazy_getattr_raises_for_unknown_name() -> None:
    with pytest.raises(AttributeError):
        storage_module.__getattr__("NotARealStore")
