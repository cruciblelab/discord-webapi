"""Web-only process for a large bot deployment: the FastAPI dashboard,
with no discord.Bot object at all -- every route in this package already
talks only to Transport/shared storage, never to a concrete bot. Run as
many of these as you want (separate processes, separate machines, behind
a load balancer), all pointed at the same Redis and database as the one
`bot_process.py`.

Run (as many times/replicas as you like):
    pip install -e ".[redis,sql]"                # from the repo root
    export DISCORD_CLIENT_ID=...
    export DISCORD_CLIENT_SECRET=...
    export DWA_FERNET_KEY=...
    export DASHBOARD_BASE_URL=https://dashboard.example.com
    export REDIS_URL=redis://localhost:6379/0
    export DATABASE_URL=postgresql+asyncpg://user:pass@host/db
    uvicorn web_process:app --host 0.0.0.0 --port 8000 \
        --app-dir examples/split_deployment
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from discord_webapi import DiscordAuth, DiscordWebAPI, RedisJobQueue, RedisTransport
from discord_webapi.storage.sql import SQLAuthzStore, SQLSessionStore

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
base_url = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")
engine = create_async_engine(os.environ["DATABASE_URL"])

transport = RedisTransport(redis_url)
auth = DiscordAuth(
    client_id=os.environ["DISCORD_CLIENT_ID"],
    client_secret=os.environ["DISCORD_CLIENT_SECRET"],
    redirect_uri=f"{base_url}/auth/discord/callback",
    encryption_keys=os.environ["DWA_FERNET_KEY"].encode(),
    cookie_secure=base_url.startswith("https://"),
    session_store=SQLSessionStore(engine),
)
api = DiscordWebAPI.for_web_process(
    transport=transport,
    auth=auth,
    authz_store=SQLAuthzStore(engine),
    # Only registers RPUSH-ing job ids here -- this process never itself
    # processes jobs, that's worker_process.py's job (pun intended).
    job_queue=RedisJobQueue(redis_url),
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with api.web_lifespan():
        yield


app = FastAPI(title="discord-webapi (web replica)", lifespan=lifespan)
api.install(app, enable_jobs=True)
