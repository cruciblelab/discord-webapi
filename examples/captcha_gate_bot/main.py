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
    /test-join                  -> DMs a button; clicking it hands back a
                                     link to /test-widgets, which shows
                                     three genuinely different captcha
                                     configurations stacked on one page
                                     (Path-Trace / "safety mode" combining
                                     a visible captcha with the invisible
                                     layer / the plain original baseline)
                                     for direct side-by-side comparison
    /test-participants           -> lists everyone who has completed any
                                     of the three test gates so far
    /giveaway-test               -> posts a public "Katıl" button (like a
                                     real giveaway post); clicking it
                                     replies ephemerally and DMs a verify
                                     link that requires login first, then
                                     shows two slots: an adaptive one
                                     (invisible check, escalates to a
                                     Path-Trace draw if it looks
                                     suspicious) and a plain original
                                     Math captcha
    /join-adaptive               -> the real library primitive behind
                                     the manual escalation above, but
                                     driven by IP reputation
                                     (`AdaptiveCaptchaGate`): a clean IP
                                     never sees a captcha, a blocked one
                                     always does. GET /api/test/block-my-ip
                                     (and /unblock-my-ip) let you flip
                                     your own connecting IP for testing.
    /test-index                  -> a hub page linking every test page
                                     below, so you don't have to remember
                                     every URL/command by heart
    /test-instant-widget          -> no login, no Discord round-trip:
                                     click the widget, human-like signals
                                     succeed outright, bot-like ones
                                     escalate to a Path-Trace widget
    /test-forced-bad-data         -> the same pipeline as above, but the
                                     page skips the widget and posts
                                     hardcoded bot-shaped signals directly,
                                     proving detection isn't cosmetic
    /test-cloudflare              -> our own Cloudflare-style "verifying
                                     you are human" interstitial: a clean
                                     IP passes silently, blocking your own
                                     IP (via /api/test/block-my-ip) makes
                                     the same AdaptiveCaptchaGate show one
                                     real Math captcha -- exactly the two
                                     tiers AdaptiveCaptchaGate does on its
                                     own, no extra chaining
"""

from __future__ import annotations

import os

import discord
from discord.ext import commands
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from discord_webapi import DiscordWebAPI
from discord_webapi.auth.dependencies import get_current_user_optional
from discord_webapi.auth.models import DiscordUser
from discord_webapi.bot import default_intents
from discord_webapi.captcha.adaptive import (
    AdaptiveCaptchaGate,
    MemoryAdaptiveDecisionStore,
    MemoryTrustStore,
)
from discord_webapi.captcha.api import build_captcha_router
from discord_webapi.captcha.events import CaptchaVerified
from discord_webapi.captcha.gate import CaptchaGate
from discord_webapi.captcha.memory import MemoryCaptchaStore, MemoryVerificationStore
from discord_webapi.captcha.providers.math_captcha import MathCaptchaProvider
from discord_webapi.captcha.providers.path_trace import PathTraceProvider
from discord_webapi.captcha.providers.proof_of_work import ProofOfWorkProvider
from discord_webapi.captcha.replay_guard import (
    MemoryTrajectoryFingerprintStore,
    RepeatedMovementCheck,
)
from discord_webapi.captcha.reputation import StaticBlocklistReputationChecker
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


giveaway_gate.on_verified(_on_giveaway_verified, purpose="giveaway_entry")


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


appeal_gate.on_verified(_on_appeal_verified, purpose="appeal_gate")


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


async def _expected_user_id(gate: CaptchaGate | AdaptiveCaptchaGate, token: str) -> int | None:
    """Who this specific link was minted for -- `None` if the token is
    gone/unknown, in which case the widget's own `get_info()` call shows
    the real "invalid or expired" state; this helper's only job is
    catching the *different, valid* token case."""
    request = await gate.store.get(token)
    return request.user_id if request is not None else None


def _wrong_account_page(signed_in_as: str) -> HTMLResponse:
    # A real bug-report-driven fix: `AccountMatchCheck` already rejects a
    # mismatched account at *verify* time (see checks.py), but that means
    # someone only finds out after clicking through and trying to solve
    # the captcha -- confusing, and easy to mistake for the captcha itself
    # being broken. Checking token ownership up front, before rendering
    # anything solvable, catches "forwarded someone else's link" (or
    # "switched Discord accounts mid-flow") immediately with a clear
    # explanation instead of a cryptic failed-check after the fact.
    return HTMLResponse(f"""<!doctype html>
