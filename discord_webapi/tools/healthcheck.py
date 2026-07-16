"""`discord-webapi-healthcheck` -- checks that the pieces a discord-webapi
deployment depends on are actually reachable: the SQL database, an
optional Redis instance (if you're running `RedisTransport`/
`RedisJobQueue`), and an optional HTTP endpoint (e.g. your own FastAPI
app's own health route, or the bot process's).

Meant for cron/monitoring/container-orchestrator use: exits `0` if every
requested check passes, `1` if any fails. `--json` prints one JSON object
per line instead of human-readable text, for log-shipping/monitoring
pipelines that parse stdout.

Each check is independent and optional -- pass only the URLs you have.
Running with no flags at all does nothing (there's nothing to check).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    elapsed_ms: float


async def check_database(url: str, *, timeout: float) -> CheckResult:
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    start = time.monotonic()
    engine = create_async_engine(url)
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return CheckResult("database", True, "bağlantı ve SELECT 1 başarılı", _elapsed_ms(start))
    except Exception as exc:  # noqa: BLE001 -- surfaced as a check result, not raised
        return CheckResult("database", False, f"{type(exc).__name__}: {exc}", _elapsed_ms(start))
    finally:
        await engine.dispose()


async def check_redis(url: str, *, timeout: float) -> CheckResult:
    import asyncio

    from redis.asyncio import Redis

    start = time.monotonic()
    client: Redis = Redis.from_url(url)
    try:
        async with asyncio.timeout(timeout):
            pong = await client.ping()
        if not pong:
            return CheckResult("redis", False, "PING yanıtı alınamadı", _elapsed_ms(start))
        return CheckResult("redis", True, "PING başarılı", _elapsed_ms(start))
    except Exception as exc:  # noqa: BLE001
        return CheckResult("redis", False, f"{type(exc).__name__}: {exc}", _elapsed_ms(start))
    finally:
        await client.aclose()


async def check_http(url: str, *, timeout: float) -> CheckResult:
    import httpx

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            return CheckResult(
                "http", False, f"HTTP {response.status_code}", _elapsed_ms(start)
            )
        return CheckResult("http", True, f"HTTP {response.status_code}", _elapsed_ms(start))
    except Exception as exc:  # noqa: BLE001
        return CheckResult("http", False, f"{type(exc).__name__}: {exc}", _elapsed_ms(start))


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


async def run_checks(
    *,
    database_url: str | None,
    redis_url: str | None,
    http_url: str | None,
    timeout: float,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    if database_url is not None:
        results.append(await check_database(database_url, timeout=timeout))
    if redis_url is not None:
        results.append(await check_redis(redis_url, timeout=timeout))
    if http_url is not None:
        results.append(await check_http(http_url, timeout=timeout))
    return results


def _print_human(results: list[CheckResult]) -> None:
    if not results:
        print("Kontrol edilecek bir şey verilmedi (--database-url/--redis-url/--http-url).")
        return
    for result in results:
        status = "OK  " if result.ok else "FAIL"
        print(f"[{status}] {result.name:<8} {result.elapsed_ms:>7.1f}ms  {result.detail}")


def _print_json(results: list[CheckResult]) -> None:
    for result in results:
        print(
            json.dumps(
                {
                    "name": result.name,
                    "ok": result.ok,
                    "detail": result.detail,
                    "elapsed_ms": result.elapsed_ms,
                }
            )
        )


def main(argv: list[str] | None = None) -> int:
    import asyncio

    parser = argparse.ArgumentParser(
        prog="discord-webapi-healthcheck",
        description=(
            "Check that discord-webapi's dependencies (database, optional Redis, "
            "optional HTTP endpoint) are reachable. Exits 0 if all requested checks "
            "pass, 1 otherwise."
        ),
    )
    parser.add_argument("--database-url", default=None, help="SQLAlchemy URL to check.")
    parser.add_argument("--redis-url", default=None, help="Redis URL to PING.")
    parser.add_argument("--http-url", default=None, help="HTTP URL to GET.")
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Per-check timeout in seconds (default: 5)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print one JSON object per line instead of text."
    )
    args = parser.parse_args(argv)

    results = asyncio.run(
        run_checks(
            database_url=args.database_url,
            redis_url=args.redis_url,
            http_url=args.http_url,
            timeout=args.timeout,
        )
    )

    if args.json:
        _print_json(results)
    else:
        _print_human(results)

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
