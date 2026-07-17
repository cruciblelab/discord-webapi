"""The two concrete bot-command scenarios `CaptchaGate` was built for,
wired up for real against a real discord.py bot -- not the playground's
fake user_id=0, an actual signed-in Discord account via the library's own
OAuth login.

1. **Giveaway entry** (`/join`): a user clicks a button, the bot sends a
   one-time verification link, they solve it on the web (safety mode:
   invisible PoW + behavior score + being signed in as *that* Discord
   account), and the bot DMs them the moment `CaptchaGate.on_verified()`
   fires -- no polling.
2. **Escalation-gated command** (`/appeal`): once a user has racked up
   enough moderation hits (stands in for your own ban/warn history --
   swap `_ban_count_for` for a real `WarnStore`/`EscalationEngine`
   lookup), a *different* restricted command refuses to run until they
   complete a *separate* captcha -- once, not on every single use.

Both gates share one thing: `require_account=True`, which is what turns
"someone solved a captcha" into "this exact Discord account solved a
captcha" -- see `discord_webapi.captcha.gate`'s docstring for why a bare
captcha can't give you that on its own.

Because there are *two* independent gate purposes here, each is mounted
under its own URL prefix via `build_captcha_router(gate=...)` (see that
module's docstring) rather than the single-gate
`app.state.discord_webapi_captcha_gate` shortcut -- and the bundled
widget's `data-api-base` attribute is pointed at the matching prefix.

Run:
    pip install -e "."                            # PoW needs no extras
    cp examples/captcha_gate_bot/.env.example examples/captcha_gate_bot/.env
    # fill in .env, then:
    set -a && source examples/captcha_gate_bot/.env && set +a
    uvicorn main:app --reload --app-dir examples/captcha_gate_bot

Try it (needs a real bot invited to a real server -- see TESTING.md's
general pattern for physical-testing an example bot):
    /join name:spring-giveaway   -> DMs a verification link
    /appeal reason:...           -> refuses until BAN_THRESHOLD is
                                     simulated (see _ban_count_for below)
                                     and a separate link is completed
"""

from __future__ import annotations

import os

import discord
from discord.ext import commands
from fastapi.responses import HTMLResponse

from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents
from discord_webapi.captcha.api import build_captcha_router
from discord_webapi.captcha.events import CaptchaVerified
from discord_webapi.captcha.gate import CaptchaGate
from discord_webapi.captcha.memory import MemoryCaptchaStore, MemoryVerificationStore
from discord_webapi.captcha.providers.proof_of_work import ProofOfWorkProvider
from discord_webapi.captcha.replay_guard import (
    MemoryTrajectoryFingerprintStore,
    RepeatedMovementCheck,
)
from discord_webapi.captcha.scoring import SignalScoreCheck
from discord_webapi.captcha.signals import reject_webdriver
from discord_webapi.captcha.widget import build_captcha_widget_router

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)

_base_url = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000")

app = DiscordWebAPI.quickstart(bot=bot, mobile_redirect_uri=f"{_base_url}/")
transport = app.state.discord_webapi_transport

# One shared "invisible layer" behind both gates: real PoW (server-cheap,
# genuine cost) + the behavioral score + replay detection. Neither gate
# shows the user an image captcha -- they shouldn't have to solve
# anything, just be signed in as themselves while the checks run quietly.
_captcha_store = MemoryCaptchaStore()
_fingerprint_store = MemoryTrajectoryFingerprintStore()


def _behavior_checks() -> list:
    # A fresh list per gate -- SignalScoreCheck/RepeatedMovementCheck are
    # cheap to construct and this avoids two gates sharing mutable state
    # they don't need to share (the fingerprint *store* is still shared
    # on purpose -- see replay_guard's module docstring on why that
    # should be global, not per-gate).
    return [
        reject_webdriver(),
        SignalScoreCheck(),
        RepeatedMovementCheck(_fingerprint_store),
    ]


# -- scenario 1: giveaway entry --------------------------------------
giveaway_gate = CaptchaGate(
    transport,
    MemoryVerificationStore(),
    ProofOfWorkProvider(_captcha_store),
    require_account=True,
    extra_checks=_behavior_checks(),
)


async def _on_giveaway_verified(event: CaptchaVerified) -> None:
    user = await bot.fetch_user(event.user_id)
    await user.send(f"Doğrulandı! **{event.metadata['giveaway_name']}** çekilişine katıldın.")


giveaway_gate.on_verified(_on_giveaway_verified)


