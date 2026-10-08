"""GET /metrics/phase-profiles reads real recorded usage, end to end (#1716).

Rows go into a real TimescaleDB ``agent_events`` the way production writes
them (COPY, so the usage-rollup trigger sees them), the workflow's executions
come from the real execution-list projection, and the numbers are read back
over HTTP from the real app. A value dropped at any hop between the rollup
and the response fails here.

The fixture is built so each expectation could only arise from the change:

* 12 in-window executions of the workflow, plus one ten days old whose plan
  phase spent a billion tokens and one of ANOTHER workflow. ``n == 12`` and a
  p90 in the thousands prove the window and the workflow both filter, over
  every row (12 > any page this API uses for lists of 10).
* ``build`` falls back from opus to haiku mid-phase and then writes the
  session summary production writes (AgentExecutionHandler), attributed to
  opus. Each model must carry only the tokens it consumed, and the summary's
  totals must be conserved across the two - not handed whole to opus.
* ``plan`` has a ``workspace_resource_usage`` row in 11 of 12 executions, one
  of them with no disk figure; ``build`` has none at all. A twelfth plan row
  lands an hour in the FUTURE and must be excluded by ``until``.
* ``soak`` started eight days ago and tore down inside the window, so only its
  usage row is in a 7-day window. Its CPU rate must be the same under a 7- and
  a 30-day look-back: the denominator is the recorded workspace lifetime.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg
    import httpx

pytestmark = pytest.mark.integration

WORKFLOW = "wf-profiles"
EXECUTIONS = 12
SONNET = "claude-sonnet-5"
OPUS = "claude-opus-5"
HAIKU = "claude-haiku-4-5-20251001"
MIB = 1 << 20

_COLUMNS = ("time", "event_type", "session_id", "execution_id", "phase_id", "data")
_Row = tuple[datetime, str, str, str, str, str]


def _plan_rows(
    execution: str, start: datetime, scale: int, *, usage: bool, disk: bool
) -> list[_Row]:
    session = f"{execution}-plan"
    rows: list[_Row] = [
        (start, "session_started", session, execution, "plan", "{}"),
        (
            start + timedelta(seconds=1),
            "token_usage",
            session,
            execution,
            "plan",
            json.dumps({"model": SONNET, "input_tokens": 1, "output_tokens": 1}),
        ),
        (
            start + timedelta(seconds=60),
            "session_summary",
            session,
            execution,
            "plan",
            json.dumps(
                {
                    "model": SONNET,
                    "total_input_tokens": 1000 * scale,
                    "total_output_tokens": 10 * scale,
                    "cache_creation_tokens": 5 * scale,
                    "cache_read_tokens": 100 * scale,
                    "total_cost_usd": 0.01 * scale,
                }
            ),
        ),
    ]
    if usage:
        data = {
            "cpu_usage_seconds": 6.0 * scale,
            "cpu_throttled_seconds": 0.5,
            "memory_peak_bytes": scale * MIB,
            "disk_bytes_at_teardown": 2 * scale * MIB if disk else None,
            "workspace_lifetime_seconds": 60.0,
        }
        rows.append(
            (
                start + timedelta(seconds=60),
                "workspace_resource_usage",
                session,
                execution,
                "plan",
                json.dumps(data),
            )
        )
    return rows


def _build_turn(
    model: str, scale: int, input_tokens: int, cache_creation: int, cache_read: int
) -> str:
    return json.dumps(
        {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": 5 * scale,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
        }
    )


def _build_rows(execution: str, start: datetime, scale: int) -> list[_Row]:
    session = f"{execution}-build"
    at = start + timedelta(minutes=5)
    # Turns divide each category differently, and the summary is exactly twice
    # them, so a share copied from the turns or split by overall tokens is off.
    # Output alone divides 1:1.
    return [
        (at, "session_started", session, execution, "build", "{}"),
        (
            at + timedelta(seconds=1),
            "token_usage",
            session,
            execution,
            "build",
            _build_turn(OPUS, scale, 50 * scale, 20 * scale, 300 * scale),
        ),
        (
            at + timedelta(seconds=2),
            "token_usage",
            session,
            execution,
            "build",
            _build_turn(HAIKU, scale, 200 * scale, 10 * scale, 100 * scale),
        ),
        (
            at + timedelta(seconds=3),
            "session_summary",
            session,
            execution,
            "build",
            json.dumps(
                {
                    "model": OPUS,
                    "total_input_tokens": 500 * scale,
                    "total_output_tokens": 20 * scale,
                    "cache_creation_tokens": 60 * scale,
                    "cache_read_tokens": 800 * scale,
                    "total_cost_usd": 0.1 * scale,
                }
            ),
        ),
    ]


def _soak_rows(execution: str, now: datetime, scale: int) -> list[_Row]:
    session = f"{execution}-soak"
    usage = {
        "cpu_usage_seconds": 60.0 * scale,
        "memory_peak_bytes": MIB,
        "workspace_lifetime_seconds": 600.0 * scale,
    }
    return [
        (now - timedelta(days=8), "session_started", session, execution, "soak", "{}"),
        (
            now - timedelta(minutes=scale),
            "workspace_resource_usage",
            session,
            execution,
            "soak",
            json.dumps(usage),
        ),
    ]


async def _seed(pool: asyncpg.Pool, now: datetime) -> None:
    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.orchestration.slices.list_executions.projection import (
        WorkflowExecutionListProjection,
    )

    listing = WorkflowExecutionListProjection(get_projection_store())
    rows: list[_Row] = []
    executions: list[tuple[str, str, datetime]] = []
    for i in range(EXECUTIONS):
        execution = f"exec-{i:02d}"
        start = now - timedelta(hours=i + 1)
        executions.append((execution, WORKFLOW, start))
        rows += _plan_rows(execution, start, i + 1, usage=i < 11, disk=i != 0)
        rows += _build_rows(execution, start, i + 1)
        rows += _soak_rows(execution, now, i + 1)
    future = {"cpu_usage_seconds": 1.0, "workspace_lifetime_seconds": 1.0}
    rows.append(
        (
            now + timedelta(hours=1),
            "workspace_resource_usage",
            "exec-11-plan",
            "exec-11",
            "plan",
            json.dumps(future),
        )
    )
    old = now - timedelta(days=10)
    executions.append(("exec-old", WORKFLOW, old))
    rows += _plan_rows("exec-old", old, 1_000_000, usage=True, disk=True)
    executions.append(("exec-other", "wf-other", now - timedelta(hours=1)))
    rows += _plan_rows("exec-other", now - timedelta(hours=1), 1_000_000, usage=True, disk=True)

    for execution, workflow, start in executions:
        await listing.on_workflow_execution_started(
            {
                "execution_id": execution,
                "workflow_id": workflow,
                "workflow_name": workflow,
                "started_at": start.isoformat(),
                "total_phases": 2,
                "inputs": {},
            }
        )
    async with pool.acquire() as conn:
        await conn.copy_records_to_table("agent_events", records=rows, columns=_COLUMNS)


@pytest.fixture
async def profiled_client(
    e2_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    import httpx

    from syn_adapters import projection_stores
    from syn_adapters.events import AgentEventStore, store_helpers
    from syn_adapters.projection_stores import PostgresProjectionStore
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_api.main import create_app

    store = AgentEventStore(e2_database)
    await store.initialize()
    pool = store.pool
    assert pool is not None
    monkeypatch.setattr(store_helpers, "_event_store", store)
    monkeypatch.setattr(projection_stores, "_store_instance", PostgresProjectionStore(pool))
    reset_projection_manager()
    await _seed(pool, datetime.now(UTC).replace(microsecond=0))
    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        reset_projection_manager()
        await store.close()


async def test_phase_profiles_are_read_from_recorded_usage(
    profiled_client: httpx.AsyncClient,
) -> None:
    response = await profiled_client.get(
        "/metrics/phase-profiles", params={"workflow_id": WORKFLOW}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_days"] == 7
    tokens = {(t["phase_id"], t["model"]): t for t in body["tokens"]}
    assert set(tokens) == {("plan", SONNET), ("build", OPUS), ("build", HAIKU)}

    plan = tokens[("plan", SONNET)]
    # 1000..12000: the old execution's billion and the other workflow are out.
    assert plan["input_tokens"]["n"] == 12
    assert plan["input_tokens"]["p50"] == pytest.approx(6500)
    assert plan["input_tokens"]["p90"] == pytest.approx(10900)
    # The summary supersedes the turn row, and cache reads are their own column.
    assert plan["cache_read_tokens"]["p50"] == pytest.approx(650)
    assert plan["cache_creation_tokens"]["p50"] == pytest.approx(32.5)
    assert plan["output_tokens"]["p90"] == pytest.approx(109)
    assert plan["cost_usd"]["p50"] == pytest.approx(0.065)
    assert plan["cost_usd"]["p90_display"] == "$0.11"

    # Mid-phase fallback, summary present: each model holds only what it
    # consumed, and every category of the summary is conserved across them.
    opus, haiku = tokens[("build", OPUS)], tokens[("build", HAIKU)]
    assert opus["input_tokens"]["n"] == haiku["input_tokens"]["n"] == 12
    # Per category, twice what each model's turns reported, at p50 (scale 6.5).
    assert opus["input_tokens"]["p50"] == pytest.approx(650)
    assert haiku["input_tokens"]["p50"] == pytest.approx(2600)
    assert opus["cache_creation_tokens"]["p50"] == pytest.approx(260)
    assert haiku["cache_creation_tokens"]["p50"] == pytest.approx(130)
    assert opus["cache_read_tokens"]["p50"] == pytest.approx(3900)
    assert haiku["cache_read_tokens"]["p50"] == pytest.approx(1300)
    assert opus["output_tokens"]["p50"] == pytest.approx(65)
    assert haiku["output_tokens"]["p50"] == pytest.approx(65)
    # The vendor's $0.10 * scale, divided by what each share costs at its own
    # model's rate (per million, per unit of scale): opus 100 in * $5 + 10 out
    # * $25 + 40 cache write * $6.25 + 600 cache read * $0.50 = 1300; haiku
    # 400 * $1 + 10 * $5 + 20 * $1.25 + 200 * $0.10 = 495.
    assert opus["cost_usd"]["p50"] == pytest.approx(0.65 * 1300 / 1795, rel=1e-3)
    assert haiku["cost_usd"]["p50"] == pytest.approx(0.65 * 495 / 1795, rel=1e-3)

    resources = {r["phase_id"]: r for r in body["resources"]}
    plan_res = resources["plan"]
    assert plan_res["coverage"]["phases"] == 12
    assert plan_res["coverage"]["phases_without_usage_row"] == 1
    assert plan_res["coverage"]["disk_bytes_at_teardown_missing"] == 1
    assert plan_res["coverage"]["coverage_display"] == "11/12 phases measured"
    # 6s of CPU per unit of scale over a 60s phase: 0.1 .. 1.1.
    assert plan_res["cpu_seconds_per_wall_second"]["n"] == 11
    assert plan_res["coverage"]["wall_seconds_missing"] == 0
    assert plan_res["cpu_seconds_per_wall_second"]["p50"] == pytest.approx(0.6)
    assert plan_res["memory_peak_bytes"]["p50"] == pytest.approx(6 * MIB)
    assert plan_res["memory_peak_bytes"]["p50_display"] == "6.0 MiB"
    assert plan_res["cpu_throttled_seconds"]["p95"] == pytest.approx(0.5)
    assert plan_res["disk_bytes_at_teardown"]["n"] == 10

    build_res = resources["build"]
    assert build_res["coverage"]["phases"] == 12
    assert build_res["coverage"]["phases_without_usage_row"] == 12
    assert build_res["memory_peak_bytes"]["n"] == 0
    assert build_res["memory_peak_bytes"]["p50"] is None
    assert build_res["memory_peak_bytes"]["p50_display"] == "insufficient"


async def test_a_completed_phase_rate_does_not_depend_on_the_look_back(
    profiled_client: httpx.AsyncClient,
) -> None:
    rates = []
    for days in (7, 30):
        response = await profiled_client.get(
            "/metrics/phase-profiles", params={"workflow_id": WORKFLOW, "window_days": days}
        )
        assert response.status_code == 200, response.text
        (soak,) = [r for r in response.json()["resources"] if r["phase_id"] == "soak"]
        assert soak["coverage"]["phases"] == 12
        assert soak["cpu_seconds_per_wall_second"]["n"] == 12
        rates.append(soak["cpu_seconds_per_wall_second"]["p50"])
    # 60s of CPU per 600s of workspace life, whatever the window cut off.
    assert rates == [pytest.approx(0.1), pytest.approx(0.1)]
