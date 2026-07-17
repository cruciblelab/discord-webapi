from datetime import UTC, datetime, timedelta

import pytest

import discord_webapi.storage as storage_module
from discord_webapi.exceptions import SessionExpiredError
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


async def test_mutating_the_object_passed_to_create_does_not_corrupt_the_store() -> None:
    """Regression test: `create`/`get` used to alias the exact `Session`
    object handed in/out, unlike every other Memory*Store in storage/
    memory.py (all of which deepcopy on write and read) -- a caller
    mutating a `Session` it still held a reference to silently corrupted
    "persisted" state with no `update()` call ever made."""
    store = MemorySessionStore()
    session = _make_session()
    await store.create(session)

    session.username = "mutated-without-update"  # no store.update() call

    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.username != "mutated-without-update"


async def test_mutating_a_fetched_session_does_not_corrupt_the_store() -> None:
    store = MemorySessionStore()
    await store.create(_make_session())

    fetched = await store.get(_make_session().session_id)
    assert fetched is not None
    fetched.username = "mutated-via-get-return-value"

    refetched = await store.get(fetched.session_id)
    assert refetched is not None
    assert refetched.username != "mutated-via-get-return-value"


async def test_update_overwrites_existing_session() -> None:
    store = MemorySessionStore()
    session = _make_session()
    await store.create(session)

    updated = session.model_copy(update={"encrypted_access_token": b"new-access"})
    await store.update(updated)

    fetched = await store.get(session.session_id)
    assert fetched is not None
    assert fetched.encrypted_access_token == b"new-access"


async def test_update_of_a_deleted_session_raises_instead_of_resurrecting_it() -> None:
    """A concurrent delete() (e.g. logout from another tab) between a
    caller's read and its update() must not silently recreate the row --
    matches SQLSessionStore, and is what lets `_ensure_fresh_discord_token`
    treat this the same as an already-expired session instead of either
    reviving a logged-out session (the old Memory behavior) or crashing
    with an uncaught error (the old SQL behavior, wrong exception type)."""
    store = MemorySessionStore()
    session = _make_session()
    await store.create(session)
    await store.delete(session.session_id)

    with pytest.raises(SessionExpiredError, match="does not exist"):
        await store.update(session)

    assert await store.get(session.session_id) is None


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
