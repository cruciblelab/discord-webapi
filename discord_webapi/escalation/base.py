from __future__ import annotations

from typing import Protocol

from discord_webapi.escalation.models import EscalationRule, ViolationRecord


class EscalationRuleStore(Protocol):
    """Storage for per-guild escalation ladders. Implementations:
    `MemoryEscalationRuleStore` (dev/test), `SQLEscalationRuleStore`
    (needs `discord-webapi[sql]`).
    """

    async def get_rules(self, guild_id: int, key: str) -> list[EscalationRule]: ...

    async def get_all_rules(self, guild_id: int) -> list[EscalationRule]: ...

    async def set_rule(self, rule: EscalationRule) -> None: ...

    async def delete_rule(self, guild_id: int, key: str, threshold: int) -> None: ...


class ViolationStore(Protocol):
    """Storage for recorded violations (the running tally
    `EscalationEngine` checks rules against). Implementations:
    `MemoryViolationStore` (dev/test), `SQLViolationStore` (needs
    `discord-webapi[sql]`).
    """

    async def add(self, record: ViolationRecord) -> None: ...

    async def count(self, guild_id: int, user_id: int, key: str) -> int: ...
