# captcha_gate_bot

The two concrete bot-command scenarios `webapi_captcha.gate.CaptchaGate`
was built for, wired up against a **real** discord.py bot with **real**
Discord OAuth account-binding -- not the `captcha_playground` example's
fake `user_id=0`.

## Scenario 1 -- giveaway entry (`/join`)

```
/join giveaway_name:spring-giveaway
```

The bot DMs a one-time verification link. The linked page shows the
bundled widget (`webapi_captcha.widget`) running in "safety mode":
invisible Proof-of-Work + the behavioral score + `RepeatedMovementCheck`,
**and** you must be signed in as the exact Discord account the link was
issued for (`require_account=True`) -- this is what makes it "this account
joined," not just "someone solved a captcha." The bot DMs "you're in!" the
moment `CaptchaGate.on_verified()` fires, no polling.

## Scenario 2 -- an escalation-gated command (`/appeal`)

```
/simulate-ban @member     -- demo-only: bumps a fake ban counter
/appeal reason:...         -- refused until re-verified, once BAN_THRESHOLD is hit
```

A **separate** `CaptchaGate` (its own purpose, its own verification link)
gates a different command once a user crosses `BAN_THRESHOLD` (a stand-in
for your own moderation history -- swap `_ban_count_for` for a real
`WarnStore`/`EscalationEngine` lookup). Once verified, they stay cleared
for this demo's lifetime (a real bot would persist that, not use an
in-memory `set`).

