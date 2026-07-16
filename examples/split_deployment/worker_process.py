"""Optional third process type for a split deployment: a job worker.
Picks up long-running work enqueued via the dashboard's `POST
/api/guilds/{guild_id}/jobs/{job_type}` (see `web_process.py`) -- things
that don't belong on a request/response cycle, like a bulk moderation
action across a whole guild's member list.

Run as many of these as you want, on any machine, pointed at the same
Redis as `web_process.py` -- `RedisJobQueue` gives proper competing-
consumer semantics (unlike `RedisTransport`'s RPC), so scaling workers
horizontally is exactly this: run more of this same script.

Run:
    pip install -e ".[redis]"
    export REDIS_URL=redis://localhost:6379/0
    python examples/split_deployment/worker_process.py
"""

import asyncio
import os

from discord_webapi import RedisJobQueue
from discord_webapi.jobs import run_worker

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
queue = RedisJobQueue(redis_url)


async def handle_bulk_action(payload: dict) -> dict:
    # Real handlers would do the actual work here (e.g. call the bot
    # process over Transport/REST for anything Discord-side, or just
    # touch the database directly). Kept trivial for the example.
    count = payload.get("count", 0)
    await asyncio.sleep(1)
    return {"processed": count}


queue.register_worker("bulk_action", handle_bulk_action)

if __name__ == "__main__":
    asyncio.run(run_worker(queue))
