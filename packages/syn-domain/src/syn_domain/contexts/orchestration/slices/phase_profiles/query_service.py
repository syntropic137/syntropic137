"""Per-phase-type usage profiles for one workflow over a window (#1716).

The capacity model (docs/north-star.md) and the execution budget (#1715) need
what a phase of a given type USUALLY costs, not what one execution cost. This
service answers that from Lane 2 alone: tokens from the usage rollup through
the canonical decision (the same one every cost read applies), resources from
the ``workspace_resource_usage`` observation written at phase teardown
(#1608). Nothing here touches an aggregate or the event store.

Every percentile is computed over EVERY phase in the window - the queries are
not paged - and each one carries the ``n`` it was computed over. Below
``MIN_SAMPLES`` a percentile is ``None``: a p90 of four phases is a guess
dressed as a measurement.

A "phase type" is a workflow phase id: every execution of a workflow runs the
same phase definitions, so one phase id across executions is one population.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import asyncpg

    from syn_domain.contexts.agent_sessions.canonical_usage import PricingResolver

from syn_domain.contexts.agent_sessions import (
    price_canonical_row,
    recorded_model_from_row,
    rollup_usage_sources,
)
from syn_domain.contexts.agent_sessions.canonical_usage import CANONICAL_MODEL_COLUMNS
from syn_domain.storable_text import pg_safe
from syn_shared.events import WORKSPACE_RESOURCE_USAGE

MIN_SAMPLES = 10
"""Fewer phases than this and no percentile is reported."""

UNKNOWN_MODEL = "unknown"

# Which phase a session ran in. agent_events is the only place a session is
# joined to its phase: the usage rollup has no phase_id. Narrowed by execution
# (idx_events_execution) and by the window, so this is bounded by the
# workflow's recent work, not by telemetry volume.
_PHASE_SESSIONS_CTE = """
phase_sessions AS (
    SELECT DISTINCT session_id, execution_id, phase_id
    FROM agent_events
    WHERE execution_id = ANY($1::text[])
      AND phase_id IS NOT NULL
      AND time >= $2
)"""

# Canonical usage per (execution, phase, model). Grouped on the model columns
# canonical usage carries per row, so a phase that fell back to another model
# mid-phase contributes its tokens to the model that consumed them - not to
# the workflow's default. Grouped on cost-nullness for the reason every
# canonical read is (#788).
_TOKEN_QUERY = f"""
WITH {_PHASE_SESSIONS_CTE},
{rollup_usage_sources("execution_id = ANY($1::text[])")}
SELECT
    ps.execution_id,
    ps.phase_id,
    {", ".join(f"cu.{c.strip()}" for c in CANONICAL_MODEL_COLUMNS.split(","))},
    SUM(cu.vendor_cost_usd) AS vendor_cost_usd,
    SUM(cu.input_tokens) AS input_tokens,
    SUM(cu.output_tokens) AS output_tokens,
    SUM(cu.cache_creation_tokens) AS cache_creation_tokens,
    SUM(cu.cache_read_tokens) AS cache_read_tokens
FROM canonical_usage cu
JOIN phase_sessions ps ON ps.session_id = cu.session_id
GROUP BY ps.execution_id, ps.phase_id,
    {", ".join(f"cu.{c.strip()}" for c in CANONICAL_MODEL_COLUMNS.split(","))},
    (cu.vendor_cost_usd IS NULL)
"""

# Every phase seen in the window, with its usage row when one was written.
# The phase's wall time is the span of its own telemetry: WorkspaceUsage
# carries no duration, and the domain's phase timings are Lane 1.
_RESOURCE_QUERY = """
SELECT
    execution_id,
    phase_id,
    EXTRACT(EPOCH FROM MAX(time) - MIN(time))::float8 AS wall_seconds,
    (ARRAY_AGG(data ORDER BY time DESC) FILTER (WHERE event_type = $3))[1] AS usage
FROM agent_events
WHERE execution_id = ANY($1::text[])
  AND phase_id IS NOT NULL
  AND time >= $2
