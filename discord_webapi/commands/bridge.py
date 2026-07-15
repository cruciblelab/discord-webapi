"""All direct discord.py introspection lives here, isolated from the rest of
the package. discord.py's internal attribute names have shifted across
minor releases before; keeping every touchpoint in one module means a
version bump only ever needs changes in this file. See the discord.py
version-pinned test matrix in CI (tests/unit/test_bridge_*.py) that exercises
this module against the pinned version range.
"""

from __future__ import annotations

import inspect
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from discord_webapi.commands.models import CommandSpec, ParamSpec

_PYTHON_TYPE_NAMES: dict[Any, str] = {
    str: "string",
    int: "integer",
    bool: "boolean",
    float: "number",
}


def _prefix_param_type_name(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return "string"
    if annotation in _PYTHON_TYPE_NAMES:
        return _PYTHON_TYPE_NAMES[annotation]
    name = getattr(annotation, "__name__", None)
    return name.lower() if name else "unknown"


def _app_command_params(command: app_commands.Command[Any, Any, Any]) -> list[ParamSpec]:
    params = []
    for param in command.parameters:
        choices = (
            [(choice.name, str(choice.value)) for choice in param.choices]
            if param.choices
            else None
        )
        params.append(
            ParamSpec(
                name=param.name,
                description=param.description or None,
                type=param.type.name.lower(),
                required=param.required,
                choices=choices,
            )
        )
    return params


def _prefix_command_params(command: commands.Command[Any, ..., Any]) -> list[ParamSpec]:
    params = []
    for name, param in command.clean_params.items():
        params.append(
            ParamSpec(
                name=name,
                description=None,
                type=_prefix_param_type_name(param.annotation),
                required=param.default is inspect.Parameter.empty,
                choices=None,
            )
        )
    return params


def extract_command_specs(bot: commands.Bot) -> list[CommandSpec]:
    """Walk the bot's registered commands via discord.py's public
    introspection APIs only (`bot.tree.walk_commands()`, `bot.walk_commands()`)
    and return a flat, JSON-serializable spec list. Hybrid commands show up
    in both trees under the same qualified name and are merged into one spec.
    """
    specs: dict[str, CommandSpec] = {}

    for app_command in bot.tree.walk_commands():
        if isinstance(app_command, app_commands.Group):
            continue
        specs[app_command.qualified_name] = CommandSpec(
            name=app_command.qualified_name,
            description=app_command.description or "",
            category=None,
            params=_app_command_params(app_command),
            is_slash=True,
            is_prefix=False,
        )

    for prefix_command in bot.walk_commands():
        if prefix_command.hidden:
            continue
        name = prefix_command.qualified_name
        existing = specs.get(name)
        if existing is not None:
            specs[name] = existing.model_copy(update={"is_prefix": True})
            continue
        cog_name = prefix_command.cog.qualified_name if prefix_command.cog else None
        specs[name] = CommandSpec(
            name=name,
            description=prefix_command.short_doc or prefix_command.description or "",
            category=cog_name,
            params=_prefix_command_params(prefix_command),
            is_slash=False,
            is_prefix=True,
        )

    return list(specs.values())


def get_member_roles(bot: commands.Bot, guild_id: int, user_id: int) -> list[int] | None:
    """Answer a guild-member role lookup from the bot's warm Gateway cache —
    never a REST call. Returns None if the guild or member isn't cached
    (e.g. `Intents.members` disabled, or the member hasn't been chunked yet).
    """
    guild = bot.get_guild(guild_id)
    if guild is None:
        return None
    member = guild.get_member(user_id)
    if member is None:
        return None
    return [role.id for role in member.roles]


def get_member_permissions(
    bot: commands.Bot, guild_id: int, user_id: int
) -> discord.Permissions | None:
    guild = bot.get_guild(guild_id)
    if guild is None:
        return None
    member = guild.get_member(user_id)
    if member is None:
        return None
    return member.guild_permissions


def get_channel_permissions(
    bot: commands.Bot, guild_id: int, channel_id: int, user_id: int
) -> discord.Permissions | None:
    """Effective permissions for a member in a specific channel --
    guild-level roles *plus* that channel's own permission overwrites
    (`channel.permissions_for` folds both together, matching what
    Discord's own UI shows as "these are your permissions here"). Answers
    from the bot's warm Gateway cache only, same no-REST-call principle as
    `get_member_permissions`. Returns `None` if the guild/member/channel
    isn't cached.
    """
    guild = bot.get_guild(guild_id)
    if guild is None:
        return None
    member = guild.get_member(user_id)
    if member is None:
        return None
    channel = guild.get_channel(channel_id)
    if channel is None:
        return None
    return channel.permissions_for(member)
