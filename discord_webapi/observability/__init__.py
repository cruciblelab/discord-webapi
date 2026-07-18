"""Optional, opt-in production observability -- see `MetricsSink`'s
docstring in `discord_webapi.observability.base` for the full picture.
`PrometheusMetricsSink` (needs `discord-webapi[metrics]`) lives in its own
module (`discord_webapi.observability.prometheus`) rather than here, so
importing this package never requires `prometheus_client`.
"""

from discord_webapi.observability.base import NOOP_METRICS, MetricsSink, NoOpMetricsSink

__all__ = ["NOOP_METRICS", "MetricsSink", "NoOpMetricsSink"]
