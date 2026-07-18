"""`commands.Bot` and `commands.AutoShardedBot` are sibling classes (neither
subclasses the other) -- `AnyBot` (`discord_webapi.bot.types`) lets every
`bot:` parameter across the library accept either, since nothing here
reads anything shard-count-specific: discord.py already merges every
shard's cache into one `.guilds` collection regardless of shard count.
This covers that an `AutoShardedBot` is genuinely accepted end to end, not
just by a type-checker."""

import discord
from discord.ext import commands

from discord_webapi.commands.registry import CommandRegistry
from discord_webapi.storage.memory import MemoryCommandConfigStore
from discord_webapi.transport.inprocess import InProcessTransport


def _sharded_bot() -> commands.AutoShardedBot:
    return commands.AutoShardedBot(
        command_prefix="!", intents=discord.Intents.default(), shard_count=2
    )


def test_command_registry_accepts_an_autosharded_bot() -> None:
    bot = _sharded_bot()

    registry = CommandRegistry(
        bot, transport=InProcessTransport(), store=MemoryCommandConfigStore()
    )

    assert registry.bot is bot
    assert isinstance(registry.bot, commands.AutoShardedBot)


async def test_register_all_and_global_check_work_with_an_autosharded_bot() -> None:
    bot = _sharded_bot()

    @bot.hybrid_command(name="ping")
    async def ping(ctx: commands.Context) -> None: ...

    registry = CommandRegistry(
        bot, transport=InProcessTransport(), store=MemoryCommandConfigStore()
    )
    await registry.register_all()

    assert "ping" in registry._specs
    # global_check/interaction_check wiring must not have raised, and the
    # bot's own tree/command surface must still work identically to a
    # plain (non-sharded) Bot's.
    assert bot.get_command("ping") is not None


def test_extras_setup_functions_accept_an_autosharded_bot() -> None:
    from discord_webapi.extras import ban, kick, timeout, warn, welcome

    bot = _sharded_bot()

    assert ban.setup(bot).name == "ban"
    assert kick.setup(bot).name == "kick"
    assert timeout.setup(bot).name == "timeout"
    assert warn.setup(bot).name == "warn"
    welcome.setup(bot, channel_id=123)  # event listener, no command to check
