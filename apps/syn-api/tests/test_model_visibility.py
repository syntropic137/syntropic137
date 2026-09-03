"""Which model ran must be visible where an operator looks (issue #1094).

A workflow meant to run opus for reasoning ran sonnet for a long time and
nobody noticed, because no surface named the model. Unlike a crash, a wrong
model never announces itself - it just produces plausible work at the wrong
quality and the wrong price.

The data was never missing. ``ExecutionCost.cost_by_model`` is already loaded
on the executions list request for the dollar figure, and the session
projection already records which harness launched each phase. Both were
dropped at the API carriers - ``_ExecutionEnrichment`` held a cost and no
models, ``PhaseExecution`` held a model and no harness - so nothing reached a
client.

These cases therefore drive the HTTP endpoints, not the carriers. Asserting on
``_ExecutionEnrichment`` would pass while ``_build_execution_summary_response``
quietly omitted the field, which is the precise shape of the bug (compare the
``error_message`` hop in #891).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import (
    UNATTRIBUTED_MODEL,
    ExecutionCost,
)

if TYPE_CHECKING:
    from syn_adapters.projections.manager import ProjectionManager
    from syn_api.routes.executions.models import (
        ExecutionSummaryResponse,
        PhaseExecutionInfo,
    )

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


@dataclass
class _StubExecutionCostProjection:
    """The TimescaleDB-backed leaf, replaced so the rest of the path is real.

    Only this leaf is stubbed: the endpoint, ``_load_execution_list_data``,
    ``_load_execution_enrichment``, ``_to_execution_summary`` and
    ``_build_execution_summary_response`` all execute as they do in
    production, which is where the field was being dropped.
    """

    costs_by_id: dict[str, ExecutionCost] = field(default_factory=dict)

    async def list_costs_for_ids(self, execution_ids: list[str]) -> dict[str, ExecutionCost]:
        return {eid: c for eid, c in self.costs_by_id.items() if eid in execution_ids}

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        return self.costs_by_id.get(execution_id)


@dataclass
class _StubSessionCostProjection:
    costs_by_id: dict[str, SessionCost] = field(default_factory=dict)

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        return self.costs_by_id.get(session_id)


async def _manager() -> ProjectionManager:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    return get_projection_mgr()


async def _seed_execution_row(exec_id: str, *, workflow_name: str = "sdlc-implement-v1") -> None:
    """Minimal row in the Lane 1 execution list projection."""
    manager = await _manager()
    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        exec_id,
        {
            "workflow_execution_id": exec_id,
            "workflow_id": "wf-1094",
            "workflow_name": workflow_name,
            "status": "completed",
            "started_at": "2026-09-03T10:00:00Z",
            "completed_at": "2026-09-03T10:15:00Z",
            "completed_phases": 4,
            "total_phases": 4,
            "total_tokens": 1000,
            "total_cost_usd": "0.05",
            "tool_call_count": 5,
            "error_message": None,
        },
    )


# --------------------------------------------------------------------------
# Ask 3: the executions LIST names what ran
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _MixedModelRun:
    """A run whose phases used different models - the shape #1094 is about."""

    execution_id: str = "exec-1094"
    opus: str = "claude-opus-4-5"
    sonnet: str = "claude-sonnet-4-5"

    def cost(self) -> ExecutionCost:
        return ExecutionCost(
            execution_id=self.execution_id,
            workflow_id="wf-1094",
            total_cost_usd=Decimal("4.08"),
            input_tokens=900,
            output_tokens=100,
            # Deliberately NOT alphabetical, and deliberately not the order the
            # phases ran in: the response must be sorted by the API, not by
            # whatever order the cost projection happened to build its dict.
            cost_by_model={self.sonnet: Decimal("0.96"), self.opus: Decimal("3.12")},
        )


async def _list_first_execution(mixed: _MixedModelRun) -> ExecutionSummaryResponse:
    """Drive the real ``GET /executions`` handler and return the single row."""
    from syn_api.routes.executions import queries as executions_queries

    await _seed_execution_row(mixed.execution_id)
    manager = await _manager()
    manager._projections["execution_cost"] = _StubExecutionCostProjection(
        {mixed.execution_id: mixed.cost()}
    )

    response = await executions_queries.list_executions_endpoint(status=None, page=1, page_size=50)
    assert len(response.executions) == 1
    return response.executions[0]


async def test_executions_list_names_every_model_that_ran() -> None:
    """The row an operator scans must say ``opus`` AND ``sonnet``.

    A single value would not have caught the original failure: the run was
    mixed by design, and reporting only one of the two models is how "we are
    on sonnet everywhere" stayed invisible.
    """
    mixed = _MixedModelRun()

    row = await _list_first_execution(mixed)

    assert row.models == [mixed.opus, mixed.sonnet]


async def test_executions_list_renders_the_models_server_side() -> None:
    """Rendering is the server's job so the dashboard and CLI agree (ADR-064)."""
    row = await _list_first_execution(_MixedModelRun())

    assert row.models_display == "Opus 4.5, Sonnet 4.5"


