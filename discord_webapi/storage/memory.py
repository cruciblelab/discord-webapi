from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from discord_webapi.storage.base import Session

if TYPE_CHECKING:
    from discord_webapi.authz.models import AppRole
    from discord_webapi.commands.models import CommandOverride


class MemorySessionStore:
    """Dict-backed SessionStore. Zero infrastructure — the default for dev/tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def update(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class MemoryCommandConfigStore:
    """Dict-backed CommandConfigStore. Zero infrastructure — the default for dev/tests."""

    def __init__(self) -> None:
        self._overrides: dict[tuple[int, str], CommandOverride] = {}

    async def get_override(self, guild_id: int, command_name: str) -> CommandOverride | None:
        override = self._overrides.get((guild_id, command_name))
        return copy.deepcopy(override) if override is not None else None

    async def get_all_overrides(self, guild_id: int) -> list[CommandOverride]:
        return [
            copy.deepcopy(override)
            for (g_id, _name), override in self._overrides.items()
            if g_id == guild_id
        ]

    async def set_override(self, override: CommandOverride) -> None:
        self._overrides[(override.guild_id, override.command_name)] = copy.deepcopy(override)


class MemoryAuthzStore:
    """Dict-backed AuthzStore. Zero infrastructure — the default for dev/tests."""

    def __init__(self) -> None:
        self._roles: dict[tuple[int, str], AppRole] = {}

    async def get_all_app_roles(self, guild_id: int) -> list[AppRole]:
        return [
            copy.deepcopy(role) for (g_id, _name), role in self._roles.items() if g_id == guild_id
        ]

    async def set_app_role(self, role: AppRole) -> None:
        self._roles[(role.guild_id, role.name)] = copy.deepcopy(role)

    async def delete_app_role(self, guild_id: int, name: str) -> None:
        self._roles.pop((guild_id, name), None)
