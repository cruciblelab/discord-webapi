"""CaptchaStore / VerificationStore backed by SQLAlchemy 2.0 async.

Requires the `discord-webapi[sql]` extra. **Own independent tables**, not
bolted onto `discord_webapi.storage.sql`'s shared schema -- importing this
module never creates a table for someone who only uses the in-memory
stores, same principle as `discord_webapi.escalation.sql`/
`extras.warn.SQLWarnStore`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from discord_webapi.captcha.models import CaptchaChallenge, PendingCaptcha, VerificationRequest

_TIMESTAMP = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class PendingCaptchaRow(Base):
    __tablename__ = "dwa_captcha_pending"

    challenge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    # Text, not a bounded String: the path-trace provider stores a
    # JSON-encoded expected answer here that's larger than a plain math
    # result.
    answer: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


class VerificationRequestRow(Base):
    __tablename__ = "dwa_captcha_verifications"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    purpose: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    challenge_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


class TrajectoryFingerprintRow(Base):
    __tablename__ = "dwa_captcha_trajectory_fingerprints"

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


def _as_utc(value: datetime) -> datetime:
    # SQLite doesn't preserve tzinfo across a round-trip -- see the same
    # normalization in discord_webapi/storage/sql.py.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SQLCaptchaStore:
    """CaptchaStore backed by SQLAlchemy 2.0 async. Call `create_all()`
    once at startup (or manage the tables via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create(self, pending: PendingCaptcha) -> None:
        async with self._sessionmaker() as db:
            db.add(
                PendingCaptchaRow(
                    challenge_id=pending.challenge_id,
                    kind=pending.kind,
                    answer=pending.answer,
                    attempts=pending.attempts,
                    created_at=pending.created_at,
                    expires_at=pending.expires_at,
                )
            )
            await db.commit()

    async def get(self, challenge_id: str) -> PendingCaptcha | None:
        async with self._sessionmaker() as db:
            row = await db.get(PendingCaptchaRow, challenge_id)
            if row is None:
                return None
            return PendingCaptcha(
                challenge_id=row.challenge_id,
                kind=row.kind,
                answer=row.answer,
                attempts=row.attempts,
                created_at=_as_utc(row.created_at),
                expires_at=_as_utc(row.expires_at),
            )

    async def increment_attempts(self, challenge_id: str) -> int:
        async with self._sessionmaker() as db:
            row = await db.get(PendingCaptchaRow, challenge_id)
            if row is None:
                return 0
            row.attempts += 1
            await db.commit()
            return row.attempts

    async def delete(self, challenge_id: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(PendingCaptchaRow, challenge_id)
            if row is not None:
                await db.delete(row)
                await db.commit()


class SQLVerificationStore:
    """VerificationStore backed by SQLAlchemy 2.0 async. Call
    `create_all()` once at startup (or manage the tables via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create(self, request: VerificationRequest) -> None:
        async with self._sessionmaker() as db:
            db.add(
                VerificationRequestRow(
                    token=request.token,
                    user_id=request.user_id,
                    guild_id=request.guild_id,
                    purpose=request.purpose,
                    metadata_json=request.metadata,
                    challenge_json=(
                        request.challenge.model_dump(mode="json")
                        if request.challenge is not None
                        else None
                    ),
                    verified=request.verified,
                    created_at=request.created_at,
                    expires_at=request.expires_at,
                )
            )
            await db.commit()

    async def get(self, token: str) -> VerificationRequest | None:
        async with self._sessionmaker() as db:
            row = await db.get(VerificationRequestRow, token)
            if row is None:
                return None
            return VerificationRequest(
                token=row.token,
                user_id=row.user_id,
                guild_id=row.guild_id,
                purpose=row.purpose,
                metadata=row.metadata_json,
                challenge=(
                    CaptchaChallenge.model_validate(row.challenge_json)
                    if row.challenge_json is not None
                    else None
                ),
                verified=row.verified,
                created_at=_as_utc(row.created_at),
                expires_at=_as_utc(row.expires_at),
            )

    async def mark_verified(self, token: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(VerificationRequestRow, token)
            if row is not None:
                row.verified = True
                await db.commit()

    async def delete(self, token: str) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(VerificationRequestRow, token)
            if row is not None:
                await db.delete(row)
                await db.commit()


class SQLTrajectoryFingerprintStore:
    """`TrajectoryFingerprintStore` backed by SQLAlchemy 2.0 async -- the
    multi-process-safe version of `MemoryTrajectoryFingerprintStore`, so a
    replayed fingerprint is caught even if it lands on a different web
    replica than the one that saw it first. Call `create_all()` once at
    startup (or manage the tables via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def seen_recently(self, fingerprint: str) -> bool:
        async with self._sessionmaker() as db:
            row = await db.get(TrajectoryFingerprintRow, fingerprint)
            if row is None:
                return False
            if _as_utc(row.expires_at) <= datetime.now(UTC):
                await db.delete(row)
                await db.commit()
                return False
            return True

    async def record(self, fingerprint: str, ttl: timedelta) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(TrajectoryFingerprintRow, fingerprint)
            expires_at = datetime.now(UTC) + ttl
            if row is None:
                db.add(TrajectoryFingerprintRow(fingerprint=fingerprint, expires_at=expires_at))
            else:
                row.expires_at = expires_at
            await db.commit()
