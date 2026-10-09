"""GET /evals reads every run of the page in a fixed number of batches (#1811).

The list used to build each eval's summary by loading the FULL execution detail
of every run, one run at a time: an event-store query, an aggregate replay, a
tool timeline per phase and a Lane 2 session cost per phase, plus the run's
execution cost. 88 evals with ~250 runs took 24.5 s on the VPS. The summary needs
none of the timeline, so it now reads the execution details, the session costs
and the execution costs once each, for every run on the page.

The Lane 2 double charges a simulated round trip per call and counts calls, so
a per-run read shows up both as calls that grow with the page and as time.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import asyncio
import time
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.eval_runs import EvalRunScore
from syn_domain.contexts.orchestration.domain.read_models.eval_summary import EvalRecord
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostsForIds,
)
from syn_shared.observed_model import UNKNOWN_MODEL_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

EVALS = 100
RUNS_PER_EVAL = 10
PHASES_PER_RUN = 2
OPUS = "claude-opus-5-5"
#: What one TimescaleDB round trip costs the API on a quiet VPS, roughly.
ROUND_TRIP_S = 0.002
BUDGET_MS = 500


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


class _Lane2:
    """TimescaleDB as the cost reads see it: a round trip per call, counted."""

    def __init__(self) -> None:
        self.calls = 0

    async def _round_trip(self) -> None:
        self.calls += 1
        await asyncio.sleep(ROUND_TRIP_S)

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        await self._round_trip()
        return SessionCost(session_id=session_id, agent_model=OPUS, requested_model="opus")

    async def get_session_costs(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        await self._round_trip()
        return {
            sid: SessionCost(session_id=sid, agent_model=OPUS, requested_model="opus")
            for sid in session_ids
        }

    def _cost(self, execution_id: str) -> ExecutionCost:
        return ExecutionCost(
            execution_id=execution_id,
            total_cost_usd=Decimal("1.25"),
            input_tokens=10,
            output_tokens=10,
        )

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        await self._round_trip()
        return self._cost(execution_id)

    async def list_costs_for_ids(self, execution_ids: list[str]) -> ExecutionCostsForIds:
        await self._round_trip()
        return ExecutionCostsForIds(costs=[self._cost(e) for e in execution_ids], tool_calls={})


@pytest.fixture
async def lane2(monkeypatch: pytest.MonkeyPatch) -> _Lane2:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    fake = _Lane2()
    manager = get_projection_mgr()
    for name in ("get_session_cost", "get_session_costs"):
        monkeypatch.setattr(manager.session_cost, name, getattr(fake, name), raising=False)
    for name in ("get_execution_cost", "list_costs_for_ids"):
        monkeypatch.setattr(manager.execution_cost, name, getattr(fake, name))
    return fake


@pytest.fixture
async def client(lane2: _Lane2) -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _seed() -> None:
    """100 evals of 10 completed, scored runs each, written straight into the read models."""
    from syn_api._wiring import get_projection_mgr

    store = get_projection_mgr().store
    for e in range(EVALS):
        eval_id = f"eval-{e:04d}"
        created = f"2026-10-01T00:{e // 60:02d}:{e % 60:02d}+00:00"
        record = EvalRecord(eval_id=eval_id, name=f"case {e}", goal="g", created_at=created)
        await store.save("evals", eval_id, record.model_dump(mode="json"))
        for r in range(RUNS_PER_EVAL):
            execution_id = f"exec-{e:04d}-{r:02d}"
            started = f"2026-10-02T{r:02d}:00:00+00:00"
            completed = f"2026-10-02T{r:02d}:05:00+00:00"
            summary = WorkflowExecutionSummary(
                workflow_execution_id=execution_id,
                workflow_id="wf-1",
                workflow_name="wf",
                status="completed",
                started_at=started,
                completed_at=completed,
                completed_phases=PHASES_PER_RUN,
                total_phases=PHASES_PER_RUN,
                total_tokens=0,
                eval_id=eval_id,
                association_kind="launched",
                workflow_version="1",
            )
            await store.save("workflow_executions", execution_id, summary.to_dict())
            detail = WorkflowExecutionDetail(
                workflow_execution_id=execution_id,
                workflow_id="wf-1",
                workflow_name="wf",
                status="completed",
                started_at=started,
                completed_at=completed,
                phases=tuple(
                    PhaseExecutionDetail(
                        workflow_phase_id=f"p{p}",
                        name=f"phase {p}",
                        status="completed",
                        session_id=f"sess-{execution_id}-{p}",
                        started_at=started,
                        completed_at=completed,
                    )
                    for p in range(PHASES_PER_RUN)
                ),
            )
            await store.save("workflow_execution_details", execution_id, detail.to_dict())
            score = EvalRunScore(
                eval_id=eval_id,
                execution_id=execution_id,
                verdict="PASS" if r % 2 else "FAIL",
                scorer="test",
                scorer_version="1",
                scored_at=completed,
            )
            await store.save(
                "eval_run_scores", f"{eval_id}/{execution_id}", score.model_dump(mode="json")
            )


async def test_a_page_of_100_evals_with_10_runs_each_answers_from_batched_reads(
    client: AsyncClient, lane2: _Lane2
) -> None:
    await _seed()
    await client.get("/evals", params={"page_size": 1})  # warm the app
    lane2.calls = 0

    started = time.perf_counter()
    response = await client.get("/evals", params={"page_size": EVALS})
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["evals"]) == EVALS
    first = body["evals"][0]
    assert first["run_count"] == RUNS_PER_EVAL
    assert first["scored_count"] == RUNS_PER_EVAL
    assert first["pass_rate"] == 0.5
    assert first["last_verdict"] == "PASS"  # run 09 is the newest, and odd
    assert [v["models"] for v in first["variants"]] == [[OPUS]]
    assert first["stats"]["median_cost_usd"] == "1.25"
    # One session-cost read and one execution-cost read for the whole page,
    # never one per run or per phase.
    assert lane2.calls <= 2, f"{lane2.calls} Lane 2 round trips for one page"
    print(f"\nGET /evals?page_size={EVALS} ({EVALS * RUNS_PER_EVAL} runs): {elapsed_ms:.0f} ms")
    assert elapsed_ms < BUDGET_MS, f"{elapsed_ms:.0f} ms for {EVALS} evals"


SONNET = "claude-sonnet-5"
CODEX = "gpt-6.1-codex"


class _VariedLane2(_Lane2):
    """Sessions that ran different models, a phase whose cost split names a delegate."""

    def _session(self, session_id: str) -> SessionCost | None:
        if session_id.endswith("-0"):
            return SessionCost(session_id=session_id, agent_model=CODEX, requested_model="codex")
        if session_id.endswith("-1"):
            return SessionCost(
                session_id=session_id,
                agent_model=SONNET,
                requested_model="sonnet",
                cost_by_model={SONNET: Decimal("0.5"), UNKNOWN_MODEL_KEY: Decimal("0.1")},
            )
        return None  # a session Lane 2 has no record of

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        await self._round_trip()
        return self._session(session_id)

    async def get_session_costs(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        await self._round_trip()
        return {sid: cost for sid in session_ids if (cost := self._session(sid)) is not None}

    def _cost(self, execution_id: str) -> ExecutionCost:
        return ExecutionCost(
            execution_id=execution_id,
            total_cost_usd=Decimal("2.5"),
            input_tokens=10,
            output_tokens=10,
            # Phase 0 (codex) delegated to opus; phase 1 has no split here.
            models_by_phase={"p0": {CODEX: Decimal("1"), OPUS: Decimal("1.5")}},
            unpriced_observation_count=1,
        )


async def test_an_eval_run_names_the_models_and_cost_its_execution_page_names(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    """The batched read derives what ``GET /executions/{id}`` derives, phase by phase."""
    from syn_api._wiring import get_projection_mgr

    fake = _VariedLane2()
    manager = get_projection_mgr()
    for name in ("get_session_cost", "get_session_costs"):
        monkeypatch.setattr(manager.session_cost, name, getattr(fake, name), raising=False)
    for name in ("get_execution_cost", "list_costs_for_ids"):
        monkeypatch.setattr(manager.execution_cost, name, getattr(fake, name))
    store = manager.store
    eval_id = "eval-varied"
    record = EvalRecord(eval_id=eval_id, name="varied", goal="g", created_at="2026-10-01T00:00:00Z")
    await store.save("evals", eval_id, record.model_dump(mode="json"))
    execution_id = "exec-varied"
    started, completed = "2026-10-02T00:00:00+00:00", "2026-10-02T00:05:00+00:00"
    summary = WorkflowExecutionSummary(
        workflow_execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="wf",
        status="completed",
        started_at=started,
        completed_at=completed,
        completed_phases=3,
        total_phases=3,
        total_tokens=0,
        eval_id=eval_id,
        association_kind="launched",
    )
    await store.save("workflow_executions", execution_id, summary.to_dict())
    phases = (
        PhaseExecutionDetail("p0", "a", "completed", session_id="s-0", started_at=started),
        PhaseExecutionDetail("p1", "b", "completed", session_id="s-1", completed_at=completed),
        PhaseExecutionDetail("p2", "c", "completed", session_id="s-2"),
        PhaseExecutionDetail("p3", "d", "completed"),  # no session at all
    )
    detail = WorkflowExecutionDetail(
        workflow_execution_id=execution_id,
        workflow_id="wf-1",
        workflow_name="wf",
        status="completed",
        started_at=started,
        completed_at=completed,
        phases=phases,
    )
    await store.save("workflow_execution_details", execution_id, detail.to_dict())

    from syn_api.routes.executions.models import ExecutionDetailResponse
    from syn_api.types import EvalRunListResponse

    page = ExecutionDetailResponse.model_validate(
        (await client.get(f"/executions/{execution_id}")).json()
    )
    runs = EvalRunListResponse.model_validate((await client.get(f"/evals/{eval_id}/runs")).json())

    expected = sorted(
        (p.phase_id, m)
        for p in page.phases
        for m in {k for k in p.cost_by_model if k != UNKNOWN_MODEL_KEY}
        | ({p.model} if p.model else set())
    )
    assert expected == sorted([("p0", CODEX), ("p0", OPUS), ("p1", SONNET)])
    (run,) = runs.items
    assert sorted((m.phase_id, m.model) for m in run.models) == expected
    assert run.total_cost_usd == page.total_cost_usd
    assert run.duration_seconds == page.total_duration_seconds
