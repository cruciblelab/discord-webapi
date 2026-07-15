"""Optional live WebSocket relay for command-config changes.

Off by default (`DiscordWebAPI.install(app, enable_websocket=True)` /
`quickstart(..., enable_websocket=True)`) -- every connection holds one
asyncio task plus one Transport subscription for as long as it's open, a
real (if modest) resource cost that deployments which don't want it, or
whose host doesn't comfortably support long-lived connections, shouldn't
be forced to pay. With it off, the dashboard just polls
`GET /api/guilds/{guild_id}/commands` as it already does.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from discord_webapi.auth.oauth import DiscordAuth
from discord_webapi.authz.cache import GuildMemberCache
from discord_webapi.authz.permissions import has_permission
from discord_webapi.commands.events import EVENT_TYPE_COMMAND_CONFIG_CHANGED, CommandConfigChanged
from discord_webapi.transport.base import Event, Transport

# Not standard WebSocket close codes (those are reserved below 4000) --
# 4401/4403 mirror the HTTP 401/403 this relay would return if it were a
# regular endpoint, so a client can tell "not logged in" from "logged in
# but not allowed here" without parsing a reason string.
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_FORBIDDEN = 4403


async def _relay_until_disconnect(
    websocket: WebSocket, queue: asyncio.Queue[CommandConfigChanged]
) -> None:
    """Forwards queued events to the client, *and* watches for the client
    disconnecting -- without the watch side, a client that closes its tab
    is never noticed until (if ever) the next event happens to arrive and
    `send_json` fails, since the relay loop otherwise never touches the
    socket while waiting on the queue. Left unfixed, a quiet guild (no
    command changes) with clients that come and go leaks one subscriber +
    one blocked task per abandoned connection, forever, in a long-running
    deployment.
    """

    async def _forward_events() -> None:
        while True:
            change = await queue.get()
            await websocket.send_json(change.model_dump())

    async def _watch_for_disconnect() -> None:
        while True:
            # The raw `receive()` does *not* raise on a disconnect message
            # (only `receive_text`/`receive_json`/etc. do, via their own
            # `_raise_on_disconnect` check) -- it just returns the message,
            # and calling `receive()` again afterwards raises a RuntimeError
            # instead. This client is never expected to send anything on
            # this socket, so any non-disconnect message is simply ignored.
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000), message.get("reason"))

    forward_task = asyncio.create_task(_forward_events())
    watch_task = asyncio.create_task(_watch_for_disconnect())
    try:
        done, pending = await asyncio.wait(
            {forward_task, watch_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()  # re-raises WebSocketDisconnect, or any real error
    finally:
        for task in (forward_task, watch_task):
            task.cancel()
        for task in (forward_task, watch_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task


def build_commands_websocket_router(transport: Transport) -> APIRouter:
    router = APIRouter()

    @router.websocket("/api/guilds/{guild_id}/commands/stream")
    async def commands_stream(websocket: WebSocket, guild_id: int) -> None:
        auth: DiscordAuth = websocket.app.state.discord_webapi_auth
        member_cache: GuildMemberCache = websocket.app.state.discord_webapi_member_cache

        try:
            user = await auth.get_current_user(websocket)
        except HTTPException:
            await websocket.close(code=_CLOSE_UNAUTHORIZED)
            return

        info = await member_cache.get(guild_id, user.id)
        if info is None or not has_permission(info.permissions, "manage_guild"):
            await websocket.close(code=_CLOSE_FORBIDDEN)
            return

        await websocket.accept()
        queue: asyncio.Queue[CommandConfigChanged] = asyncio.Queue()

        async def handler(event: Event) -> None:
            change = CommandConfigChanged.model_validate(event.payload)
            if change.guild_id == guild_id:
                await queue.put(change)

        transport.subscribe(EVENT_TYPE_COMMAND_CONFIG_CHANGED, handler)
        try:
            await _relay_until_disconnect(websocket, queue)
        except WebSocketDisconnect:
            pass
        finally:
            # Without this, every connect/disconnect cycle leaks one
            # subscriber entry that keeps trying to queue.put() into a
            # queue nobody's reading anymore -- unbounded over a long-lived
            # deployment with many dashboard clients coming and going.
            transport.unsubscribe(EVENT_TYPE_COMMAND_CONFIG_CHANGED, handler)

    return router
