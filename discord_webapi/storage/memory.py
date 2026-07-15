from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from discord_webapi.storage.base import Session

if TYPE_CHECKING:
    from discord_webapi.audit.models import AuditLogEntry
    from discord_webapi.authz.models import AppRole
    from discord_webapi.commands.models import CommandOverride
    from discord_webapi.consent.models import ConsentRecord


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

    async def list_by_user(self, user_id: int) -> list[Session]:
        return [s for s in self._sessions.values() if s.user_id == user_id]


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


class MemoryAuditStore:
    """List-backed AuditStore. Zero infrastructure — the default for dev/tests."""

    def __init__(self) -> None:
        self._entries: list[AuditLogEntry] = []

    async def record(self, entry: AuditLogEntry) -> None:
        self._entries.append(copy.deepcopy(entry))

    async def list_entries(self, guild_id: int, *, limit: int = 100) -> list[AuditLogEntry]:
        matching = [copy.deepcopy(e) for e in self._entries if e.guild_id == guild_id]
        return sorted(matching, key=lambda e: e.created_at, reverse=True)[:limit]


class MemoryConsentStore:
    """Dict-backed ConsentStore. Zero infrastructure — the default for dev/tests."""

    def __init__(self) -> None:
        self._records: dict[int, ConsentRecord] = {}

    async def get(self, user_id: int) -> ConsentRecord | None:
        record = self._records.get(user_id)
        return copy.deepcopy(record) if record is not None else None

    async def set(self, record: ConsentRecord) -> None:
        self._records[record.user_id] = copy.deepcopy(record)
