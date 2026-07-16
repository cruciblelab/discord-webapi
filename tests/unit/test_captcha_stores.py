"""Exercises Memory/SQL CaptchaStore and VerificationStore -- CRUD only,
provider logic (issue/verify) is covered separately in
tests/unit/test_captcha_providers.py."""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from discord_webapi.captcha.memory import MemoryCaptchaStore, MemoryVerificationStore
from discord_webapi.captcha.models import CaptchaChallenge, PendingCaptcha, VerificationRequest
from discord_webapi.captcha.sql import SQLCaptchaStore, SQLVerificationStore


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def _pending(challenge_id: str = "c1", answer: str = "42") -> PendingCaptcha:
    now = datetime.now(UTC)
    return PendingCaptcha(
        challenge_id=challenge_id,
        kind="math",
        answer=answer,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def _verification(token: str = "t1", user_id: int = 100) -> VerificationRequest:
    now = datetime.now(UTC)
    return VerificationRequest(
        token=token,
        user_id=user_id,
        guild_id=999,
        purpose="giveaway_entry",
        metadata={"giveaway_id": "abc"},
        challenge=CaptchaChallenge(challenge_id="c1", kind="math", prompt="1 + 1 = ?"),
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )


# -- MemoryCaptchaStore --


async def test_memory_captcha_store_create_and_get() -> None:
    store = MemoryCaptchaStore()
    await store.create(_pending())

    fetched = await store.get("c1")

    assert fetched is not None
    assert fetched.answer == "42"
    assert fetched.attempts == 0


async def test_memory_captcha_store_get_missing_returns_none() -> None:
    store = MemoryCaptchaStore()

    assert await store.get("nope") is None


async def test_memory_captcha_store_increment_attempts() -> None:
    store = MemoryCaptchaStore()
    await store.create(_pending())

    first = await store.increment_attempts("c1")
    second = await store.increment_attempts("c1")

    assert first == 1
    assert second == 2


async def test_memory_captcha_store_increment_attempts_on_missing_returns_zero() -> None:
    store = MemoryCaptchaStore()

    assert await store.increment_attempts("nope") == 0


async def test_memory_captcha_store_delete() -> None:
    store = MemoryCaptchaStore()
    await store.create(_pending())

    await store.delete("c1")

    assert await store.get("c1") is None


# -- MemoryVerificationStore --


async def test_memory_verification_store_create_and_get() -> None:
    store = MemoryVerificationStore()
    await store.create(_verification())

    fetched = await store.get("t1")

    assert fetched is not None
    assert fetched.user_id == 100
    assert fetched.verified is False


async def test_memory_verification_store_mark_verified() -> None:
    store = MemoryVerificationStore()
    await store.create(_verification())

    await store.mark_verified("t1")

    fetched = await store.get("t1")
    assert fetched is not None
    assert fetched.verified is True


async def test_memory_verification_store_delete() -> None:
    store = MemoryVerificationStore()
    await store.create(_verification())

    await store.delete("t1")

    assert await store.get("t1") is None


# -- SQLCaptchaStore --


async def test_sql_captcha_store_create_and_get(engine: AsyncEngine) -> None:
    store = SQLCaptchaStore(engine)
    await store.create_all()
    await store.create(_pending())

    fetched = await store.get("c1")

    assert fetched is not None
    assert fetched.answer == "42"
    assert fetched.kind == "math"


async def test_sql_captcha_store_increment_attempts(engine: AsyncEngine) -> None:
    store = SQLCaptchaStore(engine)
    await store.create_all()
    await store.create(_pending())

    count = await store.increment_attempts("c1")

    assert count == 1
    fetched = await store.get("c1")
    assert fetched is not None
    assert fetched.attempts == 1


async def test_sql_captcha_store_delete(engine: AsyncEngine) -> None:
    store = SQLCaptchaStore(engine)
    await store.create_all()
    await store.create(_pending())

    await store.delete("c1")

    assert await store.get("c1") is None


# -- SQLVerificationStore --


async def test_sql_verification_store_create_and_get(engine: AsyncEngine) -> None:
    store = SQLVerificationStore(engine)
    await store.create_all()
    await store.create(_verification())

    fetched = await store.get("t1")

    assert fetched is not None
    assert fetched.user_id == 100
    assert fetched.guild_id == 999
    assert fetched.purpose == "giveaway_entry"
    assert fetched.metadata == {"giveaway_id": "abc"}
    assert fetched.challenge.challenge_id == "c1"
    assert fetched.verified is False


async def test_sql_verification_store_round_trips_a_none_challenge(engine: AsyncEngine) -> None:
    """An account-only / click-only gate stores a verification with no
    captcha challenge -- challenge_json is nullable and must round-trip."""
    store = SQLVerificationStore(engine)
    await store.create_all()
    now = datetime.now(UTC)
    request = VerificationRequest(
        token="t-no-captcha",
        user_id=100,
        purpose="account_only",
        challenge=None,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    await store.create(request)

    fetched = await store.get("t-no-captcha")

    assert fetched is not None
    assert fetched.challenge is None


async def test_sql_verification_store_mark_verified(engine: AsyncEngine) -> None:
    store = SQLVerificationStore(engine)
    await store.create_all()
    await store.create(_verification())

    await store.mark_verified("t1")

    fetched = await store.get("t1")
    assert fetched is not None
    assert fetched.verified is True


async def test_sql_verification_store_delete(engine: AsyncEngine) -> None:
    store = SQLVerificationStore(engine)
    await store.create_all()
    await store.create(_verification())

    await store.delete("t1")

    assert await store.get("t1") is None
