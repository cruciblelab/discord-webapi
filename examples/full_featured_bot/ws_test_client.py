"""Standalone WebSocket test client for the opt-in command-config relay
(`enable_websocket=True` in main.py, `/api/guilds/{guild_id}/commands/stream`).

This is the piece the automated test suite can't exercise end to end
(see `tests/integration/test_websocket.py`'s docstring) -- Starlette's
TestClient runs each WebSocket connection on its own background
thread/event loop, which doesn't mix with InProcessTransport's
asyncio.Queue. So the real round-trip -- connect here, PATCH a command
elsewhere, see the push arrive -- has to be checked by hand. This script
is that hand.

Needs `websockets` (not a discord-webapi dependency -- just for this
script): `pip install websockets`

Usage:
    1. Get a session ID: log into the dashboard in a browser
       (http://localhost:8000/dashboard), then read the `dwa_session`
       cookie's value from your browser's dev tools (Application ->
       Cookies). Needs "Manage Server" in the target guild.
    2. python ws_test_client.py <guild_id> <session_id> [base_url]
    3. From another terminal (or curl), while this is running:
       curl -X PATCH http://localhost:8000/api/guilds/<guild_id>/commands/ping \\
           -H "Content-Type: application/json" -H "Cookie: dwa_session=<session_id>" \\
           -d '{"enabled": false}'
       -- a `command_config_changed` event should print here immediately.
"""

from __future__ import annotations

import asyncio
import sys

import websockets


async def main(guild_id: str, session_id: str, base_url: str) -> None:
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    uri = f"{ws_url}/api/guilds/{guild_id}/commands/stream"
    print(f"Connecting to {uri} ...")

    headers = {"Cookie": f"dwa_session={session_id}"}
    async with websockets.connect(uri, additional_headers=headers) as ws:
        print("Connected. Waiting for command_config_changed events (Ctrl+C to stop)...")
        async for message in ws:
            print("event:", message)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <guild_id> <session_id> [base_url]")
        raise SystemExit(1)

    guild_id_arg = sys.argv[1]
    session_id_arg = sys.argv[2]
    base_url_arg = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8000"

    try:
        asyncio.run(main(guild_id_arg, session_id_arg, base_url_arg))
    except KeyboardInterrupt:
        pass
