"""`discord_webapi.observability`: the `MetricsSink` Protocol itself
(`NoOpMetricsSink`, `PrometheusMetricsSink`), plus that the four
subsystems it's wired into (transport RPC, jobs, escalation, commands)
actually call it -- via a spy sink, not by depending on a real Prometheus
scrape."""

import asyncio
from collections.abc import Mapping

import discord
from discord.ext import commands as dpy_commands

from discord_webapi.commands.registry import CommandRegistry
from discord_webapi.escalation import EscalationAction, EscalationEngine
from discord_webapi.escalation.memory import MemoryEscalationRuleStore, MemoryViolationStore
from discord_webapi.exceptions import TransportError, TransportTimeoutError
from discord_webapi.jobs.memory import InProcessJobQueue
from discord_webapi.observability import NOOP_METRICS, NoOpMetricsSink
from discord_webapi.storage.memory import MemoryCommandConfigStore
from discord_webapi.transport.inprocess import InProcessTransport

GUILD_ID = 1


class _SpyMetricsSink:
    def __init__(self) -> None:
        self.increments: list[tuple[str, int, dict[str, str]]] = []
        self.observations: list[tuple[str, float, dict[str, str]]] = []

    def increment(
        self, name: str, *, value: int = 1, tags: Mapping[str, str] | None = None
    ) -> None:
        self.increments.append((name, value, dict(tags or {})))

    def observe(self, name: str, value: float, *, tags: Mapping[str, str] | None = None) -> None:
        self.observations.append((name, value, dict(tags or {})))


# -- MetricsSink primitives ------------------------------------------------


def test_noop_metrics_sink_does_nothing() -> None:
    sink = NoOpMetricsSink()

    sink.increment("anything")
    sink.increment("anything", value=5, tags={"a": "b"})
    sink.observe("anything", 1.23)

    assert sink is not None  # nothing to assert on -- just must not raise


def test_noop_metrics_singleton_is_the_default() -> None:
    assert isinstance(NOOP_METRICS, NoOpMetricsSink)


def test_prometheus_metrics_sink_increment_and_observe() -> None:
    from discord_webapi.observability.prometheus import PrometheusMetricsSink

    sink = PrometheusMetricsSink()

    sink.increment("discord_webapi.test.counter", tags={"kind": "a"})
    sink.increment("discord_webapi.test.counter", value=2, tags={"kind": "a"})
    sink.increment("discord_webapi.test.counter", tags={"kind": "b"})
    sink.observe("discord_webapi.test.duration_seconds", 0.5, tags={"kind": "a"})

    assert sink.registry.get_sample_value(
        "discord_webapi_test_counter_total", {"kind": "a"}
    ) == 3.0
    assert sink.registry.get_sample_value(
        "discord_webapi_test_counter_total", {"kind": "b"}
    ) == 1.0
    assert (
        sink.registry.get_sample_value(
            "discord_webapi_test_duration_seconds_sum", {"kind": "a"}
        )
        == 0.5
    )


def test_prometheus_metrics_sink_without_tags() -> None:
    from discord_webapi.observability.prometheus import PrometheusMetricsSink

    sink = PrometheusMetricsSink()

    sink.increment("discord_webapi.test.untagged")

    assert sink.registry.get_sample_value("discord_webapi_test_untagged_total") == 1.0


# -- Transport RPC latency/errors ------------------------------------------


async def test_inprocess_transport_records_rpc_latency() -> None:
    spy = _SpyMetricsSink()
    transport = InProcessTransport(metrics=spy)
    transport.register_handler("ping", lambda payload: asyncio.sleep(0, result={"pong": True}))

    response = await transport.request("ping", {})

    assert response == {"pong": True}
    assert len(spy.observations) == 1
    name, value, tags = spy.observations[0]
    assert name == "discord_webapi.transport.request_seconds"
    assert value >= 0
    assert tags == {"command": "ping"}
    assert spy.increments == []


async def test_inprocess_transport_records_error_for_unregistered_command() -> None:
    spy = _SpyMetricsSink()
    transport = InProcessTransport(metrics=spy)

    try:
        await transport.request("missing", {})
    except TransportError:
        pass
    else:
        raise AssertionError("expected TransportError")

    assert spy.increments == [
        ("discord_webapi.transport.request_errors", 1, {"command": "missing"})
    ]


