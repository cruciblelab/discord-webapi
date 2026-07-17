from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.captcha.models import VerificationRequest
from discord_webapi.extras.captcha_verify import setup as setup_captcha_verify

GUILD_ID = 999


class _FakeGate:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create_verification(
        self,
        *,
        user_id: int,
        guild_id: int | None = None,
        purpose: str,
        metadata: dict[str, object] | None = None,
    ) -> VerificationRequest:
        self.calls.append(
            {"user_id": user_id, "guild_id": guild_id, "purpose": purpose, "metadata": metadata}
        )
        now = datetime.now(UTC)
        return VerificationRequest(
            token="tok-123",
            user_id=user_id,
            guild_id=guild_id,
            purpose=purpose,
            metadata=metadata or {},
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )


def _build_bot() -> dpy_commands.Bot:
    return dpy_commands.Bot(
        command_prefix="!", intents=discord.Intents.default(), help_command=None
    )


def _fake_ctx(*, guild_id: int | None = GUILD_ID, author_id: int = 42) -> MagicMock:
    ctx = MagicMock()
    ctx.reply = AsyncMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = author_id
    ctx.author.send = AsyncMock()
    if guild_id is None:
        ctx.guild = None
    else:
        ctx.guild.id = guild_id
    return ctx


def _verify_url(token: str) -> str:
    return f"https://example.test/verify/{token}"


async def test_setup_registers_a_hybrid_command_named_verify() -> None:
    bot = _build_bot()
    gate = _FakeGate()

    command = setup_captcha_verify(bot, gate=gate, verify_url=_verify_url)

    assert command.name == "verify"


async def test_default_flow_replies_ephemerally_with_the_link() -> None:
    bot = _build_bot()
    gate = _FakeGate()
    command = setup_captcha_verify(bot, gate=gate, verify_url=_verify_url)
    ctx = _fake_ctx()

    await command.callback(ctx)

    ctx.reply.assert_called_once()
    args, kwargs = ctx.reply.call_args
    assert "https://example.test/verify/tok-123" in args[0]
    assert kwargs.get("ephemeral") is True
    ctx.author.send.assert_not_called()


async def test_guild_id_and_purpose_and_metadata_are_passed_through() -> None:
    bot = _build_bot()
    gate = _FakeGate()
    command = setup_captcha_verify(
        bot,
        gate=gate,
        verify_url=_verify_url,
        purpose="giveaway_entry",
        metadata={"giveaway_id": "abc"},
    )
    ctx = _fake_ctx(guild_id=555, author_id=7)

    await command.callback(ctx)

    assert gate.calls == [
        {
            "user_id": 7,
            "guild_id": 555,
            "purpose": "giveaway_entry",
            "metadata": {"giveaway_id": "abc"},
        }
    ]


async def test_guild_id_is_none_outside_a_guild() -> None:
    bot = _build_bot()
    gate = _FakeGate()
    command = setup_captcha_verify(bot, gate=gate, verify_url=_verify_url)
    ctx = _fake_ctx(guild_id=None)

    await command.callback(ctx)

    assert gate.calls[0]["guild_id"] is None


async def test_custom_message_template_is_used() -> None:
    bot = _build_bot()
    gate = _FakeGate()
    command = setup_captcha_verify(
        bot, gate=gate, verify_url=_verify_url, message="Prove you're real: {link} please"
    )
    ctx = _fake_ctx()

    await command.callback(ctx)

    args, _ = ctx.reply.call_args
    assert args[0] == "Prove you're real: https://example.test/verify/tok-123 please"


async def test_dm_link_sends_a_dm_and_replies_with_a_short_notice() -> None:
    bot = _build_bot()
    gate = _FakeGate()
    command = setup_captcha_verify(bot, gate=gate, verify_url=_verify_url, dm_link=True)
    ctx = _fake_ctx()

    await command.callback(ctx)

    ctx.author.send.assert_called_once()
    dm_args, _ = ctx.author.send.call_args
    assert "https://example.test/verify/tok-123" in dm_args[0]
    ctx.reply.assert_called_once()
    reply_args, reply_kwargs = ctx.reply.call_args
    assert "DMs" in reply_args[0]
    assert reply_kwargs.get("ephemeral") is True


async def test_dm_link_falls_back_to_an_ephemeral_reply_when_the_dm_fails() -> None:
    bot = _build_bot()
    gate = _FakeGate()
    command = setup_captcha_verify(bot, gate=gate, verify_url=_verify_url, dm_link=True)
    ctx = _fake_ctx()
    ctx.author.send.side_effect = discord.Forbidden(MagicMock(status=403), "DMs closed")

    await command.callback(ctx)

    ctx.reply.assert_called_once()
    args, kwargs = ctx.reply.call_args
    assert "https://example.test/verify/tok-123" in args[0]
    assert kwargs.get("ephemeral") is True