<title>Yanlış hesap</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:60px auto;padding:0 16px">
<h2>Bu link sana ait değil</h2>
<p>Şu anda <strong>{signed_in_as}</strong> olarak giriş yapmışsın, ama bu
doğrulama linki farklı bir Discord hesabı için oluşturuldu. Linki başka
biriyle mi paylaştın, yoksa yanlış hesapla mı giriş yaptın?</p>
<p><a href="/auth/discord/logout">Çıkış yap</a> ve doğru hesapla tekrar
giriş yap, ya da bu linki oluşturan komutu doğru hesabınla tekrar
çalıştır.</p>
</body>""")


async def _verify_page(
    token: str, api_base: str, gate: CaptchaGate | AdaptiveCaptchaGate, user: DiscordUser | None
) -> HTMLResponse:
    # DiscordAuth's non-mobile /auth/discord/login doesn't take a
    # redirect target -- it sets an httpOnly session cookie for this
    # domain and lands on a fixed login_success_redirect (default "/").
    # Since the widget's own fetch calls already carry that cookie once
    # it exists, the flow is: log in once, come back to this same
    # verify link (still in your DMs), then click the widget.
    if user is not None:
        expected_user_id = await _expected_user_id(gate, token)
        if expected_user_id is not None and expected_user_id != user.id:
            return _wrong_account_page(user.username)

    who = (
        f"<p>Giriş yaptın: <strong>{user.username}</strong>. Aşağıdaki kutuyu tıkla.</p>"
        if user is not None
        else (
            "<p>Önce Discord hesabınla giriş yap, sonra bu sayfaya geri dönüp "
            "aşağıdaki kutuyu tıkla.</p>"
            '<p><a href="/auth/discord/login" target="_blank" rel="noopener">'
            "Discord ile giriş yap</a></p>"
        )
    )
    return HTMLResponse(f"""<!doctype html>
<title>Doğrulama</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:60px auto;padding:0 16px">
<h2>Doğrulama</h2>
{who}
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
async def verify_giveaway_page(
    token: str, user: DiscordUser | None = Depends(get_current_user_optional)
) -> HTMLResponse:
    return await _verify_page(token, "/giveaway", giveaway_gate, user)


@app.get("/verify/appeal/{token}")
async def verify_appeal_page(
    token: str, user: DiscordUser | None = Depends(get_current_user_optional)
) -> HTMLResponse:
    return await _verify_page(token, "/appeal", appeal_gate, user)


# ---------------------------------------------------------------------
# Side-by-side comparison test: three genuinely different captcha
# configurations, stacked on one page, so you can compare them directly
# instead of one at a time. No account requirement here on purpose --
# this is about comparing *captcha types*, not re-proving account-binding
# (already covered by the giveaway/appeal gates above).
#
#   1. Path-Trace  -- draw the line, no invisible layer at all.
#   2. "Safety mode" -- a visible Math captcha is REQUIRED, and so is the
#      invisible behavior score -- passing the invisible layer does NOT
#      let you skip the visible one, both are ANDed.
#   3. "Original" -- the plain baseline: one Math captcha, nothing else.
# ---------------------------------------------------------------------

test_path_trace_gate = CaptchaGate(
    transport, MemoryVerificationStore(), PathTraceProvider(_captcha_store)
)
test_safety_gate = CaptchaGate(
    transport,
    MemoryVerificationStore(),
    MathCaptchaProvider(_captcha_store),
    extra_checks=_behavior_checks(),
)
test_original_gate = CaptchaGate(
    transport, MemoryVerificationStore(), MathCaptchaProvider(_captcha_store)
)

# Every distinct (purpose, user_id) that has ever completed ANY of the
# three test gates -- a real bot would persist this, this is just enough
# to prove "2 participants completed verification" for the test below.
#
# All three gates (and the giveaway/appeal ones above) share ONE
# Transport (app.state.discord_webapi_transport) -- `captcha_verified` is
# one event type shared by every gate on it, so on_verified() without a
# purpose= filter would see all five gates' events, not just its own
# (see CaptchaGate.on_verified's docstring). Each test gate gets its own
# distinct purpose specifically so this filters correctly.
_test_participants: set[tuple[str, int]] = set()


async def _record_test_participant(event: CaptchaVerified) -> None:
    _test_participants.add((event.purpose, event.user_id))


test_path_trace_gate.on_verified(_record_test_participant, purpose="test_widgets_path_trace")
test_safety_gate.on_verified(_record_test_participant, purpose="test_widgets_safety")
test_original_gate.on_verified(_record_test_participant, purpose="test_widgets_original")

app.include_router(build_captcha_router(gate=test_path_trace_gate), prefix="/test-path-trace")
app.include_router(build_captcha_router(gate=test_safety_gate), prefix="/test-safety")
app.include_router(build_captcha_router(gate=test_original_gate), prefix="/test-original")


@bot.hybrid_command(
    name="test-participants", description="Demo: kaç kişi test gate'lerini tamamladı"
)
async def test_participants(ctx: commands.Context) -> None:
    if not _test_participants:
        await ctx.reply("Henüz kimse doğrulamadı.", ephemeral=True)
        return
    lines = [f"- <@{user_id}> ({purpose})" for purpose, user_id in sorted(_test_participants)]
    await ctx.reply(
        f"**{len(_test_participants)}** doğrulama tamamlandı:\n" + "\n".join(lines),
        ephemeral=True,
    )


