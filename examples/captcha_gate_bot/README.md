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

## Why two gates need two URL prefixes

`build_captcha_router()`'s default reads a single
`app.state.discord_webapi_captcha_gate` -- fine for one gate purpose. This
example has two (`giveaway_gate`, `appeal_gate`), so each is mounted
explicitly via `build_captcha_router(gate=...)` under its own prefix
(`/giveaway`, `/appeal`), and the widget's `data-api-base` attribute
points at the matching prefix. See `discord_webapi/captcha/api.py`'s
module docstring for the general pattern.

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
