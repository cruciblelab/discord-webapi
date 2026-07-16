"""Exercises discord_webapi.tools.migrate against real (in-memory)
SQLite databases -- reflection, table creation, row copying, checkpoint,
and restore all touch real SQLAlchemy connections, not mocks."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from discord_webapi.storage.sql import SessionRow, SQLSessionStore
from discord_webapi.storage.sql import create_all as create_all_tables
from discord_webapi.tools import migrate
from discord_webapi.tools._sql_dump import redact


def _sqlite_url(path: Path, name: str) -> str:
    return f"sqlite+aiosqlite:///{path / name}"


async def _seed_session(url: str, session_id: str = "abc123") -> None:
    engine = create_async_engine(url)
    await create_all_tables(engine)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db:
        db.add(
            SessionRow(
                session_id=session_id,
                user_id=1,
                username="tester",
                global_name=None,
                avatar=None,
                guild_ids=[1, 2, 3],
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC),
                encrypted_access_token=b"enc-access",
                encrypted_refresh_token=b"enc-refresh",
                discord_token_expires_at=datetime.now(UTC),
            )
        )
        await db.commit()
    await engine.dispose()


async def test_run_migration_copies_all_rows(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    await _seed_session(source_url)

    await migrate.run_migration(
        source_url=source_url,
        dest_url=dest_url,
        assume_yes=True,
        checkpoint=True,
        checkpoint_dir=tmp_path,
    )

    dest_engine = create_async_engine(dest_url)
    store = SQLSessionStore(dest_engine)
    session = await store.get("abc123")
    assert session is not None
    assert session.user_id == 1
    assert session.guild_ids == [1, 2, 3]
    assert session.encrypted_access_token == b"enc-access"
    await dest_engine.dispose()


async def test_run_migration_writes_a_checkpoint_file(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    await _seed_session(source_url)

    await migrate.run_migration(
        source_url=source_url,
        dest_url=dest_url,
        assume_yes=True,
        checkpoint=True,
        checkpoint_dir=tmp_path,
    )

    checkpoints = list(tmp_path.glob("dwa_migrate_checkpoint_*.json"))
    assert len(checkpoints) == 1


async def test_no_checkpoint_skips_the_checkpoint_file(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    await _seed_session(source_url)

    await migrate.run_migration(
        source_url=source_url,
        dest_url=dest_url,
        assume_yes=True,
        checkpoint=False,
        checkpoint_dir=tmp_path,
    )

    assert list(tmp_path.glob("dwa_migrate_checkpoint_*.json")) == []


async def test_restore_reverts_to_pre_migration_state(tmp_path: Path) -> None:
    """The full safety story: migrate into an empty destination (checkpoint
    captures "empty"), simulate a bad extra write after the fact, restore
    -- both the migrated row AND the bad row must be gone afterwards,
    since the checkpoint correctly captured "nothing was here before"."""
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    await _seed_session(source_url)

    await migrate.run_migration(
        source_url=source_url,
        dest_url=dest_url,
        assume_yes=True,
        checkpoint=True,
        checkpoint_dir=tmp_path,
    )
    checkpoint_path = next(tmp_path.glob("dwa_migrate_checkpoint_*.json"))

    # simulate a bad write happening after the migration
    await _seed_session(dest_url, session_id="bad-corrupt-row")

    await migrate.restore_checkpoint(
        checkpoint_path=checkpoint_path, dest_url=dest_url, assume_yes=True
    )

    dest_engine = create_async_engine(dest_url)
    store = SQLSessionStore(dest_engine)
    assert await store.get("abc123") is None
    assert await store.get("bad-corrupt-row") is None
    await dest_engine.dispose()


async def test_restore_preserves_rows_that_existed_before_migration(tmp_path: Path) -> None:
    """If the destination already had data before migrating (not the
    empty-destination case above), the checkpoint must capture that data
    so restoring brings it back, not wipe it to empty."""
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    await _seed_session(source_url, session_id="from-source")
    await _seed_session(dest_url, session_id="pre-existing-in-dest")

    await migrate.run_migration(
        source_url=source_url,
        dest_url=dest_url,
        assume_yes=True,
        checkpoint=True,
        checkpoint_dir=tmp_path,
    )
    checkpoint_path = next(tmp_path.glob("dwa_migrate_checkpoint_*.json"))

    await migrate.restore_checkpoint(
        checkpoint_path=checkpoint_path, dest_url=dest_url, assume_yes=True
    )

    dest_engine = create_async_engine(dest_url)
    store = SQLSessionStore(dest_engine)
    assert await store.get("pre-existing-in-dest") is not None
    assert await store.get("from-source") is None  # the migrated row is gone again
    await dest_engine.dispose()


async def test_empty_source_database_is_a_noop(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "empty_source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    # create the source engine/file but never call create_all -- zero tables
    create_async_engine(source_url)

    await migrate.run_migration(
        source_url=source_url,
        dest_url=dest_url,
        assume_yes=True,
        checkpoint=True,
        checkpoint_dir=tmp_path,
    )

    assert list(tmp_path.glob("dwa_migrate_checkpoint_*.json")) == []


def test_redact_hides_the_password() -> None:
    assert redact("mysql+aiomysql://user:secret@host/db") == "mysql+aiomysql://user:***@host/db"


def test_redact_leaves_urls_without_credentials_alone() -> None:
    assert redact("sqlite+aiosqlite:///local.sqlite3") == "sqlite+aiosqlite:///local.sqlite3"


def test_cli_run_requires_from_and_to() -> None:
    with pytest.raises(SystemExit):
        migrate.main(["run"])


def test_cli_restore_requires_checkpoint_file_and_to() -> None:
    with pytest.raises(SystemExit):
        migrate.main(["restore"])