class _JoinTestView(discord.ui.View):
    """The button-in-a-DM flow: clicking doesn't verify anything by
    itself (a Discord interaction can't run JS/collect mouse signals) --
    it mints three fresh tokens for *this* user and hands back the one
    link that shows all three widgets stacked."""

    def __init__(self) -> None:
        super().__init__(timeout=300)

    @discord.ui.button(label="Katıl", style=discord.ButtonStyle.primary)
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        user_id = interaction.user.id
        path_trace_req = await test_path_trace_gate.create_verification(
            user_id=user_id, purpose="test_widgets_path_trace"
        )
        safety_req = await test_safety_gate.create_verification(
            user_id=user_id, purpose="test_widgets_safety"
        )
        original_req = await test_original_gate.create_verification(
            user_id=user_id, purpose="test_widgets_original"
        )
        url = (
            f"{_base_url}/test-widgets"
            f"?path_trace={path_trace_req.token}"
            f"&safety={safety_req.token}"
            f"&original={original_req.token}"
        )
        await interaction.response.send_message(
            f"Üç captcha türünü karşılaştırmak için: {url}", ephemeral=True
        )


@bot.hybrid_command(
    name="test-join", description="Demo: DM'e buton gönder, 3 captcha türünü karşılaştır"
)
async def test_join(ctx: commands.Context) -> None:
    await ctx.author.send(
        "Aşağıdaki butona tıkla, üç farklı captcha türünü yan yana test edeceğin linki alacaksın.",
        view=_JoinTestView(),
    )
    await ctx.reply("Sana DM attım, butona tıkla!", ephemeral=True)


@app.get("/test-widgets")
async def test_widgets_page(path_trace: str, safety: str, original: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<title>Captcha karşılaştırma testi</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 16px">
<h2>Üç captcha türünü karşılaştır</h2>

<h3>1) Çizgi-takip -- sadece görsel, görünmez katman yok</h3>
<div class="dwa-captcha-widget" data-token="{path_trace}" data-api-base="/test-path-trace"></div>

<h3>2) Safety mode -- görünür captcha VE görünmez davranış katmanı ikisi de şart</h3>
<p style="font-size:.85rem;color:#666">
Davranış skoru geçse bile görsel captcha'yı da çözmen gerekiyor -- biri
diğerinin yerine geçmiyor.
</p>
<div class="dwa-captcha-widget" data-token="{safety}" data-api-base="/test-safety"></div>

<h3>3) Orijinal -- sade, tek başına bir Math captcha</h3>
<div class="dwa-captcha-widget" data-token="{original}" data-api-base="/test-original"></div>

