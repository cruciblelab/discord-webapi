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
"""

from __future__ import annotations

import os

import discord
from discord.ext import commands
from fastapi import Depends
from fastapi.responses import HTMLResponse

from discord_webapi import DiscordWebAPI
from discord_webapi.auth.dependencies import get_current_user_optional
from discord_webapi.auth.models import DiscordUser
from discord_webapi.bot import default_intents
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


class _GiveawayTestJoinView(discord.ui.View):
    """A real giveaway bot would register this with `bot.add_view()` so
    the button keeps working across restarts -- skipped here to keep the
    demo to one file."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Katıl", style=discord.ButtonStyle.success, custom_id="giveaway_test_join"
    )
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        user_id = interaction.user.id
        invisible_req = await giveaway_test_invisible_gate.create_verification(
            user_id=user_id, purpose="giveaway_test_invisible"
        )
        pathtrace_req = await giveaway_test_pathtrace_gate.create_verification(
            user_id=user_id, purpose="giveaway_test_pathtrace"
        )
        original_req = await giveaway_test_original_gate.create_verification(
            user_id=user_id, purpose="giveaway_test_original"
        )
        url = (
            f"{_base_url}/giveaway-test/verify"
            f"?invisible={invisible_req.token}"
            f"&pathtrace={pathtrace_req.token}"
            f"&original={original_req.token}"
        )
        # Ephemeral -- invisible to everyone else in the channel.
        await interaction.response.send_message(
            "Kontrol ediliyor... DM'ine bir doğrulama linki gönderdim!", ephemeral=True
        )
        await interaction.user.send(f"Çekilişe katılmak için doğrulan: {url}")


@bot.hybrid_command(
    name="giveaway-test", description="Demo: gerçek bir çekiliş botu gibi bir 'Katıl' mesajı at"
)
async def giveaway_test(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="Test çekilişi", description="Katılmak için aşağıdaki butona tıkla."
    )
    await ctx.send(embed=embed, view=_GiveawayTestJoinView())


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
