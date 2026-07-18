"""`MetricsSink` -- an optional, opt-in metrics hook usable from any
subsystem that wants to expose "how much is this actually doing in
production" (transport RPC latency, job execution counts, escalation
triggers, command invocations) without imposing a dependency on any
specific metrics backend.

Same "bring your own, or don't" pattern as every `Store`/`Transport` in
this library: `NoOpMetricsSink` (the default everywhere) does nothing and
costs essentially nothing to call; pass your own implementation (or the
bundled `PrometheusMetricsSink`, see `discord_webapi.observability.prometheus`)
to actually collect something.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class MetricsSink(Protocol):
    """Two primitives are enough for everything this library emits:
    counters (`increment`) for "how many times did X happen" (a command
    was invoked, a job finished, a rung fired) and observations
    (`observe`) for a numeric measurement's distribution (RPC latency in
    seconds). `tags` is a flat string->string label set (e.g.
    `{"command": "kick"}`, `{"job_type": "send_dm", "state": "succeeded"}`)
    -- exactly what Prometheus labels/OpenTelemetry attributes expect.
    """

    def increment(
        self, name: str, *, value: int = 1, tags: Mapping[str, str] | None = None
    ) -> None: ...

    def observe(
        self, name: str, value: float, *, tags: Mapping[str, str] | None = None
    ) -> None: ...


class NoOpMetricsSink:
    """Does nothing. The default everywhere a `metrics:` parameter exists
    -- passing no sink at all costs one attribute lookup and two empty
    method calls, no allocation, no branching on "is this enabled"."""

    def increment(
        self, name: str, *, value: int = 1, tags: Mapping[str, str] | None = None
    ) -> None:
        return None

    def observe(self, name: str, value: float, *, tags: Mapping[str, str] | None = None) -> None:
        return None


# One shared instance -- stateless, so there's no reason for every
# `metrics: MetricsSink = NOOP_METRICS` default to construct its own.
NOOP_METRICS = NoOpMetricsSink()
