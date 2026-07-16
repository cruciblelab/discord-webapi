"""Automated message moderation -- a coordinator wiring together a set of
independent, individually importable checks (`banned_words`, `spam`,
`mention_spam`, `invite_filter`, `link_filter`, `caps_spam`,
`emoji_spam`), each its own module under this package, following the
exact same "one file, one concern, usable whole or in pieces" convention
as the rest of `discord_webapi.extras`.

`setup()` is the only thing that actually touches Discord (deletes a
message, posts a notice, dispatches a log) -- every check module itself
is a pure, synchronous, side-effect-free function of a `discord.Message`.
That split is deliberate: it's what makes each check trivially testable
on its own (`tests/unit/test_automod_*.py`, one file per check, no event
loop needed) and trivially composable into something other than this
particular `on_message` listener, if you want to build your own.

This is a filter, not a punishment-escalation system: it only ever
deletes a message and optionally posts a short notice or a log-channel
entry. It deliberately does *not* ban/kick/time out anyone or keep a
persistent strike count -- see `extras.warn` for that. Wire
`on_violation=` to your own callback (e.g. bumping a `WarnStore` count)
if you want the two to work together; automod itself has no dependency
on `warn.py` or any other builtin.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord
from discord.ext import commands

from discord_webapi.extras.automod import (
    banned_words,
    caps_spam,
    emoji_spam,
    invite_filter,
    link_filter,
    mention_spam,
    spam,
)
from discord_webapi.extras.automod.base import AutomodCheck
from discord_webapi.extras.automod.exemptions import is_exempt

__all__ = [
    "AutomodCheck",
    "banned_words",
    "caps_spam",
    "emoji_spam",
    "invite_filter",
    "link_filter",
    "mention_spam",
    "setup",
    "spam",
]

DEFAULT_VIOLATION_MESSAGE = "{mention}, your message was removed: {reason}."


def setup(
    bot: commands.Bot,
    *,
    # banned_words.py
    banned_words_list: list[str] | None = None,
    # spam.py
    spam_message_threshold: int | None = 5,
    spam_window_seconds: float = 10.0,
    # mention_spam.py
    max_mentions: int | None = 5,
    # invite_filter.py
    block_invites: bool = False,
    allowed_invite_codes: list[str] | None = None,
    # link_filter.py
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    # caps_spam.py
    caps_ratio: float | None = None,
    caps_min_length: int = 10,
    # emoji_spam.py
    max_emoji: int | None = None,
    # exemptions.py
    exempt_role_ids: list[int] | None = None,
    exempt_channel_ids: list[int] | None = None,
    bypass_if_manage_messages: bool = True,
    # actions
    ignore_bots: bool = True,
    delete_offending_messages: bool = True,
    notify_in_channel: bool = True,
    violation_message: str = DEFAULT_VIOLATION_MESSAGE,
    log_channel_id: int | None = None,
    on_violation: Callable[[discord.Message, str], Awaitable[None]] | None = None,
) -> None:
    """Registers an `on_message` listener running every enabled check (in
    the order listed above), stopping at the first violation. Every check
    is off by default except spam/mention-spam, which ship with sane
    default thresholds -- pass `spam_message_threshold=None` /
    `max_mentions=None` explicitly to turn those off too. Every other
    check (`banned_words_list=None`, `block_invites=False`,
    `caps_ratio=None`, `max_emoji=None`, both link-filter args `None`)
    starts disabled -- you opt in per-server.

    On a violation: deletes the message (`delete_offending_messages`),
    posts a short in-channel notice that auto-deletes itself
    (`notify_in_channel`; `violation_message` is formatted with
    `mention` and `reason`), optionally posts a permanent log entry to
    `log_channel_id`, and optionally awaits `on_violation(message, reason)`
    -- e.g. to bump a `extras.warn` count, without this module needing
    to import `warn.py` itself.

    See `extras.automod.exemptions.is_exempt` for who's skipped
    entirely (mods with `manage_messages` by default, plus any configured
    `exempt_role_ids`/`exempt_channel_ids`).
    """
    checks: list[AutomodCheck] = []
    for maybe_check in (
        banned_words.make_check(banned_words_list or []),
        spam.make_check(threshold=spam_message_threshold, window_seconds=spam_window_seconds),
        mention_spam.make_check(max_mentions=max_mentions),
        invite_filter.make_check(enabled=block_invites, allowed_codes=allowed_invite_codes),
        link_filter.make_check(allowed_domains=allowed_domains, blocked_domains=blocked_domains),
        caps_spam.make_check(ratio=caps_ratio, min_length=caps_min_length),
        emoji_spam.make_check(max_emoji=max_emoji),
    ):
        if maybe_check is not None:
            checks.append(maybe_check)

    exempt_roles = set(exempt_role_ids or ())
    exempt_channels = set(exempt_channel_ids or ())

    @bot.listen("on_message")
    async def _on_message(message: discord.Message) -> None:
        if message.guild is None:
            return
        if ignore_bots and message.author.bot:
            return
        if is_exempt(
            message,
            exempt_role_ids=exempt_roles,
            exempt_channel_ids=exempt_channels,
            bypass_if_manage_messages=bypass_if_manage_messages,
        ):
            return

        reason: str | None = None
        for check in checks:
            reason = check(message)
            if reason is not None:
                break
        if reason is None:
            return

        if delete_offending_messages:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        if notify_in_channel:
            text = violation_message.format(mention=message.author.mention, reason=reason)
            try:
                await message.channel.send(text, delete_after=10)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if log_channel_id is not None:
            log_channel = message.guild.get_channel(log_channel_id)
            if isinstance(log_channel, discord.TextChannel):
                channel_mention = getattr(message.channel, "mention", str(message.channel.id))
                try:
                    await log_channel.send(
                        f"Automod: removed a message from {message.author} "
                        f"in {channel_mention} -- {reason}"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if on_violation is not None:
            await on_violation(message, reason)
