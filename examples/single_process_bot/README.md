# single_process_bot

The v0.1 reference deployment, built with `DiscordWebAPI.quickstart()`: one
process, one asyncio event loop, `InProcessTransport`, SQLite-backed
session/command storage — the whole web/auth/storage side in about a dozen
real lines of code on top of your own discord.py commands (`main.py` is 47
lines total, most of it a usage comment).

See the walkthrough at the top of `main.py`.

## What this demonstrates

- **`DiscordWebAPI.quickstart(bot=bot)`**: reads `DISCORD_BOT_TOKEN` /
  `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` / `DWA_FERNET_KEY` /
  `DASHBOARD_BASE_URL` from the environment, wires up SQLite storage
  (`dashboard.sqlite3`, created automatically), `InProcessTransport`,
  `DiscordAuth`, the `DiscordWebAPI` facade, and the FastAPI lifespan, and
  hands back a ready-to-run `FastAPI` app. This is sugar over the
  composable API (`DiscordAuth(...)` + `DiscordWebAPI(...)` +
  `api.install(app)`) for the common single-process case — see
  `DiscordWebAPI`'s docstring if you need a different transport/storage
  backend or multiple bots.
- **`default_intents()`**: `Intents.default()` + `members=True` in one call
  — the member cache and dashboard both need it.
- **Dashboard UI**: `/` and `/dashboard` serve discord-webapi's *bundled*
  default dashboard (no build step, plain fetch() calls — works fine from
  a phone browser, e.g. testing over Termux): a login link, a Guild ID
  field, and a member table with role badges. Pass
  `serve_dashboard=False` to `quickstart()`/`install()` once you want your
  own UI instead.
- **Member listing**: `GET /api/guilds/{guild_id}/members` — every member
  of that guild with their display name, avatar, and role names, read from
  the bot's own Gateway cache (never a Discord REST call). View-only: no
  ban/kick/moderation actions are exposed.
- **Command listing + live disable, no restart**:
  `GET /api/guilds/{guild_id}/commands` lists `ping`/`say` with their
  enabled state; `PATCH .../commands/ping {"enabled": false}` takes effect
  on the very next `/ping` invocation in Discord — the command registry's
  enforcement check is an in-memory lookup kept warm by a Transport event,
  not a restart or a poll.

Both the member list and the command list require "Manage Server"
permission in the target guild (`require_guild_permission("manage_guild")`,
wired in automatically).

## Notes

- Sessions and command overrides persist in `dashboard.sqlite3` next to
  this file — restarting the process (e.g. `--reload` picking up a code
  change) doesn't log you out or forget which commands were disabled.
- `cookie_secure` is derived from whether `DASHBOARD_BASE_URL` is
  `https://` — keep it `http://localhost:...` for local testing, use a
  real HTTPS URL (and a stable `DWA_FERNET_KEY`) before deploying anywhere
  real.

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