Solving the verification widget DMs a confirmation ("Doğrulandın! Artık
`/appeal` komutunu tekrar çalıştırıp itirazını gönderebilirsin.") -- a
real bug reported from testing was this handler doing nothing user-facing
at all, so solving the captcha looked like "nothing happened" even though
it had actually cleared the user (this demo doesn't remember the original
`reason` across the verification round-trip, so you do have to resend
`/appeal` yourself; a real bot might queue and auto-resubmit it instead).

## Scenario 3 -- side-by-side captcha comparison (`/test-compare-captchas`, `/test-participants`)

```
/test-compare-captchas -- DMs a button; clicking it replies with one link
/test-participants      -- lists everyone who has completed any of the 3 below
```

**Not a real join flow** -- deliberately no login requirement and no
"you're in!" confirmation (a real bug report from testing was confusion
over exactly this: solving the captchas here does nothing visible
because there's nothing to join, no giveaway, no account binding. The
command used to be named `/test-join` with a "Katıl" (Join) button,
which implied otherwise -- renamed to make clear this is purely a
side-by-side comparison of *captcha configurations*. The real
login-required, auto-join-on-success flow is Scenario 4 below).

Clicking the button mints three fresh tokens (one per `CaptchaGate`
config below) and hands back a single link to `/test-widgets`, which
stacks all three on one page for direct comparison:

1. **Path-Trace** -- purely visual/interactive, no invisible layer at all.
2. **"Safety mode"** -- a visible Math captcha is required, *and* so is
   the invisible behavior score. Passing the behavior score does **not**
   let you skip the visible captcha -- both are ANDed. Try submitting a
   wrong Math answer with otherwise perfectly human-like signals: it
   still fails, specifically on the `"captcha"` check, not the behavior
   one.
3. **"Original"** -- the plain baseline, one Math captcha, nothing else.

This scenario is what surfaced a real bug in the library while building
it: five `CaptchaGate`s (this repo's two above plus these three) all
share one `Transport`, and `captcha_verified` is one event type broadcast
to every gate on it. `on_verified()` used to have no way to filter, so
subscribing on any one gate silently received *every other gate's*
verifications too (confirmed with two simulated users -- the participant
count came out as 6, not 2, until this was fixed). `CaptchaGate.on_verified()`
now takes an optional `purpose=` filter -- every `on_verified()` call in
this example (including the giveaway/appeal ones above) passes it, and
the three test gates each get their own distinct `purpose` string
specifically so `/test-participants` counts correctly.

## Scenario 4 -- a real giveaway simulation with adaptive escalation (`/giveaway-test`)

```
/giveaway-test    -- posts a public embed + "Katıl" button, like a real giveaway
```

Clicking it replies **ephemerally** (invisible to everyone else in the
channel) and DMs the clicking user a verify link. That link requires
Discord login **first** -- the page checks server-side and shows nothing
but a login link until you're signed in, then shows two independent
verification slots:

1. **Adaptive** -- starts invisible: real Proof-of-Work (the server
   recomputes the hash, so "I did the work" can't be faked) plus the
   behavior score plus account-binding. **Behavior signals alone are not
   enough** -- they're client-submitted, so anyone who knows the scoring
   rules can send values that pass, which is exactly what this repo's own
   verification below did on purpose to exercise the logic. That's why
   PoW is in the mix: it's the one thing here that isn't just a claim. If
   the signals still look suspicious after that, a *second* widget
   appears below asking you to draw a line (Path-Trace). `CaptchaGate`
   has no built-in escalation feature -- this composes **two separate
   gates** via the page's own JS (try the invisible one, only reveal the
   Path-Trace one if that fails), the same "compose your own" pattern the
   whole library follows.
2. **Original** -- a single, always-required Math captcha, independent
   of the above.

Verified directly against the gates (bypassing the OAuth round-trip,
which needs a live browser): bot-like signals (`webdriver: true`, no
pointer movement, near-instant) fail immediately, before Proof-of-Work
even matters; hand-crafted human-like signals *without* a solved PoW
response still fail (on the `"captcha"` check) -- proving good-looking
signals alone aren't sufficient; only human-like signals *plus* a
genuinely solved PoW nonce pass. The Path-Trace fallback separately
verifies a real drawn line. The page itself was also confirmed to show
no captcha at all before login.

## Why multiple gates need multiple URL prefixes

`build_captcha_router()`'s default reads a single
`app.state.webapi_captcha_gate` -- fine for one gate purpose. This
example has six (`giveaway_gate`, `appeal_gate`, the three test gates
above, and `adaptive_gate` below), so each is mounted explicitly via
`build_captcha_router(gate=...)` under its own prefix (`/giveaway`,
`/appeal`, `/test-path-trace`, `/test-safety`, `/test-original`,
`/adaptive`), and each widget's `data-api-base` attribute points at the
matching prefix. See `discord_webapi/captcha/api.py`'s module docstring
for the general pattern.

## Scenario 5 -- IP-reputation-driven escalation (`/join-adaptive`)

```
/join-adaptive             -- DMs a verify link
GET /api/test/block-my-ip   -- demo-only: put your own connecting IP on the blocklist
GET /api/test/unblock-my-ip
```

The real library primitive behind Scenario 4's manual "invisible gate,
then reveal a Path-Trace widget if it fails" JS composition -- but driven
by IP reputation instead of the behavior score, and decided **server-side**
rather than by page JS: `webapi_captcha.adaptive.AdaptiveCaptchaGate`.
`create_verification()` mints a token with no captcha decided yet; the
first time the link is opened (`get_info()`/`verify()`), the connecting
IP is checked against `blocklist` (a `StaticBlocklistReputationChecker`
here -- a plain IP/CIDR list, not a real reputation service) and the
decision (captcha or not) is made and persisted right there. A clean IP
never sees a captcha at all -- just the invisible layer
(`require_account=True` + behavior score, same as the other gates); a
blocked one gets a real Math challenge. Once verified, `trust_store`
remembers the user for 24h so they aren't asked again on a repeat visit.

**No widget changes needed for any of this** -- the bundled widget
already renders "no captcha" or "here's the challenge" from whatever
`get_info()` returns; it has no idea the gate behind it is adaptive.

Verified via `TestClient` without a live Discord connection: a clean IP's
`get_info()` reports `requires_captcha: false` and `verify()` passes with
no captcha response; hitting `/api/test/block-my-ip` (which blocks the
caller's own connecting IP) and minting a fresh token then shows
`requires_captcha: true` with a real Math challenge, and unblocking flips
it back -- the debug endpoints genuinely control the escalation, not just
cosmetically.

## Standalone test pages (`/test-index`)

Five pages exercising the detection pipeline directly, with no Discord
round-trip needed for most of them -- start at `/test-index` for a hub
linking all of them.

1. **`/test-instant-widget`** -- just the bundled widget, no login, no
   account requirement (`CaptchaGate(require_captcha=False,
   extra_checks=_behavior_checks())`). Click it: human-like signals
   succeed immediately; bot-like ones (real ones, from an actual
   automated browser -- not this repo's own hand-crafted test data)
   reveal a second widget below, bound to a separate Path-Trace gate.
2. **`/test-forced-bad-data`** -- the exact same two gates as page 1, but
   the page's own JS skips the widget entirely and posts a raw,
   hardcoded, obviously-bot-shaped payload straight to the gate's
   `/verify` endpoint (`webdriver: true`, zero pointer movement,
   1ms interaction time). This is a red-team-style regression check, not
   a real-user test: it proves the rejection is real and repeatable, not
   cosmetic -- verified directly (see below): the response comes back
   `verified: false, failed_check: "no-webdriver"` every time.
3. **`/giveaway-test`'s participant bookkeeping** -- see Scenario 4 above.
   Solving either the adaptive or the original widget on that flow now
   really adds the signed-in user to that specific giveaway's
   participant set (keyed by a `giveaway_id` assigned per
   `/giveaway-test title:...` invocation), checkable with
   `/giveaway-test-participants giveaway_id:N`.
4. **`/test-cloudflare`** -- a Cloudflare "Under Attack Mode"-style
   interstitial, reusing the exact same `blocklist` object (and
   `/api/test/block-my-ip`/`unblock-my-ip` debug endpoints) as Scenario
   5's `/join-adaptive`, but through a *second*, no-login-required
   `AdaptiveCaptchaGate` -- a real anonymous-traffic gate has no account
   to require. Deliberately just **two** tiers, not three: silent check,
   then -- only if the IP is blocked -- one real, visible Math captcha,
   exactly what `AdaptiveCaptchaGate` already does on its own. An
   earlier version of this page bolted on an extra *silent* behavior
   check between those two steps to simulate "double escalation" -- that
   was cut: a second silent check a bot already passed once tells you
   nothing new, it's not a real additional defense, just an extra
   pointless step for a genuine user.
5. **`/test-full-guard`** and **`/test-secure-login`** -- see
   `webapi_captcha.pageguard.PageGuard` below, the real
   reusable infrastructure version of `/test-cloudflare`.
6. **`/test-index`** -- links all of the above (plus the Discord-side
   commands) with a one-line description of each.

Verified directly with `TestClient` (no live Discord connection needed
for any of these five, since none require login): page 1 and 2's shared
`test1-behavior` gate genuinely rejects `{webdriver: true, pointer_moves:
0, interaction_ms: 1, mouse_trajectory: []}` every time
(`failed_check: "no-webdriver"`); `/api/test/block-my-ip` genuinely
flips what `/test-cloudflare`'s first widget requires, same as it does
for `/join-adaptive`.

## `PageGuard` -- Cloudflare in front of a whole page, not one link (`/test-full-guard`, `/test-secure-login`)

`AdaptiveCaptchaGate` (Scenario 5 above, `/test-cloudflare`) protects one
already-minted verification link. `webapi_captcha.pageguard.
PageGuard` is the same IP-reputation-driven escalation applied at
PAGE-LOAD time instead -- put it in front of *any* route (whatever your
own admin panel decides needs it), including a page that comes *before*
Discord OAuth login even starts, which is exactly what a real request
from testing asked for: "cloudflare gibi tam kapasite geniş bir
altyapıda verelim... discord yetkilendirmesinden önce de captcha."

On every guarded request:

1. The visitor is identified -- the signed-in Discord account if there
   is one, otherwise a random value in an httpOnly cookie (minted
   invisibly on first visit, no page shown for it).
2. If already trusted -- and, since this demo's guard sets
   `bind_trust_to_ip=True` on its `AdaptiveCaptchaGate`, still connecting
   from the *same* IP that earned that trust (a real request from
   testing: "ip değişme sıklığı... başka ipden bağlanırsa hemen
   captcha") -- the page loads with nothing shown at all.
3. Otherwise: IP reputation is checked, plus one extra, honest,
   zero-JS server-side signal this demo wires up --
   `pageguard.missing_accept_language` (real browsers virtually always
   send an `Accept-Language` header; its absence is a mild, non-JS bot
   signal, combined with IP reputation, never relied on alone -- the
   "tarayıcı dil bilgisi" signal asked for in testing). Clean -> loads
   silently, same as a trusted visitor. Suspicious -> redirected to a
   real Path-Trace challenge (the most comprehensive captcha in this
   project, chosen deliberately for "make the test solid" over the
   plain Math captcha) instead of ever seeing the page; solving it
   redirects straight back to where you started.

`/test-secure-login` applies the exact same guard to a page that offers
nothing but a "log in with Discord" link (or a logout button, if
already signed in) -- demonstrating the guard running *before* any
Discord OAuth interaction, not after.

Same "use it or don't" rule as everywhere else: `PageGuard` is a small,
optional, composable class, not wired into `DiscordWebAPI.install()` or
any route automatically -- every guarded route in this file calls
`guard.require_human()` itself, and nothing stops you from writing your
own equivalent, using reCAPTCHA/Turnstile instead, or skipping page-level
guarding entirely.

Verified directly with `TestClient` (`client=(ip, port)` to simulate
different connecting IPs, no live Discord needed): a clean IP loads the
page with `200` and no redirect, minting a visitor cookie only once;
blocking the IP redirects (`307`) to a real Path-Trace challenge instead
of showing the page; solving it (a real geometrically- and
kinematically-faithful trace, `client_ip` matching) lets the *same*
visitor+IP through silently afterward; a *different* visitor cookie on
the *same* still-blocked IP is redirected again; and the *same* visitor
cookie connecting from a *different* (also blocked) IP is redirected
again too -- proving `bind_trust_to_ip` actually forces a re-check on IP
change, not just on a fresh visitor. `/test-secure-login` was verified
the same way: a clean IP sees the Discord login link immediately, a
blocked IP is redirected to the captcha *before* that link is ever
rendered.

## Showing who you're signed in as, and catching a forwarded link early

Every login-gated verify page (`/verify/giveaway`, `/verify/appeal`,
`/verify/adaptive`, `/giveaway-test/verify`) now does two things before
it renders anything solvable:

1. If you're signed in, it says so ("Giriş yaptın: **username**" /
   "Merhaba, **username**").
2. It checks the token's *intended* user against who's actually signed
   in -- `AccountMatchCheck` already rejects a mismatched account at
   *verify* time, but that means finding out only after clicking through
   and trying to solve the captcha. Checking ownership up front instead
   shows a clear "this link isn't yours" page immediately (with a link
   to log out and sign back in with the right account) rather than a
   confusing failed-check after the fact -- catches a forwarded link or
   a mid-flow account switch before any captcha is even shown.

Verified directly with `TestClient` (auth dependency override, no live
Discord needed): signed out shows the login link and no widget; signed
in as the wrong account shows the "isn't yours" page and no widget;
signed in as the right account shows the username and the widget.

## Running it

```bash
pip install -e "."                              # PoW needs no extras at all
cp examples/captcha_gate_bot/.env.example examples/captcha_gate_bot/.env
# fill in .env, then:
set -a && source examples/captcha_gate_bot/.env && set +a
uvicorn main:app --reload --app-dir examples/captcha_gate_bot
```

Invite the bot to a real test server (`applications.commands` + `bot`
scopes) and try both commands there -- this needs a live Discord
connection to test end to end, same as every other bot example in this
repo (see `TESTING.md`'s general physical-test pattern).
