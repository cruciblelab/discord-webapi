# full_featured_bot

Every optional feature turned on at once, meant for hands-on testing --
not a "getting started" example (see `examples/single_process_bot/` for
that). This is the companion to `../../TESTING.md`'s manual test
checklist.

## What's turned on here

- `enable_websocket=True` -- live `command_config_changed` push at
  `/api/guilds/{guild_id}/commands/stream`. Use `ws_test_client.py` in
  this folder to actually watch it (see that script's docstring).
- `enable_audit_log=True` -- `GET /api/guilds/{guild_id}/audit-log` records
  every command-override and AppRole change.
- `enable_cookie_consent=True` -- the bundled dashboard shows a
  cookie-consent banner with custom message text.
- Every builtin from `discord_webapi.builtins`: `ban`, `kick`, `timeout`,
  `warn` (with `auto_timeout_after=3` -- three warnings auto-mutes),
  `role_assign` (`/role-add`/`/role-remove`), `automod` (a whole
  subpackage of independent checks -- banned words, spam, mention-spam,
  invite links, link domains, caps, emoji; `banned_words_list=[]` by
  default -- add real words to see it trigger, invite-blocking is on),
  `welcome` (needs a real `channel_id` from your server -- see the
  comment in `main.py`).

- `enable_ratelimits_api=True` -- `PUT/DELETE /api/guilds/{id}/ratelimits/{key}`
  dashboard endpoints. `main.py`'s hand-written `/ping` command
  demonstrates the "hybrid" use case: it's not a `discord_webapi.builtins`
  command and doesn't use `CommandRegistry`'s own per-command cooldown --
  it calls `GuildRateLimiter` directly (`app.state.discord_webapi_ratelimiter`),
  keyed as `"ping"`, per-server-configurable from the dashboard.

- `enable_escalation_api=True` -- `PUT/DELETE
  /api/guilds/{id}/escalation-rules/{key}[/{threshold}]` dashboard
  endpoints. `automod`'s `on_violation` hook feeds
  `app.state.discord_webapi_escalation_engine.record_violation(member,
  "automod", ...)` -- no threshold/action is hardcoded anywhere in
  `automod` itself; configure the ladder from the dashboard, e.g. `PUT
  .../escalation-rules/automod/3 {"action": "timeout", "action_minutes": 10}`.

Everything else (`AppRole`, per-command cooldowns, multi-DB) isn't
something you turn on in code -- it's configured live through the
dashboard API once the bot is running. `../../TESTING.md` walks through
exercising all of it, including these.

## Running it

Same as `single_process_bot` -- see that example's README for the
Discord Developer Portal setup steps (bot token, OAuth2 redirect URI,
Server Members intent) and the Termux notes if you're testing from a
phone. Then:

```
pip install -e ".[sql]"
cp examples/full_featured_bot/.env.example examples/full_featured_bot/.env
# fill in .env
set -a && source examples/full_featured_bot/.env && set +a
uvicorn main:app --reload --app-dir examples/full_featured_bot
```

To also try the WebSocket relay:

```
pip install websockets   # only needed for this test script, not the library
python examples/full_featured_bot/ws_test_client.py <guild_id> <session_id>
```

(`session_id` is the `dwa_session` cookie value after logging into
`/dashboard` in a browser -- see `ws_test_client.py`'s docstring for the
exact steps.)
