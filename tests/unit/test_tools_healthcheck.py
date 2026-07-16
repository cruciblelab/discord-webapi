"""Exercises discord_webapi.tools.healthcheck against a real SQLite
database, a real (loopback) HTTP server, and -- if reachable -- a real
Redis instance. Failure paths use unreachable targets rather than mocks."""

import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from redis.exceptions import RedisError

from discord_webapi.tools import healthcheck

REDIS_URL = os.environ.get("DWA_TEST_REDIS_URL", "redis://localhost:6379/15")


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path / 'hc.sqlite3'}"


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- required name from BaseHTTPRequestHandler
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def http_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join()


async def test_check_database_succeeds_against_a_real_sqlite_file(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from discord_webapi.storage.sql import create_all

    url = _sqlite_url(tmp_path)
    engine = create_async_engine(url)
    await create_all(engine)
    await engine.dispose()

    result = await healthcheck.check_database(url, timeout=5.0)
    assert result.ok
    assert result.name == "database"


async def test_check_database_fails_for_an_unreachable_directory() -> None:
    result = await healthcheck.check_database(
        "sqlite+aiosqlite:///does_not_exist_dir/hc.sqlite3", timeout=5.0
    )
    assert not result.ok
    assert "OperationalError" in result.detail


async def test_check_http_succeeds_against_a_real_server(http_server: str) -> None:
    result = await healthcheck.check_http(http_server, timeout=5.0)
    assert result.ok
    assert "200" in result.detail


async def test_check_http_fails_for_an_unreachable_port() -> None:
    result = await healthcheck.check_http("http://127.0.0.1:1/", timeout=1.0)
    assert not result.ok


async def test_check_redis_succeeds_against_a_real_redis() -> None:
    try:
        result = await healthcheck.check_redis(REDIS_URL, timeout=5.0)
    except RedisError:
        pytest.skip(f"No Redis reachable at {REDIS_URL} (set DWA_TEST_REDIS_URL)")
    assert result.ok


async def test_check_redis_fails_for_an_unreachable_port() -> None:
    result = await healthcheck.check_redis("redis://127.0.0.1:1/0", timeout=1.0)
    assert not result.ok


async def test_run_checks_only_runs_what_is_asked_for(tmp_path: Path) -> None:
    results = await healthcheck.run_checks(
        database_url=None, redis_url=None, http_url=None, timeout=5.0
    )
    assert results == []


async def test_run_checks_combines_database_and_http(
    tmp_path: Path, http_server: str
) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from discord_webapi.storage.sql import create_all

    url = _sqlite_url(tmp_path)
    engine = create_async_engine(url)
    await create_all(engine)
    await engine.dispose()

    results = await healthcheck.run_checks(
        database_url=url, redis_url=None, http_url=http_server, timeout=5.0
    )
    assert {r.name for r in results} == {"database", "http"}
    assert all(r.ok for r in results)


def test_cli_exits_zero_with_no_checks_requested() -> None:
    assert healthcheck.main([]) == 0


def test_cli_exits_one_on_a_failing_check() -> None:
    assert (
        healthcheck.main(
            ["--database-url", "sqlite+aiosqlite:///no/such/dir/hc.sqlite3", "--timeout", "1"]
        )
        == 1
    )


def test_cli_json_flag_prints_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    healthcheck.main(
        [
            "--database-url",
            "sqlite+aiosqlite:///no/such/dir/hc.sqlite3",
            "--timeout",
            "1",
            "--json",
        ]
    )
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["name"] == "database"
    assert parsed["ok"] is False
