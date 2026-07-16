# test_console

A dedicated bot for **physical testing**, plus a one-page clickable test
console at `/console` — so you can click through `TESTING.md`'s checklist
instead of typing curl commands for every step.

## What's in the bot

- `/ping` — rate-limited (key `"ping"`), configurable live from the console.
- `/warn @member reason` — `extras.warn`, audited.
- `/warnings @member` — lists a tagged member's warning history, right in Discord.
- **automod** — deletes messages containing `badword1`/`badword2`/`badword3`,
  blocks invite links, and feeds both a `WarnStore` and the `EscalationEngine`
  (key `"automod"`) on every hit — so you can configure "3 hits = timeout,
  5 hits = kick" live and watch it actually fire.

Everything writes to one shared `AuditLogger` (dashboard writes, warns, and
automatic escalations all show up in the same `GET /audit-log`).

## The console (`/console`)

A single self-contained HTML page (no build step, no CDN dependencies) with
buttons for:

- **Commands**: list, toggle enable/disable, edit cooldown + `required_app_role`.
- **Rate limit**: get/set/delete a key's rule (defaults to `"ping"`).
- **Escalation**: set a rung (key/threshold/action/minutes), list, delete.
- **Warnings**: look up a tagged user's warning history.
- **Audit log**: see every dashboard write and automatic action in one feed.
- A raw last-response panel for whenever something looks off.

Login is one click: "Discord ile giriş yap" → approve in Discord → you land
back on `/console` with the session token already filled in (via
`mobile_redirect_uri`, no cookie/CORS juggling needed even from a phone
browser on a different device than the one running the bot).

## Running it

```bash
pip install -e ".[sql]"                      # from the repo root
cp examples/test_console/.env.example examples/test_console/.env
# fill in .env -- see that file's comments for exactly what's needed
set -a && source examples/test_console/.env && set +a
uvicorn main:app --reload --app-dir examples/test_console
```

Then:

1. Invite the bot to your test server (`applications.commands` + `bot`
   scopes, and grant it `Manage Messages`/`Timeout Members`/`Kick Members`/
   `Ban Members` if you want automod's deletes and the escalation ladder's
   actions to actually take effect rather than fail silently with a
   "missing permissions" note).
2. Open `http://localhost:8000/console` in a browser — or, if
   `DASHBOARD_BASE_URL` points at a LAN address, from your phone.
3. Fill in the Guild ID (Discord Developer Mode → right-click your test
   server → Copy Server ID), click "Discord ile giriş yap".
4. Work through `TESTING.md` sections 1-21, clicking instead of curl-ing.

## Testing across your 7 servers

Since this bot will run on 7 real servers: test destructive stuff (automod
deletes, escalation kick/ban, cooldown/rate-limit behavior) on 2-3 of your
own test servers first — the console's Guild ID field switches targets
instantly, no restart, so you can point the same running bot+console at a
different server just by changing that one field and re-fetching. Get a
second Discord account (or borrow a friend's) to test the "user without
permission gets 403" and "different users have independent rate-limit
buckets" cases for real, not just in the automated test suite.