<script src="/static/discord-webapi-captcha-widget.js"></script>
</body>""")


# ---------------------------------------------------------------------
# Giveaway-bot simulation with adaptive escalation. A public "Katıl"
# button (an embed message, like a real giveaway post) replies
# ephemerally (invisible to everyone else in the channel) and DMs the
# clicking user a verify link. That page requires Discord login FIRST
# (checked server-side -- no captcha is shown before that), then offers
# two independent verification slots:
#
#   1. Adaptive -- starts invisible (behavior score only, require_captcha=
#      False). If it looks suspicious, a second widget appears asking the
#      user to draw a line (Path-Trace). CaptchaGate itself has no
#      built-in escalation -- this composes TWO separate gates via page
#      JS (try the invisible one, only reveal the Path-Trace one if that
#      fails), the same "compose your own" pattern as everywhere else in
#      this library, not a new CaptchaGate feature.
#   2. Original -- a single, always-required Math captcha, independent of
#      the above.
# ---------------------------------------------------------------------

giveaway_test_invisible_gate = CaptchaGate(
    transport,
    MemoryVerificationStore(),
    # ProofOfWorkProvider, not require_captcha=False -- "invisible" means
    # no visible puzzle, not no real cost. A behavior score alone is pure
    # client-submitted data: anyone who knows the scoring rules can send
    # values that pass it, same as this file's own test script does on
    # purpose to exercise the logic. PoW is the one thing here that isn't
    # just a claim -- the server recomputes the hash itself, so "I did
    # the work" can't be faked the way "here are some good-looking
    # signals" can.
    ProofOfWorkProvider(_captcha_store),
    require_account=True,
    extra_checks=_behavior_checks(),
)
giveaway_test_pathtrace_gate = CaptchaGate(
    transport, MemoryVerificationStore(), PathTraceProvider(_captcha_store), require_account=True
)
giveaway_test_original_gate = CaptchaGate(
    transport, MemoryVerificationStore(), MathCaptchaProvider(_captcha_store), require_account=True
)

app.include_router(
    build_captcha_router(gate=giveaway_test_invisible_gate), prefix="/giveaway-test-invisible"
)
app.include_router(
    build_captcha_router(gate=giveaway_test_pathtrace_gate), prefix="/giveaway-test-pathtrace"
)
app.include_router(
    build_captcha_router(gate=giveaway_test_original_gate), prefix="/giveaway-test-original"
)

# Real participation bookkeeping -- keyed by giveaway_id (one per
# `/giveaway-test` invocation, so re-running the command starts a fresh
# giveaway with its own participant list) rather than a single global
# set. A real bot would persist this (a SQL table, a WarnStore-style
# Store); an in-memory dict is enough to prove the wiring here.
_giveaway_test_titles: dict[int, str] = {}
_giveaway_test_participants: dict[int, set[int]] = {}
_next_giveaway_test_id = 1


async def _on_giveaway_test_joined(event: CaptchaVerified) -> None:
    """Either widget succeeding (the adaptive one, possibly after a
    Path-Trace escalation, or the plain original one) counts as "solved a
    captcha to join" -- both are independent, sufficient proof on their
    own, matching how the two widgets were designed as separate slots
    rather than a chain you must complete both of."""
    giveaway_id = event.metadata.get("giveaway_id")
    if giveaway_id is None:
        return
    _giveaway_test_participants.setdefault(giveaway_id, set()).add(event.user_id)


giveaway_test_invisible_gate.on_verified(
    _on_giveaway_test_joined, purpose="giveaway_test_invisible"
)
giveaway_test_pathtrace_gate.on_verified(
    _on_giveaway_test_joined, purpose="giveaway_test_pathtrace"
)
giveaway_test_original_gate.on_verified(
    _on_giveaway_test_joined, purpose="giveaway_test_original"
)


class _GiveawayTestJoinView(discord.ui.View):
    """A real giveaway bot would register this with `bot.add_view()` so
    the button keeps working across restarts -- skipped here to keep the
    demo to one file."""

    def __init__(self, giveaway_id: int) -> None:
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(
        label="Katıl", style=discord.ButtonStyle.success, custom_id="giveaway_test_join"
    )
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Acknowledge the interaction FIRST, before any other awaited work.
        # Discord gives a component interaction only ~3 seconds to get a
        # response; doing the token-minting below (three separate
        # create_verification calls) *before* responding meant any hiccup
        # there (or just being on the slow side) surfaced to the user as
        # "This interaction failed" with no way to retry other than
        # re-clicking. Deferring immediately removes that deadline -- the
        # real response goes out via `followup.send()` once the work (and
        # the DM, which can independently fail if the user has DMs off)
        # is actually done.
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = interaction.user.id
        metadata = {"giveaway_id": self.giveaway_id}
        invisible_req = await giveaway_test_invisible_gate.create_verification(
            user_id=user_id, purpose="giveaway_test_invisible", metadata=metadata
        )
        pathtrace_req = await giveaway_test_pathtrace_gate.create_verification(
            user_id=user_id, purpose="giveaway_test_pathtrace", metadata=metadata
        )
        original_req = await giveaway_test_original_gate.create_verification(
            user_id=user_id, purpose="giveaway_test_original", metadata=metadata
        )
        url = (
            f"{_base_url}/giveaway-test/verify"
            f"?invisible={invisible_req.token}"
            f"&pathtrace={pathtrace_req.token}"
            f"&original={original_req.token}"
        )
        try:
            await interaction.user.send(f"Çekilişe katılmak için doğrulan: {url}")
        except discord.Forbidden:
            # Ephemeral -- invisible to everyone else in the channel.
            await interaction.followup.send(
                "DM'ine ulaşamadım (DM'lerin kapalı olabilir) -- doğrulama "
                f"linkin: {url}",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            "Kontrol ediliyor... DM'ine bir doğrulama linki gönderdim!", ephemeral=True
        )


@bot.hybrid_command(
    name="giveaway-test", description="Demo: gerçek bir çekiliş botu gibi bir 'Katıl' mesajı at"
)
async def giveaway_test(ctx: commands.Context, title: str = "Test çekilişi") -> None:
    global _next_giveaway_test_id
    giveaway_id = _next_giveaway_test_id
    _next_giveaway_test_id += 1
    _giveaway_test_titles[giveaway_id] = title
    _giveaway_test_participants[giveaway_id] = set()

    embed = discord.Embed(
        title=title,
        description=f"Katılmak için aşağıdaki butona tıkla. (giveaway_id={giveaway_id})",
    )
    await ctx.send(embed=embed, view=_GiveawayTestJoinView(giveaway_id))


@bot.hybrid_command(
    name="giveaway-test-participants",
    description="Demo: bir test çekilişine gerçekten katılanları listele",
)
async def giveaway_test_participants_cmd(ctx: commands.Context, giveaway_id: int) -> None:
    title = _giveaway_test_titles.get(giveaway_id)
    if title is None:
        await ctx.reply(f"giveaway_id={giveaway_id} bulunamadı.", ephemeral=True)
        return
    participants = _giveaway_test_participants.get(giveaway_id, set())
    if not participants:
        await ctx.reply(f"**{title}** -- henüz kimse katılmadı.", ephemeral=True)
        return
    mentions = "\n".join(f"- <@{user_id}>" for user_id in sorted(participants))
    await ctx.reply(
        f"**{title}** -- {len(participants)} katılımcı:\n{mentions}", ephemeral=True
    )


@app.get("/giveaway-test/verify")
async def giveaway_test_verify_page(
    invisible: str,
    pathtrace: str,
    original: str,
    user: DiscordUser | None = Depends(get_current_user_optional),
) -> HTMLResponse:
    if user is None:
        return HTMLResponse("""<!doctype html>
