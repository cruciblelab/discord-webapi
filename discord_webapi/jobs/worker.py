from __future__ import annotations

import asyncio

from discord_webapi.jobs.base import JobQueue


async def run_worker(queue: JobQueue) -> None:
    """Entry point for a standalone job-worker process: register your
    handlers on `queue` with `register_worker()`, then call this to start
    it and block until interrupted (Ctrl+C / SIGINT/SIGTERM cancels the
    enclosing `asyncio.run`). Pairs with `RedisJobQueue` so any number of
    these can run as separate processes/machines, horizontally scaled
    independent of whatever process enqueues jobs (the web dashboard, or
    `bot_process.py` in a split deployment, see `examples/split_deployment/`).
    """
    await queue.start()
    try:
        await asyncio.Event().wait()
    finally:
        await queue.stop()
