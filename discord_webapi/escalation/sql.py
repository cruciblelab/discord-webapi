"""EscalationRuleStore / ViolationStore backed by SQLAlchemy 2.0 async.

Requires the `discord-webapi[sql]` extra. **Own independent tables**, not
bolted onto `discord_webapi.storage.sql`'s shared schema -- importing this
module never creates a table for someone who only uses the in-memory
stores, same principle as `discord_webapi.extras.warn.SQLWarnStore`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from discord_webapi.escalation.models import EscalationAction, EscalationRule, ViolationRecord

_TIMESTAMP = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class EscalationRuleRow(Base):
    __tablename__ = "dwa_escalation_rules"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    threshold: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(32))
    action_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(_TIMESTAMP)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ViolationRow(Base):
    __tablename__ = "dwa_escalation_violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TIMESTAMP)


def _as_utc(value: datetime) -> datetime:
    # SQLite doesn't preserve tzinfo across a round-trip -- see the same
    # normalization in discord_webapi/storage/sql.py.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _row_to_rule(row: EscalationRuleRow) -> EscalationRule:
    return EscalationRule(
        guild_id=row.guild_id,
        key=row.key,
        threshold=row.threshold,
        action=EscalationAction(row.action),
        action_minutes=row.action_minutes,
        reason=row.reason,
        updated_at=_as_utc(row.updated_at),
        updated_by_user_id=row.updated_by_user_id,
    )


class SQLEscalationRuleStore:
    """EscalationRuleStore backed by SQLAlchemy 2.0 async. Call
    `create_all()` once at startup (or manage the table via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_rules(self, guild_id: int, key: str) -> list[EscalationRule]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(EscalationRuleRow)
                .where(EscalationRuleRow.guild_id == guild_id, EscalationRuleRow.key == key)
                .order_by(EscalationRuleRow.threshold)
            )
            return [_row_to_rule(row) for row in result.scalars()]

    async def get_all_rules(self, guild_id: int) -> list[EscalationRule]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(EscalationRuleRow)
                .where(EscalationRuleRow.guild_id == guild_id)
                .order_by(EscalationRuleRow.key, EscalationRuleRow.threshold)
            )
            return [_row_to_rule(row) for row in result.scalars()]

    async def set_rule(self, rule: EscalationRule) -> None:
        key = (rule.guild_id, rule.key, rule.threshold)
        async with self._sessionmaker() as db:
            row = await db.get(EscalationRuleRow, key)
            if row is None:
                row = EscalationRuleRow(
                    guild_id=rule.guild_id, key=rule.key, threshold=rule.threshold
                )
                db.add(row)
            row.action = rule.action.value
            row.action_minutes = rule.action_minutes
            row.reason = rule.reason
            row.updated_at = rule.updated_at
            row.updated_by_user_id = rule.updated_by_user_id
            await db.commit()

    async def delete_rule(self, guild_id: int, key: str, threshold: int) -> None:
        async with self._sessionmaker() as db:
            row = await db.get(EscalationRuleRow, (guild_id, key, threshold))
            if row is not None:
                await db.delete(row)
                await db.commit()


class SQLViolationStore:
    """ViolationStore backed by SQLAlchemy 2.0 async. Call `create_all()`
    once at startup (or manage the table via Alembic)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def add(self, record: ViolationRecord) -> None:
        async with self._sessionmaker() as db:
            db.add(
                ViolationRow(
                    guild_id=record.guild_id,
                    user_id=record.user_id,
                    key=record.key,
                    source=record.source,
                    reason=record.reason,
                    created_at=record.created_at,
                )
            )
            await db.commit()

    async def count(self, guild_id: int, user_id: int, key: str) -> int:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(func.count()).where(
                    ViolationRow.guild_id == guild_id,
                    ViolationRow.user_id == user_id,
                    ViolationRow.key == key,
                )
            )
            return int(result.scalar_one())
