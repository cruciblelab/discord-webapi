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