async def test_inprocess_transport_records_error_and_latency_on_timeout() -> None:
    spy = _SpyMetricsSink()
    transport = InProcessTransport(metrics=spy)

    async def _hang(payload: dict) -> dict:
        await asyncio.sleep(10)
        return {}

    transport.register_handler("slow", _hang)

    try:
        await transport.request("slow", {}, timeout=0.01)
    except TransportTimeoutError:
        pass
    else:
        raise AssertionError("expected TransportTimeoutError")

    assert spy.increments == [
        ("discord_webapi.transport.request_errors", 1, {"command": "slow"})
    ]
    assert len(spy.observations) == 1
    assert spy.observations[0][0] == "discord_webapi.transport.request_seconds"


# -- Job execution ----------------------------------------------------------


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true within timeout")


async def test_job_queue_records_success_and_failure() -> None:
    spy = _SpyMetricsSink()
    queue = InProcessJobQueue(metrics=spy)

    async def ok(payload: dict) -> dict:
        return {"done": True}

    async def bad(payload: dict) -> dict:
        raise RuntimeError("boom")

    queue.register_worker("ok_job", ok)
    queue.register_worker("bad_job", bad)
    await queue.start()
    try:
        await queue.enqueue("ok_job", {})
        await queue.enqueue("bad_job", {})
        await _wait_until(lambda: len(spy.increments) >= 2)
    finally:
        await queue.stop()

    assert ("discord_webapi.jobs.executed", 1, {"job_type": "ok_job", "state": "succeeded"}) in (
        spy.increments
    )
    assert ("discord_webapi.jobs.executed", 1, {"job_type": "bad_job", "state": "failed"}) in (
        spy.increments
    )


# -- Escalation triggers -----------------------------------------------------


class _FakeRole:
    def __init__(self, position: int) -> None:
        self.position = position

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, _FakeRole):
            return NotImplemented
        return self.position >= other.position


class _FakeBotMember:
    top_role = _FakeRole(10)


class _FakeGuild:
    id = GUILD_ID
    me = _FakeBotMember()

    async def kick(self, member: object, *, reason: str | None = None) -> None:
        return None


class _FakeMember:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.guild = _FakeGuild()
        self.top_role = _FakeRole(1)  # below the bot's -- kick may proceed

    async def timeout(self, until: object, *, reason: str | None = None) -> None:
        return None


async def test_escalation_engine_records_a_triggered_rung() -> None:
    spy = _SpyMetricsSink()
    engine = EscalationEngine(
        InProcessTransport(), MemoryEscalationRuleStore(), MemoryViolationStore(), metrics=spy
    )
    member = _FakeMember(100)
    await engine.set_rule(GUILD_ID, "warn", 1, action=EscalationAction.KICK)

    outcome = await engine.record_violation(member, "warn")  # type: ignore[arg-type]

    assert outcome.triggered_rule is not None
    assert spy.increments == [
        (
            "discord_webapi.escalation.triggered",
            1,
            {"key": "warn", "action": "kick", "applied": "True"},
        )
    ]


async def test_escalation_engine_records_nothing_when_no_rung_fires() -> None:
    spy = _SpyMetricsSink()
    engine = EscalationEngine(
        InProcessTransport(), MemoryEscalationRuleStore(), MemoryViolationStore(), metrics=spy
    )
    member = _FakeMember(100)

    await engine.record_violation(member, "warn")  # type: ignore[arg-type]

    assert spy.increments == []


# -- Command invocation counting ---------------------------------------------


async def test_command_registry_records_each_invocation() -> None:
    spy = _SpyMetricsSink()
    bot = dpy_commands.Bot(command_prefix="!", intents=discord.Intents.default(), help_command=None)

    @bot.hybrid_command(name="ping")
    async def ping(ctx: dpy_commands.Context) -> None: ...

    transport = InProcessTransport()
    registry = CommandRegistry(
        bot, transport=transport, store=MemoryCommandConfigStore(), metrics=spy
    )
    await registry.register_all()

    registry._count_invocation(GUILD_ID, "ping")
    registry._count_invocation(GUILD_ID, "ping")

    assert spy.increments == [
        ("discord_webapi.commands.invoked", 1, {"command": "ping"}),
        ("discord_webapi.commands.invoked", 1, {"command": "ping"}),
    ]