<title>Giriş yap</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:60px auto;padding:0 16px">
<h2>Önce giriş yap</h2>
<p>Doğrulama ekranını görebilmek için önce Discord hesabınla giriş yapman
gerekiyor. Giriş yaptıktan sonra bu linke (adres çubuğundakine) geri dön.</p>
<p><a href="/auth/discord/login" target="_blank" rel="noopener">Discord ile giriş yap</a></p>
</body>""")

    # All three tokens were minted for the same user in one button click
    # (see _GiveawayTestJoinView.join_button), so checking one is enough --
    # this catches a forwarded link or a mid-flow account switch before
    # showing anything solvable, the same fix applied to _verify_page.
    expected_user_id = await _expected_user_id(giveaway_test_invisible_gate, invisible)
    if expected_user_id is not None and expected_user_id != user.id:
        return _wrong_account_page(user.username)

    return HTMLResponse(f"""<!doctype html>
<title>Çekiliş doğrulaması</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 16px">
<h2>Merhaba, {user.username}</h2>
<p>Giriş yaptın -- şimdi iki ayrı doğrulama var:</p>

<h3>1) Uyarlanabilir (görünmez katmandan başlar)</h3>
<p style="font-size:.85rem;color:#666">
Önce sessizce gerçek bir arka plan işi (Proof-of-Work) + davranış skorunu
dener -- davranış sinyalleri istemci tarafından gönderildiği için tek
başına sahtelenebilir, PoW'un maliyeti sahtelenemez. Şüpheli görünürse
aşağıda ikinci bir widget belirip çizgiyi çizmeni ister.
</p>
<div id="invisible-widget" class="dwa-captcha-widget" data-token="{invisible}"
     data-api-base="/giveaway-test-invisible"></div>
<div id="pathtrace-widget-holder"></div>

<h3>2) Orijinal -- sade, tek başına bir Math captcha</h3>
<div class="dwa-captcha-widget" data-token="{original}"
     data-api-base="/giveaway-test-original"></div>

<script src="/static/discord-webapi-captcha-widget.js" data-callback="onWidgetVerified"></script>
<script>
var INVISIBLE_TOKEN = {invisible!r};
var PATHTRACE_TOKEN = {pathtrace!r};