@bot.hybrid_command(name="join", description="Bir çekilişe katıl")
async def join(ctx: commands.Context, giveaway_name: str) -> None:
    request = await giveaway_gate.create_verification(
        user_id=ctx.author.id,
        guild_id=ctx.guild.id if ctx.guild else None,
        purpose="giveaway_entry",
        metadata={"giveaway_name": giveaway_name},
    )
    url = f"{_base_url}/verify/giveaway/{request.token}"
    await ctx.author.send(f"**{giveaway_name}** çekilişine katılmak için doğrulan: {url}")
    await ctx.reply("Sana DM attım, linkten doğrula!", ephemeral=True)


# -- scenario 2: an escalation-gated command -------------------------
# Stands in for your own moderation history (a real bot would read this
# from extras.warn's WarnStore or the EscalationEngine's own violation
# counts) -- swap this for that lookup, the gating logic below doesn't
# care where the number comes from.
_fake_ban_counts: dict[int, int] = {}
BAN_THRESHOLD = 3

appeal_gate = CaptchaGate(
    transport,
    MemoryVerificationStore(),
    ProofOfWorkProvider(_captcha_store),
    require_account=True,
    extra_checks=_behavior_checks(),
)
# Once a user completes this gate, they stay cleared for this demo's
# lifetime -- a real bot would persist this (a column on the user's
# moderation record, a TTL'd Store, ...) rather than an in-memory set.
_appeal_verified_users: set[int] = set()


async def _on_appeal_verified(event: CaptchaVerified) -> None:
    _appeal_verified_users.add(event.user_id)


appeal_gate.on_verified(_on_appeal_verified)


def _ban_count_for(user_id: int) -> int:
    return _fake_ban_counts.get(user_id, 0)


@bot.hybrid_command(
    name="simulate-ban", description="Demo only: pretend this user got banned once"
)
async def simulate_ban(ctx: commands.Context, member: discord.Member) -> None:
    count = _fake_ban_counts.get(member.id, 0) + 1
    _fake_ban_counts[member.id] = count
    await ctx.reply(f"{member.mention} artık {count} ban kaydına sahip.", ephemeral=True)


@bot.hybrid_command(name="appeal", description="Ban itirazı gönder")
async def appeal(ctx: commands.Context, reason: str) -> None:
    needs_verification = (
        _ban_count_for(ctx.author.id) >= BAN_THRESHOLD
        and ctx.author.id not in _appeal_verified_users
    )
    if needs_verification:
        request = await appeal_gate.create_verification(
            user_id=ctx.author.id, purpose="appeal_gate"
        )
        url = f"{_base_url}/verify/appeal/{request.token}"
        await ctx.reply(
            f"Çok fazla ban geçmişin var -- devam etmeden önce doğrulanman lazım: {url}",
            ephemeral=True,
        )
        return
    # ... your actual appeal-processing logic would go here ...
    await ctx.reply(f"İtirazın kaydedildi: {reason}", ephemeral=True)


# -- the web side: each gate purpose gets its own prefix + widget page --
app.include_router(build_captcha_router(gate=giveaway_gate), prefix="/giveaway")
app.include_router(build_captcha_router(gate=appeal_gate), prefix="/appeal")
app.include_router(build_captcha_widget_router())


def _verify_page(token: str, api_base: str) -> HTMLResponse:
    # DiscordAuth's non-mobile /auth/discord/login doesn't take a
    # redirect target -- it sets an httpOnly session cookie for this
    # domain and lands on a fixed login_success_redirect (default "/").
    # Since the widget's own fetch calls already carry that cookie once
    # it exists, the flow is: log in once, come back to this same
    # verify link (still in your DMs), then click the widget.
    return HTMLResponse(f"""<!doctype html>
<title>Doğrulama</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:60px auto;padding:0 16px">
<h2>Doğrulama</h2>
<p>Önce Discord hesabınla giriş yap, sonra bu sayfaya geri dönüp aşağıdaki
kutuyu tıkla.</p>
<p><a href="/auth/discord/login" target="_blank" rel="noopener">Discord ile giriş yap</a></p>
<div class="dwa-captcha-widget" data-token="{token}" data-api-base="{api_base}"></div>
<script src="/static/discord-webapi-captcha-widget.js" data-callback="onVerified"></script>
<script>
function onVerified(result) {{
  var msg = result.verified
    ? "Doğrulandı, Discord'a dönebilirsin."
    : "Doğrulanamadı: " + (result.detail || result.failed_check);
  document.body.insertAdjacentHTML("beforeend", "<p>" + msg + "</p>");
}}
</script>
</body>""")


@app.get("/verify/giveaway/{token}")
async def verify_giveaway_page(token: str) -> HTMLResponse:
    return _verify_page(token, "/giveaway")


@app.get("/verify/appeal/{token}")
async def verify_appeal_page(token: str) -> HTMLResponse:
    return _verify_page(token, "/appeal")
