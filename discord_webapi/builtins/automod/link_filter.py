"""Generic URL domain filter -- independent of `invite_filter.py` (which
only ever looks at Discord's own invite links). Two, mutually exclusive
modes: `blocked_domains` (blocklist -- everything's allowed except these)
or `allowed_domains` (allowlist -- everything's blocked except these).
Passing both raises `ValueError`; that combination has no sensible
meaning (which one should win?), so it's rejected at setup time instead
of silently picking one.
"""

from __future__ import annotations

import re

import discord

from discord_webapi.builtins.automod.base import AutomodCheck

_URL_RE = re.compile(r"https?://([^\s/]+)", re.IGNORECASE)


def _matches_domain(host: str, domains: set[str]) -> bool:
    host = host.lower()
    return any(host == d or host.endswith(f".{d}") for d in domains)


def make_check(
    *, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None
) -> AutomodCheck | None:
    """Returns a check enforcing the configured domain policy, or `None`
    if neither `allowed_domains` nor `blocked_domains` is set (disabled).
    """
    if allowed_domains is not None and blocked_domains is not None:
        raise ValueError(
            "link_filter.make_check() takes allowed_domains OR blocked_domains, not both"
        )
    if allowed_domains is None and blocked_domains is None:
        return None

    allowlist = {d.lower() for d in allowed_domains} if allowed_domains is not None else None
    blocklist = {d.lower() for d in blocked_domains} if blocked_domains is not None else None

    def check(message: discord.Message) -> str | None:
        for host in _URL_RE.findall(message.content):
            if blocklist is not None and _matches_domain(host, blocklist):
                return f"linked to a blocked domain ({host})"
            if allowlist is not None and not _matches_domain(host, allowlist):
                return f"linked to a domain that isn't allow-listed ({host})"
        return None

    return check
