from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import discord
from discord.ext import commands
from discord.ext.commands import BucketType, Cooldown, CooldownMapping

from discord_webapi.authz.app_roles import AppRoleCache
from discord_webapi.commands.bridge import extract_command_specs
from discord_webapi.commands.events import EVENT_TYPE_COMMAND_CONFIG_CHANGED, CommandConfigChanged
from discord_webapi.commands.models import CommandOverride, CommandSpec, CommandStatus
from discord_webapi.storage.base import CommandConfigStore
from discord_webapi.transport.base import Event, Transport

_CooldownEntry = tuple[float, int, Cooldown, "CooldownMapping[Any]"]


def _per_user_bucket_key(ctx_or_interaction: Any) -> int:
    # BucketType.user.get_key() only ever does `msg.author.id` -- it has no
    # special case for discord.Interaction (which has `.user`, not
    # `.author`), so it can't be passed directly as CooldownMapping's `type`
    # if this needs to work for both the prefix/hybrid (Context, has
    # `.author`) and slash (Interaction, has `.user`) invocation paths.
    author = getattr(ctx_or_interaction, "author", None)
    user_id: int = author.id if author is not None else ctx_or_interaction.user.id
    return user_id


class CommandRegistry:
    """Bridges the bot's registered commands to the dashboard.

    - `register_all()` introspects the bot once (see `commands.bridge`) and
      seeds the enabled/disabled cache from `store` for every guild the bot
      is currently in.
    - Enforcement (`global_check` for prefix/hybrid, the wrapped
      `interaction_check` for slash) is an O(1) in-memory dict lookup —
      never a DB query — because it runs on the hot path of every single
      command invocation across every guild. The one exception is
      `required_app_role` (`_check_app_role`), which goes through
      `AppRoleCache`'s own short-TTL cache instead, since `AppRole`
      membership can change independently of the `CommandOverride` itself.
    - Writes (`set_override`) go web -> store -> `command_config_changed`
      Transport event; the bot process only ever reads the store on boot
      and reacts to that event afterwards, it never writes to it.
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        transport: Transport,
        store: CommandConfigStore,
        app_role_cache: AppRoleCache | None = None,
    ) -> None:
        self.bot = bot
        self.transport = transport
        self.store = store
        self.app_role_cache = app_role_cache
        self._specs: dict[str, CommandSpec] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._override_cache: dict[tuple[int, str], CommandOverride] = {}
        self._cooldowns: dict[tuple[int, str], _CooldownEntry] = {}
        self._invocation_counts: dict[tuple[int, str], int] = {}
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
            guild_id, name = interaction.guild_id, interaction.command.qualified_name
            if not self.is_enabled(guild_id, name):
                return False
            role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
            if not await self._check_app_role(guild_id, name, interaction.user.id, role_ids):
                return False
            # Slash-only path: no CommandOnCooldown exception here (that's an
            # ext.commands error type, not reliably handled by the tree's own
            # error pipeline) -- just reject, matching the disabled-check above.
            if self._check_cooldown(guild_id, name, interaction) is not None:
                return False
            self._count_invocation(guild_id, name)
            return True

        # Deliberate monkeypatch: composes with whatever interaction_check the
        # bot author already defined, rather than requiring them to construct
        # the bot with a custom CommandTree subclass just for this.
        self.bot.tree.interaction_check = _interaction_check  # type: ignore[method-assign]

    async def global_check(self, ctx: commands.Context[Any]) -> bool:
        if ctx.interaction is not None:
            # A HybridCommand invoked via slash already went through
            # `_wrap_interaction_check` (see `tree.interaction_check`,
            # called first by discord.py's `CommandTree._call`).
            # `HybridCommand.can_run` -> `_check_can_run` *also* runs
            # `bot.can_run(ctx)` (this global check) a second time for the
            # very same invocation -- without this early return, that
            # would double-consume the cooldown token and double-count
            # `invocation_count` for every single slash-invoked hybrid
            # command call. Prefix invocations (`ctx.interaction is None`)
            # never touch `interaction_check` at all, so they still need
            # this check to run for real.
            return True
        if ctx.guild is None or ctx.command is None:
            return True
        guild_id, name = ctx.guild.id, ctx.command.qualified_name
        if not self.is_enabled(guild_id, name):
            return False
        role_ids = [role.id for role in getattr(ctx.author, "roles", [])]
        if not await self._check_app_role(guild_id, name, ctx.author.id, role_ids):
            return False
        retry_after = self._check_cooldown(guild_id, name, ctx)
        if retry_after is not None:
            cooldown = self._cooldowns[(guild_id, name)][2]
            raise commands.CommandOnCooldown(cooldown, retry_after, BucketType.user)
        self._count_invocation(guild_id, name)
        return True

    def is_enabled(self, guild_id: int, command_name: str) -> bool:
        override = self._override_cache.get((guild_id, command_name))
        if override is not None:
            return override.enabled
        spec = self._specs.get(command_name)
        return spec.default_enabled if spec else True

    async def _check_app_role(
        self, guild_id: int, command_name: str, user_id: int, discord_role_ids: list[int]
    ) -> bool:
        """Enforces `CommandOverride.required_app_role` -- unlike
        `is_enabled`/`_check_cooldown` this can't be a pure in-memory O(1)
        lookup (an `AppRole`'s membership can change independently of the
        override itself), so it goes through `AppRoleCache`'s own short-TTL
        cache rather than the override cache. No-op (always allowed) if the
        override has no `required_app_role` configured. If one *is*
        configured but this registry was built without an `app_role_cache`
        (a misconfiguration -- there's no way to actually check membership),
        this fails closed and denies the call rather than silently ignoring
        the restriction.
        """
        override = self._override_cache.get((guild_id, command_name))
        if override is None or override.required_app_role is None:
            return True
        if self.app_role_cache is None:
            return False
        return await self.app_role_cache.user_has_role(
            guild_id,
            override.required_app_role,
            user_id=user_id,
            discord_role_ids=discord_role_ids,
        )

    def _count_invocation(self, guild_id: int, command_name: str) -> None:
        key = (guild_id, command_name)
        self._invocation_counts[key] = self._invocation_counts.get(key, 0) + 1

    def _check_cooldown(self, guild_id: int, command_name: str, bucket_key: Any) -> float | None:
        """Enforces `CommandOverride.cooldown_seconds`/`cooldown_uses` (per
        Discord user) using discord.py's own `Cooldown`/`CooldownMapping`
        token-bucket primitives rather than reinventing rate limiting.
        Returns seconds until retry if on cooldown, else None. No-op if the
        guild/command has no cooldown override configured.
        """
        override = self._override_cache.get((guild_id, command_name))
        if (
            override is None
            or override.cooldown_seconds is None
            or override.cooldown_uses is None
        ):
            return None

        key = (guild_id, command_name)
        cached = self._cooldowns.get(key)
        if (
            cached is None
            or cached[0] != override.cooldown_seconds
            or cached[1] != override.cooldown_uses
        ):
            cooldown = Cooldown(override.cooldown_uses, override.cooldown_seconds)
            mapping = CooldownMapping(cooldown, _per_user_bucket_key)
            self._cooldowns[key] = (
                override.cooldown_seconds,
                override.cooldown_uses,
                cooldown,
                mapping,
            )
        else:
            mapping = cached[3]

        bucket = mapping.get_bucket(bucket_key)
        if bucket is None:  # never happens in practice: `mapping` always wraps a real Cooldown
            return None
        retry_after: float | None = bucket.update_rate_limit()
        return retry_after

    def list_status(self, guild_id: int) -> list[CommandStatus]:
        return [self._status_for(guild_id, name) for name in self._specs]

    async def set_override(
        self,
        guild_id: int,
        command_name: str,
        *,
        enabled: bool,
        cooldown_seconds: float | None = None,
        cooldown_uses: int | None = None,
        required_app_role: str | None = None,
        updated_by_user_id: int | None = None,
    ) -> CommandStatus:
        if command_name not in self._specs:
            raise ValueError(f"Unknown command {command_name!r}")

        override = CommandOverride(
            guild_id=guild_id,
            command_name=command_name,
            enabled=enabled,
            cooldown_seconds=cooldown_seconds,
            cooldown_uses=cooldown_uses,
            required_app_role=required_app_role,
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
            required_app_role=override.required_app_role if override else None,
            invocation_count=self._invocation_counts.get((guild_id, command_name), 0),
        )

    async def _on_config_changed(self, event: Event) -> None:
        change = CommandConfigChanged.model_validate(event.payload)
        override = await self.store.get_override(change.guild_id, change.command_name)
        key = (change.guild_id, change.command_name)
        if override is not None:
            self._override_cache[key] = override
        else:
            self._override_cache.pop(key, None)


COMMAND_LIST_COMMAND_STATUS = "list_command_status"
COMMAND_SET_COMMAND_OVERRIDE = "set_command_override"


def install_command_registry_bridge(registry: CommandRegistry, transport: Transport) -> None:
    """Wiring for whichever process owns the live `CommandRegistry` --
    wherever `register_all()`/enforcement actually run (the bot process in
    a split bot/web deployment, or the single process in the default
    single-process deployment). Answers the dashboard's command-listing/
    override RPCs from it.

    This is what lets `commands.api` behave identically whether the web
    side is co-located (`InProcessTransport`, same object, same process)
    or running as its own separate replica set against `RedisTransport` --
    the registry's in-memory specs/override cache/invocation counters
    never need to leave the process that owns them.
    """

    async def handle_list_command_status(payload: dict[str, Any]) -> dict[str, Any]:
        statuses = registry.list_status(payload["guild_id"])
        return {"statuses": [s.model_dump(mode="json") for s in statuses]}

    async def handle_set_command_override(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            status_result = await registry.set_override(
                payload["guild_id"],
                payload["command_name"],
                enabled=payload["enabled"],
                cooldown_seconds=payload.get("cooldown_seconds"),
                cooldown_uses=payload.get("cooldown_uses"),
                required_app_role=payload.get("required_app_role"),
                updated_by_user_id=payload.get("updated_by_user_id"),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"status": status_result.model_dump(mode="json")}

    transport.register_handler(COMMAND_LIST_COMMAND_STATUS, handle_list_command_status)
    transport.register_handler(COMMAND_SET_COMMAND_OVERRIDE, handle_set_command_override)
