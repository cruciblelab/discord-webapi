"""Shared, schema-agnostic SQL read/write/(de)serialize helpers used by
both `migrate.py` and `backup.py`. Never imports any of this library's
own ORM row classes -- everything here works off of SQLAlchemy's own
table reflection, so it automatically covers core stores, `escalation`,
`extras.warn`'s `SQLWarnStore`, and any third-party extension's own
SQL-backed store without needing to know about them in advance.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine


class DumpFileError(Exception):
    """A checkpoint/backup JSON file is missing or unreadable. Callers catch
    this in their CLI `main()` to print a clean one-line error and exit 1,
    instead of letting a raw FileNotFoundError/JSONDecodeError traceback
    reach the terminal."""


async def reflect(engine: AsyncEngine) -> MetaData:
    metadata = MetaData()
    async with engine.connect() as conn:
        await conn.run_sync(metadata.reflect)
    return metadata


async def table_exists(engine: AsyncEngine, table_name: str) -> bool:
    metadata = await reflect(engine)
    return table_name in metadata.tables


async def read_rows(
    engine: AsyncEngine, table: Table, *, where: Any = None
) -> list[dict[str, Any]]:
    stmt = select(table)
    if where is not None:
        stmt = stmt.where(where)
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        return [dict(row._mapping) for row in result]


async def ensure_table(dest_engine: AsyncEngine, table: Table) -> None:
    async with dest_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))


async def write_rows(dest_engine: AsyncEngine, table: Table, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with dest_engine.begin() as conn:
        await conn.execute(insert(table), rows)


async def delete_rows(dest_engine: AsyncEngine, table: Table) -> None:
    async with dest_engine.begin() as conn:
        await conn.execute(table.delete())


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__datetime_iso__": value.isoformat()}
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    raise TypeError(f"Cannot serialize {value!r} for a dump file")


def json_object_hook(obj: dict[str, Any]) -> Any:
    if set(obj.keys()) == {"__bytes_hex__"}:
        return bytes.fromhex(obj["__bytes_hex__"])
    if set(obj.keys()) == {"__datetime_iso__"}:
        return datetime.fromisoformat(obj["__datetime_iso__"])
    return obj


def dumps(snapshot: dict[str, list[dict[str, Any]]]) -> str:
    return json.dumps(snapshot, default=json_default, indent=2)


def loads(text: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = json.loads(text, object_hook=json_object_hook)
    return result


def load_dump_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Reads and parses a checkpoint/backup JSON file, raising `DumpFileError`
    (a clean, catchable error) instead of a raw FileNotFoundError/
    JSONDecodeError traceback for the common CLI mistakes: wrong path, or a
    file that was never fully written (e.g. an interrupted `create`)."""
    if not path.exists():
        raise DumpFileError(f"Dosya bulunamadı: {path}")
    try:
        return loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DumpFileError(f"'{path}' geçerli bir JSON dosyası değil: {exc}") from exc


def redact(url: str) -> str:
    """Hides a password embedded in a DB URL (scheme://user:PASSWORD@host/db)
    before printing it to the terminal/logs."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, _, host_and_db = rest.partition("@")
    if ":" not in creds:
        return url
    user, _sep, _password = creds.partition(":")
    return f"{scheme}://{user}:***@{host_and_db}"


def confirm(prompt: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(prompt)
    except EOFError:
        # No interactive stdin (cron/CI/piped input) and --yes wasn't passed --
        # treat it as a declined confirmation rather than crashing with a
        # traceback. A destructive command should refuse by default, not fail
        # open.
        return False
    return answer.strip().lower() in ("y", "yes", "e", "evet")
