"""Tests for syn_api.routes.sessions — start, list, complete cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from syn_api.types import Ok
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run none of them (#1065).
pytestmark = pytest.mark.unit


# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
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


async def test_list_sessions_empty():
    """List sessions when none exist."""
    from syn_api.routes.sessions import list_sessions

    result = await list_sessions()

    assert isinstance(result, Ok)
    assert result.value == []


async def test_start_session():
    """Start a new session."""
    from syn_api.routes.sessions import start_session

    result = await start_session(
        workflow_id="wf-test-123",
        phase_id="phase-1",
        agent_type="claude",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_start_and_list_sessions():
    """Start a session and verify list returns Ok.

    Note: In test mode, session events go to the SDK event store via
    repository.save() but aren't dispatched to projections (no subscription
    service running). The list query returns Ok but may not contain the
    session. Full round-trip is verified in integration tests.
    """
    from syn_api.routes.sessions import list_sessions, start_session

    start_result = await start_session(
        workflow_id="wf-test-456",
        phase_id="phase-1",
        agent_type="mock",
    )
    assert isinstance(start_result, Ok)

    # Verify list_sessions returns successfully
    list_result = await list_sessions()
    assert isinstance(list_result, Ok)


async def test_complete_session():
    """Start then complete a session."""
    from syn_api.routes.sessions import complete_session, start_session

    start_result = await start_session(
        workflow_id="wf-test-789",
        phase_id="phase-1",
    )
    assert isinstance(start_result, Ok)
    session_id = start_result.value

    # CompleteSessionHandler is currently a stub (pass), so this should not error
    complete_result = await complete_session(session_id)
    assert isinstance(complete_result, Ok)


async def test_get_session_includes_lineage_fields():
    """get_session() must surface parent_session_id/root_session_id (#895).

    Regression test: SessionDetail gained these fields for #895, but the
    SessionDetail(...) construction in get_session() was never updated to
    pass them through, so the field existed and was always None at this
    endpoint despite being correctly populated in list_sessions().
    """
    from syn_api._wiring import get_session_repo, sync_published_events_to_projections
    from syn_api.routes.sessions import get_session
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
        StartSessionCommand,
    )

    repo = get_session_repo()
    session_id = "lineage-test-0001"

    agg = AgentSessionAggregate()
    agg.start_session(
        StartSessionCommand(
            aggregate_id=session_id,
            workflow_id="wf-lineage",
            execution_id="exec-lineage",
            phase_id="phase-1",
            agent_provider="claude",
        )
    )
    await repo.save(agg)
    await sync_published_events_to_projections()

    result = await get_session(session_id)

    assert isinstance(result, Ok)
    # A leader session (no parent) has root_session_id == its own id.
    assert result.value.parent_session_id is None
    assert result.value.root_session_id == session_id


# -- Regression tests for #1077 (sessions list N+1) ---------------------------


@dataclass
class _CountingSessionCostQuery:
    """Stands in for ``SessionCostQueryService`` at the ``_load_session_costs`` seam.

    ``get`` raises, so any code path that still asks per session - the
    pre-#1077 behaviour - fails loudly instead of quietly working via the slow
    path and leaving the endpoint just as slow as before.

    ``list_for_ids`` records every call it receives, which is what lets a test
    assert "once, whatever the page size" without timing anything. A wall-clock
    threshold cannot tell a batched query from twenty fast ones on an idle
    machine, which is exactly the machine CI runs on.
    """

    costs_by_id: dict[str, SessionCost]
    list_calls: list[list[str]] = field(default_factory=list)

    async def get(self, session_id: str) -> SessionCost | None:
        raise AssertionError(
            f"get({session_id!r}) was called - the list path must use the "
            "batched list_for_ids instead of a per-session loop (issue #1077)"
        )

    async def list_for_ids(self, session_ids: list[str]) -> dict[str, SessionCost]:
        self.list_calls.append(list(session_ids))
        return {sid: c for sid, c in self.costs_by_id.items() if sid in session_ids}


def _session_cost(session_id: str, cost: str, model: str) -> SessionCost:
    """A priced session whose numbers are distinct per id.

    Distinct values are the point: they make a mis-keyed batch - session A's
    cost attributed to session B - fail the assertion, which a shared fixture
    value would hide.
    """
    sc = SessionCost(session_id=session_id)
    sc.total_cost_usd = Decimal(cost)
    sc.agent_model = model
    sc.input_tokens = 11
    sc.output_tokens = 22
    return sc


def _patch_cost_query(monkeypatch: pytest.MonkeyPatch, stub: _CountingSessionCostQuery) -> None:
    from syn_api.routes import sessions

    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: stub)


@pytest.mark.parametrize("session_count", [1, 5, 20])
async def test_load_session_costs_issues_one_batched_lookup(
    monkeypatch: pytest.MonkeyPatch, session_count: int
) -> None:
    """Regression for #1077: enrichment is ONE lookup covering every id.

    Parametrised over page sizes because the defect is a loop: a loop and a
    batch are indistinguishable at a page size of one, and only the shape
    "call count stays at 1 while the id count grows" rules the loop out.
    """
    from syn_api.routes.sessions import _load_session_costs

    ids = [f"sess-{i}" for i in range(session_count)]
    stub = _CountingSessionCostQuery(
        costs_by_id={
            sid: _session_cost(sid, f"{i + 1}.25", "claude-sonnet-4-20250514")
            for i, sid in enumerate(ids)
        }
    )
    _patch_cost_query(monkeypatch, stub)

    enrichment = await _load_session_costs(ids)

    assert len(stub.list_calls) == 1, (
        f"expected exactly one batched lookup for {session_count} session ids, "
        f"got {len(stub.list_calls)}: {stub.list_calls}"
    )
    assert stub.list_calls[0] == ids
    assert len(enrichment) == session_count


async def test_load_session_costs_keeps_each_cost_with_its_own_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batching must not scramble which cost belongs to which session.

    The per-session loop could not get this wrong - it held one id at a time.
    A batch can, so the mapping is pinned with values that differ per session
    and ids deliberately not in sorted order.
    """
    from syn_api.routes.sessions import _load_session_costs

    stub = _CountingSessionCostQuery(
        costs_by_id={
            "sess-b": _session_cost("sess-b", "2.00", "claude-opus-4-20250514"),
            "sess-a": _session_cost("sess-a", "1.00", "claude-sonnet-4-20250514"),
            "sess-c": _session_cost("sess-c", "3.00", "claude-haiku-4-20250514"),
        }
    )
    _patch_cost_query(monkeypatch, stub)

    enrichment = await _load_session_costs(["sess-c", "sess-a", "sess-b"])

    assert enrichment["sess-a"].total_cost_usd == Decimal("1.00")
    assert enrichment["sess-b"].total_cost_usd == Decimal("2.00")
    assert enrichment["sess-c"].total_cost_usd == Decimal("3.00")
    assert enrichment["sess-a"].agent_model == "claude-sonnet-4-20250514"
    assert enrichment["sess-b"].agent_model == "claude-opus-4-20250514"
    assert enrichment["sess-c"].agent_model == "claude-haiku-4-20250514"


async def test_load_session_costs_enriches_only_sessions_with_cost_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session the query service knows nothing about stays unenriched.

    The loop achieved this by skipping ``None`` returns. The batch achieves it
    by absence from the result map; the observable behaviour must be the same,
    or a session with no observations would start reporting $0.00 as if priced.
    """
    from syn_api.routes.sessions import _load_session_costs

    stub = _CountingSessionCostQuery(
        costs_by_id={"sess-known": _session_cost("sess-known", "4.00", "claude-sonnet-4-20250514")}
    )
    _patch_cost_query(monkeypatch, stub)

    enrichment = await _load_session_costs(["sess-known", "sess-unknown"])

    assert set(enrichment) == {"sess-known"}
