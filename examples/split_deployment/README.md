# Split bot/web deployment

For a bot big enough that the dashboard's HTTP traffic should scale
independently of the single Discord Gateway connection: run the bot in
its own process (`bot_process.py`) and the FastAPI dashboard as any
number of separate replicas (`web_process.py`), all sharing a Redis
instance (`RedisTransport`) and one database.

This is opt-in — nothing about it is required for the default,
single-process deployment (`DiscordWebAPI(bot=..., transport=..., auth=...)`
/ `DiscordWebAPI.quickstart(...)`, see `examples/single_process_bot/` and
`examples/full_featured_bot/`), and every route/dependency in this package
was already written only against `Transport`, never a concrete bot object
— splitting the process doesn't change any of that code.

## Running it

```bash
pip install -e ".[redis,sql-postgres]"   # from the repo root

# one Redis instance and one Postgres database, shared by both processes
docker run -d -p 6379:6379 redis:7
# ... your Postgres instance ...

export DISCORD_BOT_TOKEN=...
export DISCORD_CLIENT_ID=...
export DISCORD_CLIENT_SECRET=...
export DWA_FERNET_KEY=...            # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export DASHBOARD_BASE_URL=http://localhost:8000
export REDIS_URL=redis://localhost:6379/0
export DATABASE_URL=postgresql+asyncpg://user:pass@host/db

# Terminal 1 -- exactly one of these, it owns the Gateway connection.
# Also creates the database schema on startup (create_all).
python bot_process.py

# Terminal 2, 3, 4, ... -- as many as you want, each its own process
# (or container/machine), all pointed at the same Redis + database.
uvicorn web_process:app --port 8000
uvicorn web_process:app --port 8001

# Terminal 5, 6, ... -- optional, only if you enqueue background jobs
# (POST /api/guilds/{id}/jobs/{job_type}). As many as you want, same idea.
python worker_process.py
```

## What actually changes vs. the default deployment

- `DiscordWebAPI.for_bot_process(bot=..., transport=..., ...)` builds only
  the bot-side wiring: the live `CommandRegistry`, and RPC handlers for
  member/channel-permission/guild-listing lookups and command status/
  overrides (see `commands.registry.install_command_registry_bridge`).
  No FastAPI.
- `DiscordWebAPI.for_web_process(transport=..., auth=..., ...)` builds
  only the web-side wiring: auth, the dashboard routers, caches that talk
  to the bot process over `Transport`. No `discord.Bot` object at all.
- Both are backed by the exact same `DiscordWebAPI` class and the exact
  same routers as the single-process case — `for_bot_process`/
  `for_web_process` just skip constructing the half that process doesn't
  need. Nothing in `discord_webapi.commands`/`authz`/`members`/`guilds`
  had to change to support this; they were already written only against
  `Transport`.
- **Schema creation**: only `bot_process.py` calls `create_all(engine)` in
  this example — make sure it (or a proper migration tool, e.g. Alembic,
  in production) runs before any `web_process.py` replica starts serving
  traffic.
- **RedisTransport's one-handler-per-command rule still applies**: run
  exactly one `bot_process.py` per bot account/token. Running two would
  mean two processes both answering the same RPC commands, which is
  undefined (first reply wins, see `RedisTransport`'s docstring) — this
  is about *replicating the web tier*, not the bot itself.

## Background jobs (`worker_process.py`, optional)

For work that shouldn't block a dashboard request/response cycle (bulk
moderation actions, exports, scheduled cleanups): `web_process.py` enables
`enable_jobs=True` with a `RedisJobQueue`, exposing `POST
/api/guilds/{guild_id}/jobs/{job_type}` (enqueue, 202 Accepted with a
`job_id`) and `GET /api/guilds/{guild_id}/jobs/{job_id}` (poll status).
`worker_process.py` is where jobs actually run — unlike `RedisTransport`'s
RPC (exactly one handler may ever answer), `RedisJobQueue` uses plain
Redis lists (`RPUSH`/`BLPOP`), which give proper competing-consumer
semantics for free: run as many `worker_process.py` instances as you want,
on any machine, and Redis guarantees no two of them ever process the same
job. Scaling job throughput is just running more of that one script.
