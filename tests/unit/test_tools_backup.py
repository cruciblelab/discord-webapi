"""Exercises discord_webapi.tools.backup against real SQLite databases --
full backup, guild-scoped backup, date-scoped backup, list, and restore."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from discord_webapi.storage.sql import CommandOverrideRow, SQLCommandConfigStore
from discord_webapi.storage.sql import create_all as create_all_tables
from discord_webapi.tools import backup


def _sqlite_url(path: Path, name: str) -> str:
    return f"sqlite+aiosqlite:///{path / name}"


async def _seed(url: str) -> None:
    """3 rows across 2 guilds and 2 different updated_at dates."""
    engine = create_async_engine(url)
    await create_all_tables(engine)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with sessionmaker() as db:
        db.add(
            CommandOverrideRow(
                guild_id=111, command_name="ping", enabled=True, updated_at=now - timedelta(days=10)
            )
        )
        db.add(
            CommandOverrideRow(guild_id=111, command_name="warn", enabled=True, updated_at=now)
        )
        db.add(
            CommandOverrideRow(guild_id=222, command_name="ping", enabled=False, updated_at=now)
        )
        await db.commit()
    await engine.dispose()


async def test_full_backup_includes_all_rows(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "full.json"

    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=None,
        since=None,
        until=None,
        tables_filter=None,
        assume_yes=True,
    )

    snapshot = backup.load_json(out_path.read_text())
    assert len(snapshot["dwa_command_overrides"]) == 3


async def test_guild_scoped_backup_filters_by_guild_id(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "guild.json"

    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=111,
        since=None,
        until=None,
        tables_filter=None,
        assume_yes=True,
    )

    snapshot = backup.load_json(out_path.read_text())
    rows = snapshot["dwa_command_overrides"]
    assert len(rows) == 2
    assert all(r["guild_id"] == 111 for r in rows)


async def test_date_scoped_backup_filters_by_updated_at(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "recent.json"
    since = datetime.now(UTC) - timedelta(days=1)

    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=None,
        since=since,
        until=None,
        tables_filter=None,
        assume_yes=True,
    )

    snapshot = backup.load_json(out_path.read_text())
    # the row from 10 days ago must be excluded, the two recent ones kept
    assert len(snapshot["dwa_command_overrides"]) == 2


async def test_guild_and_date_scope_combine(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "combo.json"
    since = datetime.now(UTC) - timedelta(days=1)

    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=111,
        since=since,
        until=None,
        tables_filter=None,
        assume_yes=True,
    )

    snapshot = backup.load_json(out_path.read_text())
    rows = snapshot["dwa_command_overrides"]
    assert len(rows) == 1
    assert rows[0]["command_name"] == "warn"


async def test_tables_filter_restricts_to_named_tables(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "one_table.json"

    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=None,
        since=None,
        until=None,
        tables_filter=["dwa_command_overrides"],
        assume_yes=True,
    )

    snapshot = backup.load_json(out_path.read_text())
    assert set(snapshot.keys()) == {"dwa_command_overrides"}


async def test_restore_writes_rows_into_an_existing_table(tmp_path: Path) -> None:
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "full.json"
    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=None,
        since=None,
        until=None,
        tables_filter=None,
        assume_yes=True,
    )
    dest_engine = create_async_engine(dest_url)
    await create_all_tables(dest_engine)  # destination must already have the tables

    await backup.restore_backup(backup_path=out_path, dest_url=dest_url, assume_yes=True)

    store = SQLCommandConfigStore(dest_engine)
    overrides_111 = await store.get_all_overrides(111)
    overrides_222 = await store.get_all_overrides(222)
    assert {o.command_name for o in overrides_111} == {"ping", "warn"}
    assert {o.command_name for o in overrides_222} == {"ping"}
    await dest_engine.dispose()


async def test_restore_skips_a_table_missing_in_the_destination(tmp_path: Path) -> None:
    """A backup file has no schema info -- restoring into a database that
    never had the table can't create it. Must skip, not crash."""
    source_url = _sqlite_url(tmp_path, "source.sqlite3")
    dest_url = _sqlite_url(tmp_path, "dest_empty.sqlite3")
    await _seed(source_url)
    out_path = tmp_path / "full.json"
    await backup.create_backup(
        source_url=source_url,
        out_path=out_path,
        guild_id=None,
        since=None,
        until=None,
        tables_filter=None,
        assume_yes=True,
    )
    create_async_engine(dest_url)  # dest file exists but has zero tables

    # must not raise
    await backup.restore_backup(backup_path=out_path, dest_url=dest_url, assume_yes=True)


def test_list_backup_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_path = tmp_path / "b.json"
    out_path.write_text(backup.dump_json({"dwa_command_overrides": [{"a": 1}]}))

    backup.list_backup(backup_path=out_path)

    out = capsys.readouterr().out
    assert "dwa_command_overrides: 1 satır" in out


def test_cli_create_requires_from_and_out() -> None:
    with pytest.raises(SystemExit):
        backup.main(["create"])


def test_cli_restore_requires_backup_file_and_to() -> None:
    with pytest.raises(SystemExit):
        backup.main(["restore"])


def test_parse_iso_assumes_utc_when_naive() -> None:
    parsed = backup._parse_iso("2026-01-01T00:00:00")
    assert parsed.tzinfo is not None
