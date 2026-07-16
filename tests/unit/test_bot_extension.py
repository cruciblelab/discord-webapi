import asyncio
from types import SimpleNamespace

import discord
import pytest

from discord_webapi.bot.extension import (
    install_channel_permission_lookup,
    install_guild_listing,
    install_member_lookup,
    run_bot_process,
    single_process_lifespan,
    web_only_lifespan,
)
from discord_webapi.jobs import InProcessJobQueue
from discord_webapi.jobs.worker import run_worker
from discord_webapi.transport import InProcessTransport

GUILD_ID = 999
USER_ID = 42


class _FakeRole:
    def __init__(self, id_: int) -> None:
        self.id = id_


class _FakeMember:
    def __init__(self, id_: int, roles: list[_FakeRole]) -> None:
        self.id = id_
        self.roles = roles
        self.guild_permissions = discord.Permissions(manage_guild=True)


class _FakeChannel:
    def __init__(self, permissions: discord.Permissions) -> None:
        self._permissions = permissions

    def permissions_for(self, member: _FakeMember) -> discord.Permissions:
        return self._permissions


def _make_guild(member: _FakeMember, channel: _FakeChannel | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        get_member=lambda uid: member if uid == member.id else None,
        get_channel=lambda cid: channel if channel is not None else None,
        name="Test Guild",
        icon=None,
    )


async def test_install_member_lookup_found_path_returns_roles_and_permissions() -> None:
    member = _FakeMember(USER_ID, [_FakeRole(1), _FakeRole(2)])
    guild = _make_guild(member)
    bot = SimpleNamespace(
        get_guild=lambda gid: guild if gid == GUILD_ID else None,
        add_listener=lambda func, name: None,
    )
    transport = InProcessTransport()

    install_member_lookup(bot, transport)  # type: ignore[arg-type]
    response = await transport.request("get_member", {"guild_id": GUILD_ID, "user_id": USER_ID})

    assert response["found"] is True
    assert response["role_ids"] == [1, 2]
    assert response["permissions"] == discord.Permissions(manage_guild=True).value


async def test_install_member_lookup_publishes_on_role_change() -> None:
    # SimpleNamespace has no add_listener -- a minimal stand-in that
    # captures registered listeners so this test can actually invoke them.
    listeners: dict[str, object] = {}

    class _ListenerBot:
        def get_guild(self, gid: int) -> None:
            return None

        def add_listener(self, func: object, name: str) -> None:
            listeners[name] = func

    transport = InProcessTransport()
    received = []

    async def on_member_updated(event: object) -> None:
        received.append(event)

    transport.subscribe("member_updated", on_member_updated)

    install_member_lookup(_ListenerBot(), transport)  # type: ignore[arg-type]

    before = SimpleNamespace(roles=[_FakeRole(1)])
    after = SimpleNamespace(
        roles=[_FakeRole(1), _FakeRole(2)], guild=SimpleNamespace(id=GUILD_ID), id=USER_ID
    )
    await listeners["on_member_update"](before, after)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].payload == {"guild_id": GUILD_ID, "user_id": USER_ID}


async def test_install_channel_permission_lookup_found_path() -> None:
    permissions = discord.Permissions(send_messages=True)
    member = _FakeMember(USER_ID, [])
    channel = _FakeChannel(permissions)
    guild = _make_guild(member, channel)
    bot = SimpleNamespace(get_guild=lambda gid: guild if gid == GUILD_ID else None)
    transport = InProcessTransport()

    install_channel_permission_lookup(bot, transport)  # type: ignore[arg-type]
    response = await transport.request(
        "get_channel_permissions", {"guild_id": GUILD_ID, "channel_id": 1, "user_id": USER_ID}
    )

    assert response["found"] is True
    assert response["permissions"] == permissions.value


async def test_install_guild_listing_returns_manageable_guilds() -> None:
    member = _FakeMember(USER_ID, [])
    guild = _make_guild(member)
    bot = SimpleNamespace(get_guild=lambda gid: guild if gid == GUILD_ID else None)
    transport = InProcessTransport()

    install_guild_listing(bot, transport)  # type: ignore[arg-type]
    response = await transport.request(
        "list_manageable_guilds", {"guild_ids": [GUILD_ID, 111], "user_id": USER_ID}
    )

    assert len(response["guilds"]) == 1
    assert response["guilds"][0]["guild_id"] == GUILD_ID


class _FakeDiscordBot:
    def __init__(self, *, fail_before_ready: bool = False) -> None:
        self.closed = False
        self._fail_before_ready = fail_before_ready

    async def start(self, token: str) -> None:
        if self._fail_before_ready:
            raise RuntimeError("bad token")
        await asyncio.sleep(3600)  # never returns on its own

    async def wait_until_ready(self) -> None:
        if self._fail_before_ready:
            await asyncio.sleep(3600)  # bot_task fails first
        # else: ready "immediately"

    async def close(self) -> None:
        self.closed = True


async def test_single_process_lifespan_starts_and_stops_transport() -> None:
    bot = _FakeDiscordBot()
    transport = InProcessTransport()

    async with single_process_lifespan(bot, transport, "fake-token"):  # type: ignore[arg-type]
        pass

    assert bot.closed is True


async def test_single_process_lifespan_surfaces_bot_startup_failure() -> None:
    bot = _FakeDiscordBot(fail_before_ready=True)
    transport = InProcessTransport()

    with pytest.raises(RuntimeError, match="bad token"):
        async with single_process_lifespan(bot, transport, "fake-token"):  # type: ignore[arg-type]
            pytest.fail("should never reach the yield")


async def test_web_only_lifespan_starts_and_stops_transport() -> None:
    started = []
    stopped = []

    class _TrackingTransport(InProcessTransport):
        async def start(self) -> None:
            started.append(True)
            await super().start()

        async def stop(self) -> None:
            stopped.append(True)
            await super().stop()

    transport = _TrackingTransport()
    async with web_only_lifespan(transport):
        assert started == [True]
        assert stopped == []

    assert stopped == [True]


async def test_run_bot_process_blocks_until_cancelled() -> None:
    bot = _FakeDiscordBot()
    transport = InProcessTransport()

    task = asyncio.create_task(run_bot_process(bot, transport, "fake-token"))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_worker_starts_and_stops_the_queue() -> None:
    queue = InProcessJobQueue()
    task = asyncio.create_task(run_worker(queue))
    await asyncio.sleep(0.05)
    assert not task.done()
    assert queue._workers  # started

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert queue._workers == []  # stopped