GROUP BY execution_id, phase_id
"""


@dataclass(frozen=True)
class Percentiles:
    """Percentiles of one measure, with the sample count behind them.

    ``n`` counts the phases that HAD a value; each percentile is ``None``
    when ``n < MIN_SAMPLES``.
    """

    n: int
    p50: float | None
    p90: float | None
    p95: float | None

    @classmethod
    def of(cls, values: Iterable[float]) -> Percentiles:
        ordered = sorted(values)
        n = len(ordered)
        if n < MIN_SAMPLES:
            return cls(n=n, p50=None, p90=None, p95=None)
        return cls(
            n=n,
            p50=_interpolate(ordered, 0.50),
            p90=_interpolate(ordered, 0.90),
            p95=_interpolate(ordered, 0.95),
        )

    @property
    def sufficient(self) -> bool:
        return self.n >= MIN_SAMPLES


def _interpolate(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile (numpy's default, PostgreSQL's percentile_cont)."""
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class PhaseTokenProfile:
    """One (phase type, model): what a phase spent on that model.

    A sample is one execution's phase. ``unpriced_phases`` counts samples
    whose cost omits tokens no rate could price (#788): their cost is a floor.
    """

    phase_id: str
    model: str
    input_tokens: Percentiles
    output_tokens: Percentiles
    cache_creation_tokens: Percentiles
    cache_read_tokens: Percentiles
    cost_usd: Percentiles
    unpriced_phases: int


class _WorkspaceUsageRow(BaseModel):
    """The fields of a ``workspace_resource_usage`` observation read here."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    cpu_usage_seconds: float | None = None
    cpu_throttled_seconds: float | None = None
    memory_peak_bytes: int | None = None
    disk_bytes_at_teardown: int | None = None


@dataclass(frozen=True)
class ResourceCoverage:
    """How much of the window's phases the resource percentiles stand on.

    ``phases`` is every phase of this type seen in the window; the rest are
    subsets of it. A field counted under ``*_missing`` was absent or null in
    a usage row that does exist.
    """

    phases: int
    phases_without_usage_row: int
    cpu_usage_seconds_missing: int
    cpu_throttled_seconds_missing: int
    memory_peak_bytes_missing: int
    disk_bytes_at_teardown_missing: int
    wall_seconds_missing: int


@dataclass(frozen=True)
class PhaseResourceProfile:
    """One phase type's workspace resource use at teardown."""

    phase_id: str
    cpu_seconds_per_wall_second: Percentiles
    cpu_throttled_seconds: Percentiles
    memory_peak_bytes: Percentiles
    disk_bytes_at_teardown: Percentiles
    coverage: ResourceCoverage


@dataclass(frozen=True)
class PhaseProfiles:
    """Profiles for one workflow over ``[since, until)``."""

    workflow_id: str
    since: datetime
    until: datetime
    executions: int
    tokens: list[PhaseTokenProfile] = field(default_factory=list)
    resources: list[PhaseResourceProfile] = field(default_factory=list)


@dataclass
class _TokenSample:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost: Decimal = Decimal("0")
    unpriced_tokens: int = 0


