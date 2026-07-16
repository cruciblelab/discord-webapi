"""`discord-webapi-migrate` -- move all data from one SQL database to
another (e.g. a local SQLite file to MariaDB/Postgres for production).

Engine-agnostic and schema-agnostic on purpose: it never imports any of
this library's own ORM row classes (`storage.sql.SessionRow`, etc.). It
reflects whatever tables actually exist in the SOURCE database via
SQLAlchemy's own introspection, creates matching tables in the
DESTINATION if they aren't there yet, and copies every row. This means it
works identically for the core stores, `discord_webapi.escalation`'s
tables, `discord_webapi.extras.warn`'s `SQLWarnStore` table, and any
third-party extension's own SQL-backed store -- none of them need to be
known about in advance.

Safety, by design:
- Read-only against the source. Nothing here ever writes to `--from`.
- Requires typed confirmation before touching the destination unless
  `--yes` is passed (meant for scripted/repeat runs, not first use).
- **Checkpoint ON by default**: before writing anything, every row
  currently in the destination's matching tables (if any -- e.g. you're
  re-running against a database that already has some data) is dumped to
  a local JSON file. `discord-webapi-migrate restore <checkpoint-file>`
  restores exactly that state. `--no-checkpoint` skips this (faster for
  repeat runs against a destination you know is empty/disposable).
- This tool's checkpoint only covers discord-webapi's own tables. It is
  NOT a substitute for your own database backup (a full `mysqldump`/
  `pg_dump`/file copy) -- take one before running this against anything
  that matters. See `discord_webapi.tools.backup` for a standalone,
  scoped (whole DB / one guild / a date range) backup file you can keep
  around independently of a migration.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from discord_webapi.tools._sql_dump import (
    confirm,
    delete_rows,
    ensure_table,
    read_rows,
    redact,
    reflect,
    table_exists,
    write_rows,
)
from discord_webapi.tools._sql_dump import dumps as dump_json
from discord_webapi.tools._sql_dump import loads as load_json


async def _write_checkpoint(dest_engine: AsyncEngine, tables: list[Table], path: Path) -> None:
    snapshot: dict[str, list[dict[str, object]]] = {}
    for table in tables:
        if await table_exists(dest_engine, table.name):
            snapshot[table.name] = await read_rows(dest_engine, table)
        else:
            snapshot[table.name] = []
    path.write_text(dump_json(snapshot), encoding="utf-8")


async def run_migration(
    *,
    source_url: str,
    dest_url: str,
    assume_yes: bool,
    checkpoint: bool,
    checkpoint_dir: Path,
) -> None:
    source_engine = create_async_engine(source_url)
    dest_engine = create_async_engine(dest_url)

    print(f"Kaynak (salt okunur):  {redact(source_url)}")
    print(f"Hedef (yazılacak):     {redact(dest_url)}")

    metadata = await reflect(source_engine)
    tables = list(metadata.tables.values())
    if not tables:
        print("Kaynak veritabanında hiç tablo bulunamadı -- yapılacak bir şey yok.")
        await source_engine.dispose()
        await dest_engine.dispose()
        return

    print(f"\n{len(tables)} tablo bulundu:")
    row_counts: dict[str, int] = {}
    for table in tables:
        rows = await read_rows(source_engine, table)
        row_counts[table.name] = len(rows)
        print(f"  - {table.name}: {len(rows)} satır")

    print(
        "\nUYARI: Bu araç sadece discord-webapi'nin kendi tablolarını taşır. "
        "Kritik bir taşıma yapıyorsan bu işlemden ÖNCE veritabanının kendi "
        "yedekleme aracıyla (mysqldump/pg_dump/dosya kopyası) tam bir yedek al -- "
        "checkpoint (aşağıda) sadece discord-webapi tablolarını kapsıyor, "
        "genel bir veritabanı yedeği DEĞİL."
    )

    proceed = confirm(
        f"\n{sum(row_counts.values())} satır '{redact(dest_url)}' hedefine "
        "yazılacak. Devam edilsin mi? [y/N] ",
        assume_yes=assume_yes,
    )
    if not proceed:
        print("İptal edildi.")
        await source_engine.dispose()
        await dest_engine.dispose()
        return

    checkpoint_path: Path | None = None
    if checkpoint:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        checkpoint_path = checkpoint_dir / f"dwa_migrate_checkpoint_{stamp}.json"
        print(f"\nHedefin şu anki durumu kaydediliyor: {checkpoint_path}")
        await _write_checkpoint(dest_engine, tables, checkpoint_path)
        print(
            "Checkpoint alındı. Bir sorun olursa: "
            f"discord-webapi-migrate restore {checkpoint_path} --to <hedef-url>"
        )
    else:
        print("\n--no-checkpoint verildi: hedefin ön-durumu kaydedilmiyor.")

    print("\nTaşıma başlıyor...")
    for table in tables:
        await ensure_table(dest_engine, table)
        rows = await read_rows(source_engine, table)
        await write_rows(dest_engine, table, rows)
        print(f"  - {table.name}: {len(rows)} satır yazıldı")

    print("\nTamamlandı.")
    await source_engine.dispose()
    await dest_engine.dispose()


async def restore_checkpoint(*, checkpoint_path: Path, dest_url: str, assume_yes: bool) -> None:
    snapshot = load_json(checkpoint_path.read_text(encoding="utf-8"))
    dest_engine = create_async_engine(dest_url)
    metadata = await reflect(dest_engine)

    print(f"Checkpoint: {checkpoint_path}")
    print(f"Hedef (yazılacak): {redact(dest_url)}")
    print(f"{len(snapshot)} tablo geri yüklenecek:")
    for name, rows in snapshot.items():
        print(f"  - {name}: {len(rows)} satır")

    proceed = confirm(
        "\nBu, hedefteki bu tabloların İÇERİĞİNİ checkpoint anındaki haline "
        "geri döndürecek (mevcut satırlar silinip checkpoint'tekiler yazılacak). "
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
            print(f"  - {name}: hedefte bu tablo yok, atlanıyor")
            continue
        await delete_rows(dest_engine, table)
        await write_rows(dest_engine, table, rows)
        print(f"  - {name}: {len(rows)} satır geri yüklendi")

    print("\nGeri yükleme tamamlandı.")
    await dest_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    import asyncio

    parser = argparse.ArgumentParser(
        prog="discord-webapi-migrate",
        description="Move discord-webapi's SQL data from one database to another.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Migrate all tables from one database to another.")
    run.add_argument("--from", dest="source_url", required=True, help="Source SQLAlchemy URL.")
    run.add_argument("--to", dest="dest_url", required=True, help="Destination SQLAlchemy URL.")
    run.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt (for scripted runs)."
    )
    run.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Skip taking a pre-migration checkpoint of the destination's current state.",
    )
    run.add_argument(
        "--checkpoint-dir",
        default=".",
        help="Directory to write the checkpoint file into (default: current directory).",
    )

    restore = sub.add_parser(
        "restore", help="Restore a destination database from a checkpoint file."
    )
    restore.add_argument("checkpoint_file", help="Path to a checkpoint JSON file.")
    restore.add_argument("--to", dest="dest_url", required=True, help="Destination SQLAlchemy URL.")
    restore.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    args = parser.parse_args(argv)

    if args.command == "run":
        asyncio.run(
            run_migration(
                source_url=args.source_url,
                dest_url=args.dest_url,
                assume_yes=args.yes,
                checkpoint=not args.no_checkpoint,
                checkpoint_dir=Path(args.checkpoint_dir),
            )
        )
        return 0
    if args.command == "restore":
        asyncio.run(
            restore_checkpoint(
                checkpoint_path=Path(args.checkpoint_file),
                dest_url=args.dest_url,
                assume_yes=args.yes,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
