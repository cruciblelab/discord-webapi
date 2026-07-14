from datetime import datetime
from typing import Self

from pydantic import BaseModel, model_validator


class ParamSpec(BaseModel):
    name: str
    description: str | None = None
    type: str
    required: bool
    choices: list[tuple[str, str]] | None = None


class CommandSpec(BaseModel):
    """Static shape of a registered discord.py command, as introspected by
    `discord_webapi.commands.bridge.extract_command_specs`."""

    name: str
    description: str
    category: str | None = None
    params: list[ParamSpec] = []
    is_slash: bool = False
    is_prefix: bool = False
    default_enabled: bool = True
    default_cooldown_seconds: float | None = None
    default_cooldown_uses: int | None = None


class CommandOverride(BaseModel):
    """A per-guild override of a command's default behavior, written by the
    dashboard and enforced live by `CommandRegistry.global_check` /
    `CommandRegistry`-wrapped `interaction_check` — never a per-invocation
    DB read."""

    guild_id: int
    command_name: str
    enabled: bool
    cooldown_seconds: float | None = None
    cooldown_uses: int | None = None
    required_app_role: str | None = None
    updated_at: datetime
    updated_by_user_id: int | None = None


class CommandOverridePatch(BaseModel):
    """Request body for `PATCH /api/guilds/{guild_id}/commands/{command_name}`.

    `cooldown_seconds`/`cooldown_uses` must be set together (e.g. "1 use per
    10 seconds") or both left `None` for no cooldown; enforced per Discord
    user by `CommandRegistry`.
    """

    enabled: bool
    cooldown_seconds: float | None = None
    cooldown_uses: int | None = None

    @model_validator(mode="after")
    def _cooldown_fields_are_paired(self) -> Self:
        if (self.cooldown_seconds is None) != (self.cooldown_uses is None):
            raise ValueError("cooldown_seconds and cooldown_uses must be set together")
        return self


class CommandStatus(BaseModel):
    """CommandSpec merged with any CommandOverride — what the dashboard reads."""

    name: str
    description: str
    category: str | None
    params: list[ParamSpec]
    is_slash: bool
    is_prefix: bool
    enabled: bool
    cooldown_seconds: float | None = None
    cooldown_uses: int | None = None