class PhaseProfileQueryService:
    """Reads per-phase-type profiles for a workflow from Lane 2."""

    def __init__(self, pool: asyncpg.Pool, cost_calculator: PricingResolver) -> None:
        """Takes the resolver, not CostCalculator, for the VSA reason canonical_totals gives."""
        self._pool = pool
        self._cost_calculator = cost_calculator

    async def profiles(
        self,
        workflow_id: str,
        execution_ids: Iterable[str],
        window: timedelta,
        *,
        now: datetime | None = None,
    ) -> PhaseProfiles:
        """Profiles over every phase of ``execution_ids`` with telemetry in the window."""
        until = now or datetime.now(UTC)
        since = until - window
        ids = sorted({pg_safe(eid) for eid in execution_ids})
        if not ids:
            return PhaseProfiles(workflow_id=workflow_id, since=since, until=until, executions=0)
        async with self._pool.acquire() as conn:
            token_rows = await conn.fetch(_TOKEN_QUERY, ids, since)
            resource_rows = await conn.fetch(
                _RESOURCE_QUERY, ids, since, WORKSPACE_RESOURCE_USAGE
            )
        return PhaseProfiles(
            workflow_id=workflow_id,
            since=since,
            until=until,
            executions=len(ids),
            tokens=self._token_profiles(token_rows),
            resources=_resource_profiles(resource_rows),
        )

    def _token_profiles(self, rows: Iterable[asyncpg.Record]) -> list[PhaseTokenProfile]:
        samples: dict[tuple[str, str], dict[str, _TokenSample]] = defaultdict(
            lambda: defaultdict(_TokenSample)
        )
        for row in rows:
            model = recorded_model_from_row(row).pricing_model or UNKNOWN_MODEL
            sample = samples[(row["phase_id"], model)][row["execution_id"]]
            sample.input_tokens += int(row["input_tokens"])
            sample.output_tokens += int(row["output_tokens"])
            sample.cache_creation_tokens += int(row["cache_creation_tokens"])
            sample.cache_read_tokens += int(row["cache_read_tokens"])
            row_cost = price_canonical_row(row, self._cost_calculator)
            sample.cost += row_cost.cost
            sample.unpriced_tokens += row_cost.unpriced_tokens

        profiles = []
        for (phase_id, model), by_execution in sorted(samples.items()):
            values = list(by_execution.values())
            profiles.append(
                PhaseTokenProfile(
                    phase_id=phase_id,
                    model=model,
                    input_tokens=Percentiles.of(s.input_tokens for s in values),
                    output_tokens=Percentiles.of(s.output_tokens for s in values),
                    cache_creation_tokens=Percentiles.of(s.cache_creation_tokens for s in values),
                    cache_read_tokens=Percentiles.of(s.cache_read_tokens for s in values),
                    cost_usd=Percentiles.of(float(s.cost) for s in values),
                    unpriced_phases=sum(1 for s in values if s.unpriced_tokens),
                )
            )
        return profiles


def _parse_usage(raw: object) -> _WorkspaceUsageRow | None:
    """asyncpg hands JSONB back as text unless a codec is registered."""
    if raw is None:
        return None
    return _WorkspaceUsageRow.model_validate(json.loads(raw) if isinstance(raw, str) else raw)


def _resource_profiles(rows: Iterable[asyncpg.Record]) -> list[PhaseResourceProfile]:
    by_phase: dict[str, list[tuple[float | None, _WorkspaceUsageRow | None]]] = defaultdict(list)
    for row in rows:
        wall = row["wall_seconds"]
        by_phase[row["phase_id"]].append(
            (float(wall) if wall else None, _parse_usage(row["usage"]))
        )

    profiles = []
    for phase_id, phases in sorted(by_phase.items()):
        measured = [(wall, usage) for wall, usage in phases if usage is not None]
        cpu_rates = [
            usage.cpu_usage_seconds / wall
            for wall, usage in measured
            if wall is not None and usage.cpu_usage_seconds is not None
        ]
        profiles.append(
            PhaseResourceProfile(
                phase_id=phase_id,
                cpu_seconds_per_wall_second=Percentiles.of(cpu_rates),
                cpu_throttled_seconds=Percentiles.of(
                    u.cpu_throttled_seconds for _, u in measured if u.cpu_throttled_seconds is not None
                ),
                memory_peak_bytes=Percentiles.of(
                    u.memory_peak_bytes for _, u in measured if u.memory_peak_bytes is not None
                ),
                disk_bytes_at_teardown=Percentiles.of(
                    u.disk_bytes_at_teardown
                    for _, u in measured
                    if u.disk_bytes_at_teardown is not None
                ),
                coverage=ResourceCoverage(
                    phases=len(phases),
                    phases_without_usage_row=len(phases) - len(measured),
                    cpu_usage_seconds_missing=sum(
                        1 for _, u in measured if u.cpu_usage_seconds is None
                    ),
                    cpu_throttled_seconds_missing=sum(
                        1 for _, u in measured if u.cpu_throttled_seconds is None
                    ),
                    memory_peak_bytes_missing=sum(
                        1 for _, u in measured if u.memory_peak_bytes is None
                    ),
                    disk_bytes_at_teardown_missing=sum(
                        1 for _, u in measured if u.disk_bytes_at_teardown is None
                    ),
                    wall_seconds_missing=sum(1 for w, _ in measured if w is None),
                ),
            )
        )
    return profiles
