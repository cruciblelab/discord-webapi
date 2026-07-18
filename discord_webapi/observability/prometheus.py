"""`PrometheusMetricsSink` -- a `MetricsSink` backed by `prometheus_client`.
Needs the `discord-webapi[metrics]` extra (`pip install
discord-webapi[metrics]`); nothing else in the library imports
`prometheus_client`, so it stays a fully optional dependency.

```python
from discord_webapi.observability.prometheus import PrometheusMetricsSink

metrics = PrometheusMetricsSink()
api = DiscordWebAPI(..., metrics=metrics)
# expose metrics.registry however you already serve Prometheus scrapes,
# e.g. prometheus_client.make_asgi_app(registry=metrics.registry) mounted
# as its own route.
```
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry, Counter, Histogram


def _sanitize(name: str) -> str:
    # Prometheus metric names may only contain [a-zA-Z0-9_:] -- this
    # library's own metric names use dots (matching the dotted
    # "discord_webapi.<subsystem>.<thing>" convention used everywhere
    # else, e.g. log logger names), so translate on the way in rather
    # than forcing every call site to know about Prometheus's stricter
    # charset.
    return name.replace(".", "_").replace("-", "_")


class PrometheusMetricsSink:
    """One registry per instance (own your own `CollectorRegistry` if you
    need to isolate this from `prometheus_client`'s global default one --
    e.g. running more than one `DiscordWebAPI` in the same process)."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        from prometheus_client import CollectorRegistry

        self.registry = registry if registry is not None else CollectorRegistry()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def increment(
        self, name: str, *, value: int = 1, tags: Mapping[str, str] | None = None
    ) -> None:
        from prometheus_client import Counter

        prom_name = _sanitize(name)
        counter = self._counters.get(prom_name)
        if counter is None:
            counter = Counter(
                prom_name, name, labelnames=sorted(tags) if tags else (), registry=self.registry
            )
            self._counters[prom_name] = counter
        (counter.labels(**tags) if tags else counter).inc(value)

    def observe(self, name: str, value: float, *, tags: Mapping[str, str] | None = None) -> None:
        from prometheus_client import Histogram

        prom_name = _sanitize(name)
        histogram = self._histograms.get(prom_name)
        if histogram is None:
            histogram = Histogram(
                prom_name, name, labelnames=sorted(tags) if tags else (), registry=self.registry
            )
            self._histograms[prom_name] = histogram
        (histogram.labels(**tags) if tags else histogram).observe(value)
