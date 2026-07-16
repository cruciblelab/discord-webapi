from __future__ import annotations

import copy

from discord_webapi.escalation.models import EscalationRule, ViolationRecord


class MemoryEscalationRuleStore:
    """Dict-backed EscalationRuleStore. Zero infrastructure -- the default
    for dev/test."""

    def __init__(self) -> None:
        self._rules: dict[tuple[int, str, int], EscalationRule] = {}

    async def get_rules(self, guild_id: int, key: str) -> list[EscalationRule]:
        matching = [
            copy.deepcopy(rule)
            for (g_id, k, _threshold), rule in self._rules.items()
            if g_id == guild_id and k == key
        ]
        return sorted(matching, key=lambda r: r.threshold)

    async def get_all_rules(self, guild_id: int) -> list[EscalationRule]:
        matching = [
            copy.deepcopy(rule)
            for (g_id, _k, _threshold), rule in self._rules.items()
            if g_id == guild_id
        ]
        return sorted(matching, key=lambda r: (r.key, r.threshold))

    async def set_rule(self, rule: EscalationRule) -> None:
        self._rules[(rule.guild_id, rule.key, rule.threshold)] = copy.deepcopy(rule)

    async def delete_rule(self, guild_id: int, key: str, threshold: int) -> None:
        self._rules.pop((guild_id, key, threshold), None)


class MemoryViolationStore:
    """List-backed ViolationStore. Zero infrastructure -- the default for
    dev/test."""

    def __init__(self) -> None:
        self._records: list[ViolationRecord] = []

    async def add(self, record: ViolationRecord) -> None:
        self._records.append(copy.deepcopy(record))

    async def count(self, guild_id: int, user_id: int, key: str) -> int:
        return sum(
            1
            for r in self._records
            if r.guild_id == guild_id and r.user_id == user_id and r.key == key
        )