function onWidgetVerified(result) {{
  // data-callback is one global name shared by every widget on this
  // page -- route on result.token so only the "invisible" widget's
  // outcome triggers the escalation logic below.
  if (result.token !== INVISIBLE_TOKEN) return;

  if (result.verified) {{
    document.getElementById("invisible-widget").insertAdjacentHTML(
      "afterend", "<p>Görünmez katman geçti, robot sanılmadın.</p>"
    );
    return;
  }}
  document.getElementById("pathtrace-widget-holder").innerHTML =
    "<p>Robot gibi göründün -- lütfen aşağıdaki çizgiyi çiz.</p>" +
    "<div class=\\"dwa-captcha-widget\\" data-token=\\"" + PATHTRACE_TOKEN +
    "\\" data-api-base=\\"/giveaway-test-pathtrace\\"></div>";
  if (window.dwaCaptchaWidgetInit) window.dwaCaptchaWidgetInit();
}}
</script>
</body>""")


# ---------------------------------------------------------------------
# Real AdaptiveCaptchaGate demo -- the library primitive this whole
# module's ad-hoc "invisible gate, then page JS reveals a second widget
# if it fails" pattern (scenario 4, above) was standing in for, for the
# specific case of IP reputation rather than the behavioral score.
# `AdaptiveCaptchaGate` makes the escalation decision server-side, the
# first time the link is opened, based on the connecting IP -- the
# bundled widget needs no special handling for this at all, since it
# already renders "no captcha" or "here's the challenge" from whatever
# get_info() returns.
#
# `blocklist` ships empty -- nobody's IP is suspicious by default. Two
# debug endpoints let you block/unblock *your own* connecting IP so you
# can watch the escalation actually happen without needing a real
# reputation service for this demo.
# ---------------------------------------------------------------------

blocklist = StaticBlocklistReputationChecker()
adaptive_gate = AdaptiveCaptchaGate(
    transport,
    MemoryVerificationStore(),
    blocklist,
    MathCaptchaProvider(_captcha_store),
    MemoryAdaptiveDecisionStore(),
    require_account=True,
    extra_checks=_behavior_checks(),
    trust_store=MemoryTrustStore(),
)
app.include_router(build_captcha_router(gate=adaptive_gate), prefix="/adaptive")


async def _on_adaptive_verified(event: CaptchaVerified) -> None:
    user = await bot.fetch_user(event.user_id)
    await user.send("Doğrulandı! (adaptive gate -- IP itibarına göre karar verildi)")


adaptive_gate.on_verified(_on_adaptive_verified, purpose="adaptive_join")


@bot.hybrid_command(
    name="join-adaptive", description="Demo: IP itibarına göre otomatik captcha isteyen gate"
)
async def join_adaptive(ctx: commands.Context) -> None:
    request = await adaptive_gate.create_verification(
        user_id=ctx.author.id, purpose="adaptive_join"
    )
    url = f"{_base_url}/verify/adaptive/{request.token}"
    await ctx.author.send(
        f"Doğrulan: {url}\n\n"
        "IP'n itibarımıza göre temizse hiç captcha görmeyeceksin -- sadece "
        "hesap + görünmez katman. Şüpheliyse gerçek bir Math captcha çıkar."
    )
    await ctx.reply("Sana DM attım!", ephemeral=True)


@app.get("/verify/adaptive/{token}")
async def verify_adaptive_page(
    token: str, user: DiscordUser | None = Depends(get_current_user_optional)
) -> HTMLResponse:
    return await _verify_page(token, "/adaptive", adaptive_gate, user)


@app.get("/api/test/block-my-ip")
async def block_my_ip(request: Request) -> dict:
    """Demo-only: lets you put your own connecting IP on the blocklist
    so you can physically watch AdaptiveCaptchaGate escalate to a real
    captcha, without needing an actual reputation service for this."""
    ip = request.client.host if request.client else None
    if ip is None:
        return {"blocked": None}
    blocklist.block(ip)
    return {"blocked": ip}


@app.get("/api/test/unblock-my-ip")
async def unblock_my_ip(request: Request) -> dict:
    ip = request.client.host if request.client else None
    if ip is None:
        return {"unblocked": None}
    blocklist.unblock(ip)
    return {"unblocked": ip}


# ---------------------------------------------------------------------
# Test page 1 -- just the widget, no login, no Discord round-trip: click
# it, and if the behavior signals look human it succeeds; if not, a
# second widget appears asking you to draw a line (Path-Trace). No
# account requirement here on purpose -- this page is about testing the
# *detection*, not account-binding (already covered by the giveaway/
# appeal gates above).
#
# This gate deliberately still requires real Proof-of-Work alongside the
# behavior score, NOT `require_captcha=False` on its own -- an earlier
# version of this test page used the behavior score as the only gate,
# which is exactly the mistake `scoring.py`'s own module docstring warns
# against: client-submitted signals (curvature, velocity variance,
# timing variance, a single click's offset from center, ...) are a
# *soft* signal, "a speed bump," never a standalone human/bot verdict --
# a single click, however many heuristics you run over it, is still one
# weak, forgeable data point. PoW is the one thing here with a real,
# unfakeable cost; the behavior score rides alongside it as an extra
# check, not as the sole judge.
# ---------------------------------------------------------------------

test1_behavior_gate = CaptchaGate(
    transport,
    MemoryVerificationStore(),
    ProofOfWorkProvider(_captcha_store),
    extra_checks=_behavior_checks(),
)
test1_pathtrace_gate = CaptchaGate(
    transport, MemoryVerificationStore(), PathTraceProvider(_captcha_store)
)
app.include_router(build_captcha_router(gate=test1_behavior_gate), prefix="/test1-behavior")
app.include_router(build_captcha_router(gate=test1_pathtrace_gate), prefix="/test1-pathtrace")

_test_synthetic_user_id = 900_000_000_000_000_000


def _next_synthetic_user_id() -> int:
    # No login on these test pages -- there's no real Discord account to
    # bind to, so each page load gets its own fake snowflake-shaped id,
    # just so require_account=False gates (which still take a user_id)
    # have something to key on.
    global _test_synthetic_user_id
    _test_synthetic_user_id += 1
    return _test_synthetic_user_id


def _escalation_page(
    title: str,
    intro_html: str,
    first_token: str,
    first_prefix: str,
    second_token: str,
    second_prefix: str,
    *,
    extra_body: str = "",
) -> HTMLResponse:
    # The same "try the invisible/behavior gate, only reveal the harder
    # one if it fails" page-JS composition already used by
    # /giveaway-test/verify above, factored out since pages 1, 2 and 4 all
    # need a version of it.
    return HTMLResponse(f"""<!doctype html>
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 16px">
<h2>{title}</h2>
{intro_html}
<div id="first-widget" class="dwa-captcha-widget" data-token="{first_token}"
     data-api-base="{first_prefix}"></div>
