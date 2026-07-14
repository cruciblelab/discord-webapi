from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import discord
from discord.ext import commands

from discord_webapi.commands.bridge import extract_command_specs
from discord_webapi.commands.events import EVENT_TYPE_COMMAND_CONFIG_CHANGED, CommandConfigChanged
from discord_webapi.commands.models import CommandOverride, CommandSpec, CommandStatus
from discord_webapi.storage.base import CommandConfigStore
from discord_webapi.transport.base import Event, Transport


class CommandRegistry:
    """Bridges the bot's registered commands to the dashboard.

    - `register_all()` introspects the bot once (see `commands.bridge`) and
      seeds the enabled/disabled cache from `store` for every guild the bot
      is currently in.
    - Enforcement (`global_check` for prefix/hybrid, the wrapped
      `interaction_check` for slash) is an O(1) in-memory dict lookup —
      never a DB query — because it runs on the hot path of every single
      command invocation across every guild.
    - Writes (`set_override`) go web -> store -> `command_config_changed`
      Transport event; the bot process only ever reads the store on boot
      and reacts to that event afterwards, it never writes to it.
    """

    def __init__(
        self, bot: commands.Bot, *, transport: Transport, store: CommandConfigStore
    ) -> None:
        self.bot = bot
        self.transport = transport
        self.store = store
        self._specs: dict[str, CommandSpec] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._override_cache: dict[tuple[int, str], CommandOverride] = {}
        self._registered = False

        self.transport.subscribe(EVENT_TYPE_COMMAND_CONFIG_CHANGED, self._on_config_changed)

    def command_meta(
        self, *, category: str | None = None, default_enabled: bool = True
    ) -> Any:
        """Decorator recording metadata against a discord.py Command/HybridCommand
        object by its qualified name — never touches discord.py internals, just a
        side table consulted during `register_all()`.
        """

        def decorator(command: Any) -> Any:
            name = getattr(command, "qualified_name", None) or getattr(command, "name", None)
            if name is None:
                raise TypeError(
                    "command_meta must decorate a discord.py Command/HybridCommand object"
                )
            self._meta[name] = {"category": category, "default_enabled": default_enabled}
            return command

        return decorator

    async def register_all(self) -> None:
        """Call once the bot is ready (guilds populated). Introspects all
        registered commands, seeds the override cache for every current
        guild, and wires enforcement into the bot."""
        specs = extract_command_specs(self.bot)
        self._specs = {}
        for spec in specs:
            meta = self._meta.get(spec.name)
            if meta is not None:
                spec = spec.model_copy(
                    update={
                        "category": meta.get("category", spec.category),
                        "default_enabled": meta.get("default_enabled", spec.default_enabled),
                    }
                )
            self._specs[spec.name] = spec

        for guild in self.bot.guilds:
            overrides = await self.store.get_all_overrides(guild.id)
            for override in overrides:
                self._override_cache[(guild.id, override.command_name)] = override

        if not self._registered:
            self.bot.add_check(self.global_check)
            self._wrap_interaction_check()
            self._registered = True

    def _wrap_interaction_check(self) -> None:
        original_check = self.bot.tree.interaction_check

        async def _interaction_check(interaction: discord.Interaction[commands.Bot]) -> bool:
            if not await original_check(interaction):
                return False
            if interaction.guild_id is None or interaction.command is None:
                return True
            return self.is_enabled(interaction.guild_id, interaction.command.qualified_name)

        # Deliberate monkeypatch: composes with whatever interaction_check the
        # bot author already defined, rather than requiring them to construct
        # the bot with a custom CommandTree subclass just for this.
        self.bot.tree.interaction_check = _interaction_check  # type: ignore[method-assign]

    async def global_check(self, ctx: commands.Context[Any]) -> bool:
        if ctx.guild is None or ctx.command is None:
            return True
        return self.is_enabled(ctx.guild.id, ctx.command.qualified_name)

    def is_enabled(self, guild_id: int, command_name: str) -> bool:
        override = self._override_cache.get((guild_id, command_name))
        if override is not None:
            return override.enabled
        spec = self._specs.get(command_name)
        return spec.default_enabled if spec else True

    def list_status(self, guild_id: int) -> list[CommandStatus]:
        return [self._status_for(guild_id, name) for name in self._specs]

    async def set_override(
        self,
        guild_id: int,
        command_name: str,
        *,
        enabled: bool,
        updated_by_user_id: int | None = None,
    ) -> CommandStatus:
        if command_name not in self._specs:
            raise ValueError(f"Unknown command {command_name!r}")

        override = CommandOverride(
            guild_id=guild_id,
            command_name=command_name,
            enabled=enabled,
            updated_at=datetime.now(UTC),
            updated_by_user_id=updated_by_user_id,
        )
        await self.store.set_override(override)
        self._override_cache[(guild_id, command_name)] = override

        event = CommandConfigChanged(guild_id=guild_id, command_name=command_name)
        await self.transport.publish(
            Event(type=EVENT_TYPE_COMMAND_CONFIG_CHANGED, payload=event.model_dump())
        )

        return self._status_for(guild_id, command_name)

    def _status_for(self, guild_id: int, command_name: str) -> CommandStatus:
        spec = self._specs[command_name]
        override = self._override_cache.get((guild_id, command_name))
        return CommandStatus(
            name=spec.name,
            description=spec.description,
            category=spec.category,
            params=spec.params,
            is_slash=spec.is_slash,
            is_prefix=spec.is_prefix,
            enabled=override.enabled if override else spec.default_enabled,
            cooldown_seconds=(
                override.cooldown_seconds if override else spec.default_cooldown_seconds
            ),
            cooldown_uses=override.cooldown_uses if override else spec.default_cooldown_uses,
        )

    async def _on_config_changed(self, event: Event) -> None:
        change = CommandConfigChanged.model_validate(event.payload)
        override = await self.store.get_override(change.guild_id, change.command_name)
        key = (change.guild_id, change.command_name)
        if override is not None:
            self._override_cache[key] = override
        else:
            self._override_cache.pop(key, None)