async def test_executions_list_keeps_cost_whose_model_is_unknown() -> None:
    """Unattributed spend stays in the list rather than being filtered out.

    Hiding the sentinel would let the row claim it knows every model that ran
    when it does not - the same "incomplete rendered as confident" failure
    ``unpriced_observation_count`` exists to prevent (#890).
    """
    mixed = _MixedModelRun()
    from syn_api.routes.executions import queries as executions_queries

    await _seed_execution_row(mixed.execution_id)
    cost = mixed.cost()
    cost.cost_by_model[UNATTRIBUTED_MODEL] = Decimal("0.10")
    manager = await _manager()
    manager._projections["execution_cost"] = _StubExecutionCostProjection(
        {mixed.execution_id: cost}
    )

    response = await executions_queries.list_executions_endpoint(status=None, page=1, page_size=50)

    assert UNATTRIBUTED_MODEL in response.executions[0].models


async def test_executions_list_row_without_cost_data_reports_no_models() -> None:
    """No Lane 2 record must render as "unknown", never as a fabricated model."""
    from syn_api.routes.executions import queries as executions_queries

    await _seed_execution_row("exec-no-cost")
    manager = await _manager()
    manager._projections["execution_cost"] = _StubExecutionCostProjection({})

    response = await executions_queries.list_executions_endpoint(status=None, page=1, page_size=50)

    assert response.executions[0].models == []
    assert response.executions[0].models_display is None


# --------------------------------------------------------------------------
# Ask 2: the execution detail names the harness per phase
# --------------------------------------------------------------------------


async def _seed_heterogeneous_execution(exec_id: str = "exec-hetero") -> None:
    """Two phases on two different harnesses - the run #1094 describes.

    ``implement`` on claude/opus, ``verify`` on codex. The harness is seeded
    ONLY on the session record and the model ONLY on the cost record, so a
    phase can report the right harness only by reading the session - not by
    pattern-matching a model id.
    """
    manager = await _manager()
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "workflow_execution_id": exec_id,
            "workflow_id": "wf-1094",
            "workflow_name": "sdlc-implement-v1",
            "status": "completed",
            "started_at": "2026-09-03T10:00:00Z",
            "completed_at": "2026-09-03T10:15:00Z",
            "total_input_tokens": 900,
            "total_output_tokens": 100,
            "total_cost_usd": "3.43",
            "total_duration_seconds": 900.0,
            "artifact_ids": [],
            "error_message": None,
            "phases": [
                {
                    "workflow_phase_id": "implement",
                    "name": "implement",
                    "status": "completed",
                    "session_id": "sess-implement",
                    "input_tokens": 800,
                    "output_tokens": 80,
                    "duration_seconds": 359.0,
                },
                {
                    "workflow_phase_id": "verify",
                    "name": "verify",
                    "status": "completed",
                    "session_id": "sess-verify",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "duration_seconds": 67.0,
                },
            ],
        },
    )
    for session_id, agent_type in (("sess-implement", "claude"), ("sess-verify", "codex")):
        await manager.store.save(
            "session_summaries",
            session_id,
            {
                "id": session_id,
                "workflow_id": "wf-1094",
                "agent_type": agent_type,
                "status": "completed",
            },
        )
    manager._projections["session_cost"] = _StubSessionCostProjection(
        {
            "sess-implement": SessionCost(
                session_id="sess-implement", agent_model="claude-opus-4-5"
            ),
            "sess-verify": SessionCost(session_id="sess-verify", agent_model="gpt-5.6-sol"),
        }
    )


async def _phases_of(exec_id: str = "exec-hetero") -> dict[str, PhaseExecutionInfo]:
    """Drive the real ``GET /executions/{id}`` handler, keyed by phase name."""
    from syn_api.routes.executions.queries import get_execution_endpoint

    await _seed_heterogeneous_execution(exec_id)
    response = await get_execution_endpoint(exec_id)
    return {p.name: p for p in response.phases}


async def test_each_phase_reports_the_harness_it_ran_on() -> None:
    """``codex`` on verify cannot be inferred from anything else in the response.

    It is not the execution's harness, not the leader model's vendor prefix,
    and not a default - the only source is the phase's own session record,
    which is exactly the hop that was missing.
    """
    phases = await _phases_of()

    assert phases["implement"].provider == "claude"
    assert phases["verify"].provider == "codex"


async def test_each_phase_reports_a_rendered_model_beside_the_harness() -> None:
    """``claude`` + ``Opus 4.5`` is the ``claude/opus`` label the issue asks for."""
    phases = await _phases_of()

    assert phases["implement"].model == "claude-opus-4-5"
    assert phases["implement"].model_display == "Opus 4.5"
    # A non-Anthropic id must round-trip unchanged rather than be mangled.
    assert phases["verify"].model_display == "gpt-5.6-sol"


async def test_a_phase_with_no_session_reports_no_harness() -> None:
    """A pending phase has nothing to read; it must say so, not guess."""
    from syn_api.routes.executions.queries import get_execution_endpoint

    manager = await _manager()
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        "exec-pending",
        {
            "workflow_execution_id": "exec-pending",
            "workflow_id": "wf-1094",
            "workflow_name": "sdlc-implement-v1",
            "status": "running",
            "phases": [
                {
                    "workflow_phase_id": "open_pr",
                    "name": "open_pr",
                    "status": "pending",
                    "session_id": None,
                }
            ],
        },
    )

    response = await get_execution_endpoint("exec-pending")

    assert response.phases[0].provider is None
