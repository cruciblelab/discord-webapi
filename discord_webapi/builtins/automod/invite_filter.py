"""Discord invite-link filter -- flags messages linking to other Discord
servers, the classic self-promo/raid-advertising pattern. An allowlist of
specific invite codes (e.g. the server's own partner/affiliate servers)
can opt individual invites back in.
"""

from __future__ import annotations

import re

import discord

from discord_webapi.builtins.automod.base import AutomodCheck

_INVITE_RE = re.compile(
    r"(?:discord\.gg|discord(?:app)?\.com/invite)/([a-zA-Z0-9-]+)", re.IGNORECASE
)


def make_check(*, enabled: bool, allowed_codes: list[str] | None = None) -> AutomodCheck | None:
    """Returns a check flagging any Discord invite link
    (`discord.gg/...`, `discord.com/invite/...`) not in `allowed_codes`,
    or `None` if `enabled` is `False` (disabled entirely).
    """
    if not enabled:
        return None
    allowlist = {code.lower() for code in (allowed_codes or [])}

    def check(message: discord.Message) -> str | None:
        for code in _INVITE_RE.findall(message.content):
            if code.lower() not in allowlist:
                return "contains a Discord invite link"
        return None

    return check
