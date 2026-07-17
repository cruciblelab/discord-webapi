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

from discord_webapi.extras.automod.base import AutomodCheck

_URL_RE = re.compile(
    r"(?:https?://|www\.)([^\s/]+)"
    # No scheme and no "www." -- still flag it if it looks like a real
    # domain (has a dotted, letters-only TLD) immediately followed by a
    # path (`/...`). That trailing "/" is what keeps this from matching
    # ordinary prose ("we love node.js and vue.js") while still catching
    # the common bypass of just dropping "https://"/"www." from a link
    # ("evil.com/free-nitro" renders as a clickable link in Discord's own
    # client exactly like a fully-schemed one would).
    r"|\b([a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,24}(?::\d+)?)(?=/)",
    re.IGNORECASE,
)


def _extract_hosts(content: str) -> list[str]:
    hosts = []
    for match in _URL_RE.finditer(content):
        host = match.group(1) or match.group(2)
        # `[^\s/]+` (and the bare-domain branch's own `(?::\d+)?`) both
        # happily swallow a `:port` suffix as part of the "host" -- left
        # in, "evil.com:8080" matches neither `== "evil.com"` nor
        # `.endswith(".evil.com")`, letting a blocked domain through by
        # just tacking a port onto it (and, in allowlist mode, wrongly
        # flagging an *allowed* domain posted with an explicit port).
        hosts.append(host.split(":", 1)[0].lower())
    return hosts


def _matches_domain(host: str, domains: set[str]) -> bool:
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
        for host in _extract_hosts(message.content):
            if blocklist is not None and _matches_domain(host, blocklist):
                return f"linked to a blocked domain ({host})"
            if allowlist is not None and not _matches_domain(host, allowlist):
                return f"linked to a domain that isn't allow-listed ({host})"
        return None

    return check
