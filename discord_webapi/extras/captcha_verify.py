"""A ready-made "get me a verification link" command -- the quick-usage
front door to `discord_webapi.captcha`'s `CaptchaGate`/`AdaptiveCaptchaGate`,
same convention as every other builtin in this package (`warn.py`,
`ban.py`, ...): `setup(bot, **kwargs)`, nothing auto-registered.

This is deliberately thin. The actual verification *policy* -- which
captcha kind, account-binding, IP-adaptive escalation, trust duration,
PathTrace vs. reCAPTCHA vs. your own provider -- is entirely up to
whichever `gate` you construct and pass in; this command only does the
"mint a link and hand it to whoever typed the command" part. Use it as-is
for the common case, or skip it and call `gate.create_verification()`
yourself from a command you write from scratch -- both are first-class,
same "use it whole, in pieces, or not at all" philosophy as the rest of
`discord_webapi.extras`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from discord_webapi.captcha.models import VerificationRequest


class _VerificationGate(Protocol):
    """Structural shape both `CaptchaGate` and `AdaptiveCaptchaGate`
    satisfy -- same idea as `captcha.api.GateLike`, kept as its own
    narrower copy here (this command only ever calls
    `create_verification`, never `get_info`/`verify`) so importing this
    module doesn't pull in `captcha.api`'s FastAPI-specific surface."""

    async def create_verification(
        self,
        *,
        user_id: int,
        guild_id: int | None = None,
        purpose: str,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationRequest: ...


def setup(
    bot: commands.Bot,
    *,
    gate: _VerificationGate,
    verify_url: Callable[[str], str],
    command_name: str = "verify",
    purpose: str = "verify",
    metadata: dict[str, Any] | None = None,
    message: str = "Click here to verify you're human: {link}",
    dm_link: bool = False,
) -> Any:
    """Registers a command that mints a verification link via
    `gate.create_verification()` and hands it to the invoking user.

    `verify_url`: `Callable[[str], str]` turning a bare token into the
    full URL your web app serves it at (e.g.
    `lambda token: f"https://yoursite.com/verify/{token}"`) -- same
    "you own routing, we own the token" split as `PageGuard.verify_url`.

    `purpose`/`metadata`: passed straight through to
    `create_verification()` -- `purpose` is how your `on_verified()`
    handler tells this command's verifications apart from any other
    gate purpose sharing the same `Transport` (see `CaptchaGate.
    on_verified`'s `purpose=` filter).

    `message`: a format string with a `{link}` placeholder -- entirely
    yours to change (wording, emoji, additional instructions).

    `dm_link` (default `False`, ephemeral reply): if `True`, DMs the
    link instead and only replies with a short "check your DMs" --
    falls back to an ephemeral reply with the link if the DM fails
    (closed DMs, blocked bot), same best-effort-DM convention as every
    other builtin here.
    """

    @bot.hybrid_command(name=command_name, description="Verify you're human")
    async def verify(ctx: commands.Context[commands.Bot]) -> None:
        guild_id = ctx.guild.id if ctx.guild is not None else None
        request = await gate.create_verification(
            user_id=ctx.author.id, guild_id=guild_id, purpose=purpose, metadata=metadata
        )
        text = message.format(link=verify_url(request.token))

        if dm_link:
            try:
                await ctx.author.send(text)
            except (discord.Forbidden, discord.HTTPException):
                await ctx.reply(text, ephemeral=True)
            else:
                await ctx.reply("Check your DMs for the verification link.", ephemeral=True)
        else:
            await ctx.reply(text, ephemeral=True)

    return verify
