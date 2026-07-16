"""`discord-webapi-backup` -- a standalone backup file you keep around,
independent of any migration. Same schema-agnostic reflection approach as
`discord_webapi.tools.migrate`: no ORM row classes imported, whatever
tables exist in the database are discovered and dumped.

Three scopes, combinable:
- **Full**: every row in every table (the default -- no filters given).
- **Guild-scoped** (`--guild-id N`): only rows from tables that have a
  `guild_id` column, filtered to that guild. Tables without a `guild_id`
  column (e.g. `dwa_sessions`, which is keyed by user, not guild) are
  included in full regardless -- there's no guild dimension to filter by.
- **Date-scoped** (`--since`/`--until`, ISO 8601): only rows whose
  timestamp column falls in that range. Each table's timestamp column is
  whichever of `created_at`/`updated_at`/`given_at`/`expires_at` it
  actually has (checked in that order); a table with none of those is
  included in full regardless -- there's no time dimension to filter by.

`discord-webapi-backup list <file>` shows what's inside a backup file
without restoring anything. `discord-webapi-backup restore <file> --to
<url>` writes it into a database (same delete-then-write-per-table
semantics as `migrate restore`). Restore needs the destination to
already have the matching tables (e.g. a database your bot has already
run against at least once) -- a backup file only stores rows, not
column/type definitions, so unlike `migrate` (which always has a live
source engine to reflect the real schema from) there's nothing to create
a missing table from here.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_
from sqlalchemy.ext.asyncio import create_async_engine

from discord_webapi.tools._sql_dump import (
    confirm,
    delete_rows,
    read_rows,
    redact,
    reflect,
    write_rows,
)
from discord_webapi.tools._sql_dump import dumps as dump_json
from discord_webapi.tools._sql_dump import loads as load_json

_TIMESTAMP_COLUMN_CANDIDATES = ("created_at", "updated_at", "given_at", "expires_at")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def create_backup(
    *,
    source_url: str,
    out_path: Path,
    guild_id: int | None,
    since: datetime | None,
    until: datetime | None,
    tables_filter: list[str] | None,
    assume_yes: bool,
) -> None:
    source_engine = create_async_engine(source_url)
    metadata = await reflect(source_engine)
    tables = list(metadata.tables.values())
    if tables_filter is not None:
        tables = [t for t in tables if t.name in tables_filter]

    if not tables:
        print("Eşleşen tablo yok -- yedeklenecek bir şey bulunamadı.")
        await source_engine.dispose()
        return

    print(f"Kaynak (salt okunur): {redact(source_url)}")
    if guild_id is not None:
        print(f"Kapsam: sadece guild_id={guild_id} (guild_id sütunu olmayan tablolar tam alınır)")
    if since is not None or until is not None:
        print(f"Kapsam: {since or '(başlangıç)'} .. {until or '(şimdi)'} arası")

    snapshot: dict[str, list[dict[str, object]]] = {}
    for table in tables:
        where = None
        conditions = []
        if guild_id is not None and "guild_id" in table.columns:
            conditions.append(table.c.guild_id == guild_id)
        if since is not None or until is not None:
            ts_column = next(
                (c for c in _TIMESTAMP_COLUMN_CANDIDATES if c in table.columns), None
            )
            if ts_column is not None:
                col = table.columns[ts_column]
                if since is not None:
                    conditions.append(col >= since)
                if until is not None:
                    conditions.append(col <= until)
        if conditions:
            where = and_(*conditions)
        rows = await read_rows(source_engine, table, where=where)
        snapshot[table.name] = rows
        print(f"  - {table.name}: {len(rows)} satır")

    total = sum(len(rows) for rows in snapshot.values())
    proceed = confirm(
        f"\n{total} satır '{out_path}' dosyasına yazılacak. Devam edilsin mi? [y/N] ",
        assume_yes=assume_yes,
    )
    if not proceed:
        print("İptal edildi.")
        await source_engine.dispose()
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dump_json(snapshot), encoding="utf-8")
    print(f"\nYedek yazıldı: {out_path}")
    await source_engine.dispose()


def list_backup(*, backup_path: Path) -> None:
    snapshot = load_json(backup_path.read_text(encoding="utf-8"))
    print(f"Yedek: {backup_path}")
    for name, rows in snapshot.items():
        print(f"  - {name}: {len(rows)} satır")
    print(f"Toplam: {sum(len(rows) for rows in snapshot.values())} satır")


async def restore_backup(*, backup_path: Path, dest_url: str, assume_yes: bool) -> None:
    snapshot = load_json(backup_path.read_text(encoding="utf-8"))
    dest_engine = create_async_engine(dest_url)
    metadata = await reflect(dest_engine)

    print(f"Yedek: {backup_path}")
    print(f"Hedef (yazılacak): {redact(dest_url)}")
    for name, rows in snapshot.items():
        print(f"  - {name}: {len(rows)} satır")

    proceed = confirm(
        "\nBu, hedefteki bu tabloların İÇERİĞİNİ yedek anındaki haline geri "
        "döndürecek (mevcut satırlar silinip yedektekiler yazılacak). "
        "Devam edilsin mi? [y/N] ",
        assume_yes=assume_yes,
    )
    if not proceed:
        print("İptal edildi.")
        await dest_engine.dispose()
        return

    for name, rows in snapshot.items():
        table = metadata.tables.get(name)
        if table is None:
            # A backup file only stores rows, not column/type definitions
            # -- unlike migrate.py (which always has a source engine to
            # reflect the real schema from), there's no schema to create a
            # missing table from here. Restore into a database that
            # already has the matching tables (e.g. one your bot has
            # already run against at least once, so quickstart()/
            # create_all() already made them).
            print(
                f"  - {name}: hedefte bu tablo yok, atlanıyor "
                "(önce tabloyu oluşturman gerekiyor)"
            )
            continue
        await delete_rows(dest_engine, table)
        await write_rows(dest_engine, table, rows)
        print(f"  - {name}: {len(rows)} satır geri yüklendi")

    print("\nGeri yükleme tamamlandı.")
    await dest_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    import asyncio

    parser = argparse.ArgumentParser(
        prog="discord-webapi-backup",
        description="Back up (and restore) discord-webapi's SQL data to/from a file.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a backup file.")
    create.add_argument("--from", dest="source_url", required=True, help="Source SQLAlchemy URL.")
    create.add_argument("--out", required=True, help="Path to write the backup file to.")
    create.add_argument(
        "--guild-id", type=int, default=None, help="Only back up this guild's rows."
    )
    create.add_argument("--since", default=None, help="Only rows on/after this ISO 8601 date.")
    create.add_argument("--until", default=None, help="Only rows on/before this ISO 8601 date.")
    create.add_argument(
        "--tables", default=None, help="Comma-separated table names to include (default: all)."
    )
    create.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    lst = sub.add_parser("list", help="Show what's inside a backup file.")
    lst.add_argument("backup_file", help="Path to a backup JSON file.")

    restore = sub.add_parser("restore", help="Restore a database from a backup file.")
    restore.add_argument("backup_file", help="Path to a backup JSON file.")
    restore.add_argument("--to", dest="dest_url", required=True, help="Destination SQLAlchemy URL.")
    restore.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    args = parser.parse_args(argv)

    if args.command == "create":
        asyncio.run(
            create_backup(
                source_url=args.source_url,
                out_path=Path(args.out),
                guild_id=args.guild_id,
                since=_parse_iso(args.since) if args.since else None,
                until=_parse_iso(args.until) if args.until else None,
                tables_filter=args.tables.split(",") if args.tables else None,
                assume_yes=args.yes,
            )
        )
        return 0
    if args.command == "list":
        list_backup(backup_path=Path(args.backup_file))
        return 0
    if args.command == "restore":
        asyncio.run(
            restore_backup(
                backup_path=Path(args.backup_file), dest_url=args.dest_url, assume_yes=args.yes
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
