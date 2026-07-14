# single_process_bot

The v0.1 reference deployment: one process, one asyncio event loop, the bot
and the dashboard API sharing `InProcessTransport` — no Redis, no SQL, just
`pip install discord-webapi` and go.

See the walkthrough at the top of `main.py`.

## What this demonstrates

- **Dashboard UI**: `/` (and `/dashboard`) serve a single self-contained
  HTML page (`static/dashboard.html`, no build step, plain fetch() calls —
  works fine from a phone browser, e.g. testing over Termux) with a login
  link, a Guild ID field, and a member table.
- **Login**: `/auth/discord/login` → Discord OAuth2 → opaque session cookie.
- **Member listing**: `GET /api/guilds/{guild_id}/members` — every member
  of that guild with their display name, avatar, and role names, read from
  the bot's own Gateway cache (never a Discord REST call). View-only: no
  ban/kick/moderation actions are exposed.
- **Command listing**: `GET /api/guilds/{guild_id}/commands` returns both
  registered commands (`ping`, `say`) with their live enabled/disabled state.
- **Live disable, no restart**: `PATCH /api/guilds/{guild_id}/commands/ping`
  with `{"enabled": false}` takes effect on the very next `/ping` invocation
  in Discord — the command registry's enforcement check is an in-memory
  lookup kept warm by a Transport event, not a restart or a poll.

Both the member list and the command list require "Manage Server"
permission in the target guild (`require_guild_permission("manage_guild")`).

## Notes

- `cookie_secure` is derived from whether `DASHBOARD_BASE_URL` is `https://`
  — keep it `http://localhost:...` for local testing, use a real HTTPS URL
  (and a stable `DWA_FERNET_KEY`) before deploying anywhere real.
- Sessions and command overrides both live in memory here (the default
  `MemorySessionStore`/`MemoryCommandConfigStore`) — restarting the process
  clears them. Swap in `discord-webapi[sql]`'s SQL-backed stores for
  anything longer-lived.

## Running this on Termux (Android)

- `pip install cryptography` often fails to build from source on Termux
  (no prebuilt wheel for Android). Install Termux's own prebuilt package
  first so pip reuses it instead of compiling: `pkg install python-cryptography`
  before `pip install -e ".[sql]"`. If it still tries to build from source,
  `pkg install rust` first.
- Open `http://localhost:8000/dashboard` in the phone's own browser — the
  bot, the API, and the browser are all on the same device, so no extra
  networking setup is needed.
- Your Discord application's OAuth2 redirect URI (Developer Portal) must
  match `DASHBOARD_BASE_URL` from `.env` exactly, e.g.
  `http://localhost:8000/auth/discord/callback`.