<div id="second-widget-holder"></div>
{extra_body}
<script src="/static/discord-webapi-captcha-widget.js" data-callback="onWidgetVerified"></script>
<script>
var FIRST_TOKEN = {first_token!r};
var SECOND_TOKEN = {second_token!r};

function onWidgetVerified(result) {{
  if (result.token !== FIRST_TOKEN) return;
  if (result.verified) {{
    document.getElementById("first-widget").insertAdjacentHTML(
      "afterend", "<p>İnsan gibi göründün -- ek bir teste gerek yok.</p>"
    );
    return;
  }}
  document.getElementById("second-widget-holder").innerHTML =
    "<p>Robot gibi göründün -- lütfen aşağıdaki çizgiyi çiz.</p>" +
    "<div class=\\"dwa-captcha-widget\\" data-token=\\"" + SECOND_TOKEN +
    "\\" data-api-base=\\"{second_prefix}\\"></div>";
  if (window.dwaCaptchaWidgetInit) window.dwaCaptchaWidgetInit();
}}
</script>
</body>""")


@app.get("/test-instant-widget")
async def test_instant_widget_page() -> HTMLResponse:
    user_id = _next_synthetic_user_id()
    behavior_req = await test1_behavior_gate.create_verification(
        user_id=user_id, purpose="test1_behavior"
    )
    pathtrace_req = await test1_pathtrace_gate.create_verification(
        user_id=user_id, purpose="test1_pathtrace"
    )
    return _escalation_page(
        "Test 1 -- anında widget",
        "<p>Kutucuğa tıkla. Fare/dokunma hareketlerin insan gibiyse doğrudan "
        "başarılı sayılırsın; robot gibi görünürse aşağıda çizgi-takip "
        "captcha'sı çıkar.</p>",
        behavior_req.token,
        "/test1-behavior",
        pathtrace_req.token,
        "/test1-pathtrace",
    )


# ---------------------------------------------------------------------
# Test page 2 -- the same detection pipeline as page 1, but this page
# does NOT use the bundled widget's real signal-collection at all: it
# deliberately sends hardcoded, obviously-bot-shaped signals with a raw
# fetch() call. The point isn't to test a real user's browser -- it's a
# red-team-style regression check that the detection genuinely rejects
# bad data every time, rather than being cosmetic.
# ---------------------------------------------------------------------


@app.get("/test-forced-bad-data")
async def test_forced_bad_data_page() -> HTMLResponse:
    user_id = _next_synthetic_user_id()
    behavior_req = await test1_behavior_gate.create_verification(
        user_id=user_id, purpose="test1_behavior"
    )
    pathtrace_req = await test1_pathtrace_gate.create_verification(
        user_id=user_id, purpose="test1_pathtrace"
    )
    return HTMLResponse(f"""<!doctype html>
<title>Test 2 -- sahte veri</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 16px">
<h2>Test 2 -- kasıtlı sahte/kötü veri</h2>
<p>Bu sayfa widget'ı hiç kullanmıyor -- doğrudan gate'in verify uç noktasına
elle uydurduğumuz, açıkça robot-gibi sinyaller gönderiyor
(<code>webdriver: true</code>, sıfır fare hareketi, anlık tıklama).
Amaç: tespitin gerçekten her seferinde reddettiğini kanıtlamak, kozmetik
olmadığını göstermek.</p>
<button id="send-bad" onclick="sendBad()">Sahte veriyi gönder</button>
<pre id="result" style="white-space:pre-wrap;background:#f4f4f4;padding:8px"></pre>
<div id="second-widget-holder"></div>

<script src="/static/discord-webapi-captcha-widget.js"></script>
<script>
var TOKEN = {behavior_req.token!r};
var PATHTRACE_TOKEN = {pathtrace_req.token!r};

