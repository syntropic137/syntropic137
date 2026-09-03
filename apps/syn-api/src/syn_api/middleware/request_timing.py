"""ASGI middleware and in-process aggregator for per-route request timing.

Addresses #1070: the API records nothing about its own request latency, so a
slow endpoint cannot be diagnosed from inside the process. This is the
narrowest slice of that issue - per-route wall-time percentiles over a
rolling window. It deliberately does NOT add a within-request DB/handler/
serialization breakdown or an operator-facing surface (dashboard panel or
JSON endpoint); those are separate, larger pieces of work (see #1070).

Lane 2 (observability) only, per the Two-Lane Architecture rule: this data
never touches the event store or any aggregate, and is lost on restart.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

_DEFAULT_WINDOW_SIZE = 500


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty list."""
    idx = int(len(sorted_values) * fraction)
    return sorted_values[min(idx, len(sorted_values) - 1)]


class RouteTimingSnapshot:
    """Percentiles and count for one route template at a point in time."""

    def __init__(self, count: int, p50_ms: float, p95_ms: float, p99_ms: float) -> None:
        self.count = count
        self.p50_ms = p50_ms
        self.p95_ms = p95_ms
        self.p99_ms = p99_ms


class RequestTimingAggregator:
    """Rolling-window, per-route-template request duration aggregator.

    Keeps at most ``window_size`` most recent durations per route template
    (oldest evicted first) and reports p50/p95/p99 + count on demand.
    In-process only - never persisted, never replayed, safe to lose on
    restart, per the Two-Lane Architecture rule for Lane 2 telemetry.
    """

    def __init__(self, window_size: int = _DEFAULT_WINDOW_SIZE) -> None:
        self._window_size = window_size
        self._durations_ms: dict[str, deque[float]] = {}
        self._lock = Lock()

    def record(self, route_template: str, duration_ms: float) -> None:
        with self._lock:
            window = self._durations_ms.setdefault(route_template, deque(maxlen=self._window_size))
            window.append(duration_ms)

    def snapshot(self, route_template: str) -> RouteTimingSnapshot | None:
        with self._lock:
            window = self._durations_ms.get(route_template)
            if not window:
                return None
            sorted_values = sorted(window)

        return RouteTimingSnapshot(
            count=len(sorted_values),
            p50_ms=_percentile(sorted_values, 0.50),
            p95_ms=_percentile(sorted_values, 0.95),
            p99_ms=_percentile(sorted_values, 0.99),
        )

    def known_routes(self) -> list[str]:
        with self._lock:
            return list(self._durations_ms.keys())


# Process-wide singleton - one aggregator per API process, mirroring the
# process-wide lifetime of the middleware stack itself.
request_timing_aggregator = RequestTimingAggregator()


def _route_template(scope: Scope) -> str:
    """Best-effort route template for *scope*, falling back to the raw path.

    FastAPI's ``APIRoute.matches`` sets ``scope["route"] = self`` once a route
    is matched, so this is only reachable after the downstream app has run.
    Unmatched requests (404s) have no ``route`` key - fall back to the raw
    path so those durations aren't silently dropped, at the cost of not
    aggregating across raw path variants for that case.
    """
    route = scope.get("route")
    path = route.path if route is not None else None
    return path if isinstance(path, str) else str(scope.get("path", ""))


class RequestTimingMiddleware:
    """ASGI middleware that records wall-clock duration per route template."""

    def __init__(self, app: ASGIApp, aggregator: RequestTimingAggregator | None = None) -> None:
        self.app = app
        self._aggregator = aggregator if aggregator is not None else request_timing_aggregator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._aggregator.record(_route_template(scope), duration_ms)
