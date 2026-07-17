# captcha_gate_bot

The two concrete bot-command scenarios `discord_webapi.captcha.gate.CaptchaGate`
was built for, wired up against a **real** discord.py bot with **real**
Discord OAuth account-binding -- not the `captcha_playground` example's
fake `user_id=0`.

## Scenario 1 -- giveaway entry (`/join`)

```
/join giveaway_name:spring-giveaway
```

The bot DMs a one-time verification link. The linked page shows the
bundled widget (`discord_webapi.captcha.widget`) running in "safety mode":
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

## Scenario 3 -- side-by-side captcha comparison (`/test-join`, `/test-participants`)

```
/test-join            -- DMs a button; clicking it replies with one link
/test-participants     -- lists everyone who has completed any of the 3 below
```

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
`app.state.discord_webapi_captcha_gate` -- fine for one gate purpose. This
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
rather than by page JS: `discord_webapi.captcha.adaptive.AdaptiveCaptchaGate`.
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
   to require. Passing that first check is not automatically the end:
   a stricter second-tier behavior-only gate (`test4_strict_gate`) runs
   next, and only if that one *also* looks suspicious does a third,
   final Path-Trace widget appear -- a genuine double-escalation chain,
   composed the same "page JS reveals the next gate on failure" way as
   every other escalation in this file, not a new library feature.
5. **`/test-index`** -- links all of the above (plus the Discord-side
   commands) with a one-line description of each.

Verified directly with `TestClient` (no live Discord connection needed
for any of these five, since none require login): page 1 and 2's shared
`test1-behavior` gate genuinely rejects `{webdriver: true, pointer_moves:
0, interaction_ms: 1, mouse_trajectory: []}` every time
(`failed_check: "no-webdriver"`); `/api/test/block-my-ip` genuinely
flips what `/test-cloudflare`'s first widget requires, same as it does
for `/join-adaptive`.

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
