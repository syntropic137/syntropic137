"""ASGI middleware and in-process aggregator for per-route request timing.

Addresses #1070: the API records nothing about its own request latency, so a
slow endpoint cannot be diagnosed from inside the process. This is the
narrowest slice of that issue - per-route wall-time percentiles over a
rolling window. It deliberately does NOT add a within-request DB/handler/
serialization breakdown or an operator-facing surface (dashboard panel or
JSON endpoint); those are separate, larger pieces of work (see #1070).

Lane 2 (observability) only, per the Two-Lane Architecture rule: this data
never touches the event store or any aggregate, and is lost on restart.

SLOW REQUESTS ARE ALSO LOGGED (#1583), one line each, so a stall can be
attributed from the logs alone: was the API slow, and was it waiting for a
database connection? Only requests at or over
``slow_request_log_threshold_ms`` are logged - a line per request would bury
everything else - and the line carries the method, the route TEMPLATE, the
status and two durations, never the raw path, query string, headers or body:
ids, tokens and credentials all pass through here.

EVERY REQUEST IS ALSO RECORDED DURABLY (ADR-073): the same method, route
template, status and time-to-response-start, with a request id, are offered to
the request latency recorder, which batches them into the observability
database off the request path. The id is returned as ``x-request-id`` and named
on the slow-request line, so a slow line and its row can be joined.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING

from syn_adapters.postgres_pool import tally_pool_wait
from syn_adapters.request_latency import (
    RequestLatencyRecorder,
    RequestSample,
    request_latency_recorder,
)

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

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


#: What a slow-request line names when no route matched. The raw path is never
#: logged, so an unmatched path carrying an id or a token cannot leak through.
UNMATCHED_ROUTE = "<unmatched>"


def _logged_route(scope: Scope) -> str:
    route = scope.get("route")
    path = route.path if route is not None else None
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class RequestTimingMiddleware:
    """ASGI middleware that times every request and logs the slow ones.

    Every request's wall-clock duration is recorded per route template in the
    aggregator. A request whose response STARTED at least
    ``slow_request_ms`` after it arrived is also logged. Time to response start
    rather than to the last byte, so a long-lived stream (SSE) that answered
    promptly is not reported as slow when it eventually closes.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        slow_request_ms: int,
        aggregator: RequestTimingAggregator | None = None,
        recorder: RequestLatencyRecorder | None = None,
    ) -> None:
        self.app = app
        self._aggregator = aggregator if aggregator is not None else request_timing_aggregator
        self._recorder = recorder if recorder is not None else request_latency_recorder
        self._slow_request_ms = slow_request_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        arrived = datetime.now(UTC)
        request_id = uuid.uuid4().hex
        responded_at: float | None = None
        status: int | None = None

        async def send_noting_response_start(message: Message) -> None:
            nonlocal responded_at, status
            if message["type"] == "http.response.start":
                responded_at = time.perf_counter()
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        with tally_pool_wait() as pool_wait:
            try:
                await self.app(scope, receive, send_noting_response_start)
            except Exception:
                # An unhandled exception propagates past this middleware to
                # Starlette's ServerErrorMiddleware, which answers 500. Record
                # the status the client will see; the exception still raises.
                if status is None:
                    status = 500
                raise
            finally:
                end = time.perf_counter()
                self._aggregator.record(_route_template(scope), (end - start) * 1000)
                # No response started means the handler raised or the client
                # went away: the whole time was spent without an answer.
                duration_ms = ((responded_at or end) - start) * 1000
                route = _logged_route(scope)
                self._recorder.offer(
                    RequestSample(
                        time=arrived,
                        method=scope["method"],
                        route=route,
                        # No response started: the client got the 500 or nothing.
                        status=status if status is not None else 500,
                        duration_ms=duration_ms,
                        request_id=request_id,
                    )
                )
                if duration_ms >= self._slow_request_ms:
                    logger.warning(
                        "slow request method=%s route=%s status=%s duration_ms=%d "
                        "pool_wait_ms=%d request_id=%s",
                        scope["method"],
                        route,
                        status if status is not None else "-",
                        duration_ms,
                        pool_wait.wait_ms,
                        request_id,
                    )
