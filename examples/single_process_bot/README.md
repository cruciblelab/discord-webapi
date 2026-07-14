# single_process_bot

The v0.1 reference deployment: one process, one asyncio event loop, the bot
and the dashboard API sharing `InProcessTransport` — no Redis, no SQL, just
`pip install discord-webapi` and go.

See the walkthrough at the top of `main.py`.

## What this demonstrates

- **Login**: `/auth/discord/login` → Discord OAuth2 → opaque session cookie.
- **Command listing**: `GET /api/guilds/{guild_id}/commands` returns both
  registered commands (`ping`, `say`) with their live enabled/disabled state.
- **Live disable, no restart**: `PATCH /api/guilds/{guild_id}/commands/ping`
  with `{"enabled": false}` takes effect on the very next `/ping` invocation
  in Discord — the command registry's enforcement check is an in-memory
  lookup kept warm by a Transport event, not a restart or a poll.

## Notes

- `cookie_secure` is derived from whether `DASHBOARD_BASE_URL` is `https://`
  — keep it `http://localhost:...` for local testing, use a real HTTPS URL
  (and a stable `DWA_FERNET_KEY`) before deploying anywhere real.
- Sessions and command overrides both live in memory here (the default
  `MemorySessionStore`/`MemoryCommandConfigStore`) — restarting the process
  clears them. Swap in `discord-webapi[sql]`'s SQL-backed stores for
  anything longer-lived.
