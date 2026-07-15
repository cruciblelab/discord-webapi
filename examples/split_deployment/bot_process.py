"""Bot-only process for a large bot deployment: connects to Discord and to
a shared RedisTransport, and answers every RPC the web side needs (member/
channel-permission/guild-listing lookups, command status/overrides). No
FastAPI here at all -- run exactly one of these per bot account/token.

Pair with `web_process.py`, which you can run as any number of separate
replicas/machines against the same Redis and database.

Run:
    pip install -e ".[redis,sql]"                # from the repo root
    export DISCORD_BOT_TOKEN=...
    export REDIS_URL=redis://localhost:6379/0
    export DATABASE_URL=postgresql+asyncpg://user:pass@host/db
    python examples/split_deployment/bot_process.py
"""

import asyncio
import os

from discord.ext import commands
from sqlalchemy.ext.asyncio import create_async_engine

from discord_webapi import DiscordWebAPI, RedisTransport
from discord_webapi.bot import default_intents
from discord_webapi.storage.sql import SQLCommandConfigStore, create_all

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)


@bot.hybrid_command(name="ping", description="Replies with pong")
async def ping(ctx: commands.Context) -> None:
    await ctx.reply("pong")


async def main() -> None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    database_url = os.environ["DATABASE_URL"]

    engine = create_async_engine(database_url)
    await create_all(engine)

    transport = RedisTransport(redis_url)
    api = DiscordWebAPI.for_bot_process(
        bot=bot,
        transport=transport,
        command_store=SQLCommandConfigStore(engine),
        # Global sync's ~1hr propagation delay is fine for a big, stable
        # bot -- pass sync_guild_id=<test_guild_id> instead while developing.
    )

    async with api.lifespan(token):
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
