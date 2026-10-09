"""Per-route latency percentiles over a time window (ADR-075).

Exact: ``percentile_cont`` over every row in the window, not an estimate. At
the volumes this API serves (a few requests a second, 30 days retained) a
sort per route is cheap; ADR-075 says when to switch to a sketch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_adapters.request_latency.schema import TABLE

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

_QUERY = f"""
    SELECT method, route, n, p, worst FROM (
        SELECT method, route, count(*) AS n,
               percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY duration_ms) AS p,
               max(duration_ms) AS worst
        FROM {TABLE}
        WHERE time >= $1 AND ($2::text IS NULL OR route = $2)
        GROUP BY method, route
    ) AS by_route
    ORDER BY p[3] DESC, method, route
"""


@dataclass(frozen=True, slots=True)
class RouteLatency:
    method: str
    route: str
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


async def latency_by_route(
    pool: asyncpg.Pool, *, since: datetime, route: str | None = None
) -> list[RouteLatency]:
    """Every (method, route template) answered since ``since``, slowest p99 first."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_QUERY, since, route)  # type: ignore[union-attr]  # asyncpg generates PoolConnectionProxy's methods at runtime
    return [
        RouteLatency(
            method=row["method"],
            route=row["route"],
            count=row["n"],
            p50_ms=row["p"][0],
            p95_ms=row["p"][1],
            p99_ms=row["p"][2],
            max_ms=row["worst"],
        )
        for row in rows
    ]