async function sendBad() {{
  var res = await fetch("/test1-behavior/api/captcha/gate/" + TOKEN + "/verify", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{
      captcha_response: null,
      signals: {{
        webdriver: true,
        pointer_moves: 0,
        interaction_ms: 1,
        mouse_trajectory: [],
        click_offset_x: 0,
        click_offset_y: 0
      }}
    }})
  }});
  var body = await res.json();
  document.getElementById("result").textContent = JSON.stringify(body, null, 2) +
    (body.verified
      ? "\\n\\nBEKLENMEDIK: sahte veri geçti -- bu bir regresyon."
      : "\\n\\nBeklendiği gibi reddedildi (failed_check: " + body.failed_check + ").");
  if (!body.verified) {{
    document.getElementById("second-widget-holder").innerHTML =
      "<p>Beklendiği gibi şüpheli sayıldı -- ek test: aşağıdaki çizgiyi çiz.</p>" +
      "<div class=\\"dwa-captcha-widget\\" data-token=\\"" + PATHTRACE_TOKEN +
      "\\" data-api-base=\\"/test1-pathtrace\\"></div>";
    if (window.dwaCaptchaWidgetInit) window.dwaCaptchaWidgetInit();
  }}
}}
</script>
</body>""")


# ---------------------------------------------------------------------
# Test page 4 -- a Cloudflare "Under Attack Mode"-style interstitial:
# putting your own connecting IP on the shared `blocklist` (the same one
# /join-adaptive uses, via the same /api/test/block-my-ip debug endpoint)
# makes this page show a "verifying you are human" screen. Unlike
# /join-adaptive this needs no Discord login at all (a real Cloudflare-
# style gate runs in front of anonymous traffic) -- so a second, no-login
# `AdaptiveCaptchaGate` is used here.
#
# This is deliberately TWO tiers, not three: a real, honest escalation is
# "silent check, then -- only if that looks suspicious -- one real
# visible captcha," exactly what `AdaptiveCaptchaGate` already does
# natively (an earlier version of this page bolted on a second *silent*
# check between those two steps purely to have something to show for
# "double escalation" -- that's not a serious defense, it's theater: a
# bot that got past the first silent check would sail through an
# identical second one for the same reason, and a real user gets an
# extra pointless step for nothing). If the connecting IP is clean, this
# gate shows no captcha at all; if it's blocked, it shows one real Math
# challenge -- no manual page-JS chaining needed here at all, since this
# is exactly the single library primitive `AdaptiveCaptchaGate` exists
# for, the same as /join-adaptive minus the login requirement.
# ---------------------------------------------------------------------

test4_adaptive_gate = AdaptiveCaptchaGate(
    transport,
    MemoryVerificationStore(),
    blocklist,
    MathCaptchaProvider(_captcha_store),
    MemoryAdaptiveDecisionStore(),
)
app.include_router(build_captcha_router(gate=test4_adaptive_gate), prefix="/test4-adaptive")


@app.get("/test-cloudflare")
async def test_cloudflare_page() -> HTMLResponse:
    user_id = _next_synthetic_user_id()
    adaptive_req = await test4_adaptive_gate.create_verification(
        user_id=user_id, purpose="test4_adaptive"
    )
    return HTMLResponse(f"""<!doctype html>
<title>Test 4 -- kendi Cloudflare'imiz</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;
padding:0 16px;background:#f2f4f5">
<h2>Doğrulanıyor: bir insan mısın?</h2>
<p style="font-size:.85rem;color:#555">
IP itibarına göre karar veriliyor -- kara listeye kendi IP'ni eklemek için
<a href="/api/test/block-my-ip">/api/test/block-my-ip</a>, çıkarmak için
<a href="/api/test/unblock-my-ip">/api/test/unblock-my-ip</a>. IP'n
temizse bu kutu hiç captcha göstermeden geçer; kara listedeysen gerçek
bir Math sorusu çıkar.
</p>
<div class="dwa-captcha-widget" data-token="{adaptive_req.token}"
     data-api-base="/test4-adaptive"></div>
<script src="/static/discord-webapi-captcha-widget.js"></script>
</body>""")


# ---------------------------------------------------------------------
# Test page 5 -- an index/hub page linking every test scenario in this
# file together, so you don't have to remember every URL/command.
# ---------------------------------------------------------------------


@app.get("/test-index")
async def test_index_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html>
<title>Captcha test merkezi</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<body style="font-family:system-ui,sans-serif;max-width:520px;margin:40px auto;padding:0 16px">
<h2>Captcha test merkezi</h2>
<ul>
<li><a href="/test-instant-widget">Test 1 -- anında widget</a>: kutucuğa
tıkla, insansa başarılı, robotsa çizgi-takip'e yükseltir.</li>
<li><a href="/test-forced-bad-data">Test 2 -- kasıtlı sahte veri</a>:
widget'ı atlayıp elle uydurulmuş robot-sinyalleri gönderir, reddedildiğini
kanıtlar.</li>
<li>Test 3 -- Discord'da <code>/giveaway-test</code> komutu: gerçek bir
çekiliş botu gibi bir "Katıl" mesajı, doğrulanınca gerçekten katılımcı
listesine ekler (<code>/giveaway-test-participants</code> ile kontrol et).</li>
<li><a href="/test-cloudflare">Test 4 -- kendi Cloudflare'imiz</a>: IP'n
temizse sessizce geçersin; kara listeye ekleyince
(<a href="/api/test/block-my-ip">block-my-ip</a>) "insan mısın" ekranı tek
bir gerçek Math captcha'sı sorar.</li>
<li>Diğer senaryolar için Discord'da <code>/join</code>, <code>/appeal</code>,
<code>/test-join</code>, <code>/join-adaptive</code> komutlarını dene.</li>
</ul>
</body>""")
