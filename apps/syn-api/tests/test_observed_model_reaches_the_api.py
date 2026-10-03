"""Every run-time API surface names the model that RAN, never the alias (ADR-067 D9).

A workflow definition says ``opus``; the harness reports ``claude-opus-5-5``.
Only the second proves anything, so it is the only one served as ``model`` /
``agent_model``. The alias travels as ``requested_model`` and shows up in the
display string only as context: ``unknown (requested: opus)``.

Two eras of stored data reach these routes:

- rows written under the contract, whose model is the reported id;
- LEGACY rows, whose ``model`` was the requested alias. They must read back as
  "not reported, requested opus" and their cost as ``unattributed-model`` - and
  must not 500 on the alias-rejecting response types.

Each case goes through the real loader and mapper, with only the Lane 2 query
seam stubbed, so a hop that drops or mislabels the field fails here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from syn_api.routes.executions.phase_mapping import _map_phase_detail, _map_phase_to_response
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary as DomainSessionSummary,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
    PhaseDefinitionDetail,
    WorkflowDetail,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    PhaseExecutionDetail,
)
from syn_shared.observed_model import UNKNOWN_MODEL_KEY

os.environ.setdefault("APP_ENVIRONMENT", "test")

pytestmark = pytest.mark.unit

_SESSION_ID = "sess-d9"
_PHASE_ID = "implement"


def _legacy_cost() -> SessionCost:
    """A cost record as a pre-ADR-067 writer left it: the ALIAS as the model."""
    return SessionCost(
        session_id=_SESSION_ID,
        agent_model="opus",
        cost_by_model={"opus": Decimal("1.25")},
    )


def _classified_legacy_cost() -> SessionCost:
    """The same legacy rows as the post-ADR-067 read path classifies them."""
    return SessionCost(
        session_id=_SESSION_ID,
        agent_model=None,
        requested_model="opus",
        cost_by_model={UNKNOWN_MODEL_KEY: Decimal("1.25")},
    )


def _observed_cost(observed: str, requested: str) -> SessionCost:
    return SessionCost(
        session_id=_SESSION_ID,
        agent_model=observed,
        requested_model=requested,
        cost_by_model={observed: Decimal("2.5")},
    )


# ---------------------------------------------------------------------------
# Execution phases
# ---------------------------------------------------------------------------


@dataclass
class _SessionCostProjection:
    cost: SessionCost | None

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        return self.cost


@dataclass
class _SessionTools:
    async def get(self, session_id: str) -> list[object]:
        return []


@dataclass
class _WorkflowDetails:
    workflow: WorkflowDetail | None

    async def get_by_id(self, workflow_id: str) -> WorkflowDetail | None:
        return self.workflow


@dataclass
class _Manager:
    session_cost: _SessionCostProjection
    session_tools: _SessionTools = field(default_factory=_SessionTools)
    workflow_detail: _WorkflowDetails = field(default_factory=lambda: _WorkflowDetails(None))


def _phase(session_id: str | None = _SESSION_ID) -> PhaseExecutionDetail:
    return PhaseExecutionDetail(
        workflow_phase_id=_PHASE_ID,
        name="Implement",
        status="completed",
        session_id=session_id,
    )


async def _phase_response(cost: SessionCost | None, session_id: str | None = _SESSION_ID):
    manager = _Manager(session_cost=_SessionCostProjection(cost))
    mapped = await _map_phase_detail(_phase(session_id), manager, {})  # type: ignore[arg-type]
    return _map_phase_to_response(mapped)


@pytest.mark.parametrize(
    "cost", [_legacy_cost(), _classified_legacy_cost()], ids=["stored", "classified"]
)
async def test_a_legacy_phase_reports_unknown_with_the_alias_as_the_request(
    cost: SessionCost,
) -> None:
    response = await _phase_response(cost)

    assert response.model is None
    assert response.requested_model == "opus"
    assert response.model_display == "unknown (requested: opus)"
    assert response.cost_by_model == {UNKNOWN_MODEL_KEY: "1.25"}
    wire = response.model_dump(mode="json")
    assert wire["model_display"] == "unknown (requested: opus)"


@pytest.mark.parametrize(
    ("observed", "requested"),
    [("claude-opus-5-5", "opus"), ("gpt-6-sol", "gpt-sol")],
)
async def test_a_new_phase_reports_the_model_that_ran(observed: str, requested: str) -> None:
    response = await _phase_response(_observed_cost(observed, requested))

    assert response.model == observed
    assert response.requested_model == requested
    assert response.model_display == observed
    assert response.cost_by_model == {observed: "2.5"}


async def test_a_phase_with_no_usage_row_falls_back_to_the_configured_request() -> None:
    """Pending or pre-first-turn: nothing ran yet, but the request is known."""
    manager = _Manager(session_cost=_SessionCostProjection(None))
    mapped = await _map_phase_detail(
        _phase(session_id=None),
        manager,  # type: ignore[arg-type]
        {},
        {_PHASE_ID: "gpt-sol"},
    )

    response = _map_phase_to_response(mapped)

    assert response.model is None
    assert response.requested_model == "gpt-sol"
    assert response.model_display == "unknown (requested: gpt-sol)"


async def test_the_configured_model_never_overrides_a_recorded_request() -> None:
    manager = _Manager(session_cost=_SessionCostProjection(_classified_legacy_cost()))
    mapped = await _map_phase_detail(
        _phase(),
        manager,  # type: ignore[arg-type]
        {},
        {_PHASE_ID: "sonnet"},
    )

    assert mapped.requested_model == "opus"


async def test_configured_models_are_read_from_the_workflow_definition() -> None:
    from syn_api.routes.executions.phase_mapping import load_configured_models

    workflow = WorkflowDetail(
        id="wf-d9",
        name="D9",
        workflow_type="custom",
        classification="standard",
        description=None,
        phases=[PhaseDefinitionDetail(id=_PHASE_ID, name="Implement", model="opus")],
    )
    manager = _Manager(
        session_cost=_SessionCostProjection(None), workflow_detail=_WorkflowDetails(workflow)
    )

    assert await load_configured_models(manager, "wf-d9") == {_PHASE_ID: "opus"}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@dataclass
class _StubSessionCostQuery:
    cost: SessionCost | None

    async def get(self, session_id: str) -> SessionCost | None:
        return self.cost

    async def get_many(self, session_ids: list[str]) -> dict[str, SessionCost]:
        return {sid: self.cost for sid in session_ids if self.cost is not None}


def _lane1_row() -> DomainSessionSummary:
    return DomainSessionSummary(
        id=_SESSION_ID,
        workflow_id="wf-d9",
        agent_type="claude",
        status="completed",
        started_at=None,
        completed_at=None,
        total_tokens=0,
    )


@pytest.mark.parametrize(
    "cost", [_legacy_cost(), _classified_legacy_cost()], ids=["stored", "classified"]
)
async def test_a_legacy_session_reports_unknown_with_the_alias_as_the_request(
    cost: SessionCost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from syn_api.routes import sessions
    from syn_api.types import SessionDetail

    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: _StubSessionCostQuery(cost))
    data = await sessions._load_cost_data(_lane1_row())  # pyright: ignore[reportPrivateUsage]

    detail = SessionDetail(
        id=_SESSION_ID,
        agent_model=data.agent_model,
        requested_model=data.requested_model,
        cost_by_model=data.cost_by_model,
    )

    assert detail.agent_model is None
    assert detail.requested_model == "opus"
    assert detail.agent_model_display == "unknown (requested: opus)"
    assert detail.cost_by_model == {UNKNOWN_MODEL_KEY: Decimal("1.25")}


@pytest.mark.parametrize(
    ("observed", "requested"),
    [("claude-opus-5-5", "opus"), ("gpt-6-sol", "gpt-sol")],
)
async def test_a_new_session_summary_reports_the_model_that_ran(
    observed: str, requested: str
) -> None:
    from syn_api.routes.sessions import _build_session_summary_response, _enrichment_from_cost
    from syn_api.types import SessionSummary

    summary = SessionSummary(id=_SESSION_ID, status="completed", agent_type="claude")
    response = _build_session_summary_response(
        summary, None, _enrichment_from_cost(_observed_cost(observed, requested))
    )

    assert response.agent_model == observed
    assert response.requested_model == requested
    assert response.agent_model_display == observed
    assert response.model_dump(mode="json")["agent_model_display"] == observed


async def test_a_legacy_session_summary_does_not_500_on_the_alias() -> None:
    from syn_api.routes.sessions import _build_session_summary_response, _enrichment_from_cost
    from syn_api.types import SessionSummary

    summary = SessionSummary(id=_SESSION_ID, status="completed", agent_type="claude")
    response = _build_session_summary_response(summary, None, _enrichment_from_cost(_legacy_cost()))

    assert response.agent_model is None
    assert response.requested_model == "opus"
    assert response.agent_model_display == "unknown (requested: opus)"


# ---------------------------------------------------------------------------
# Conversation metadata
# ---------------------------------------------------------------------------


@dataclass
class _ConversationStore:
    meta: dict[str, str | None]

    async def get_session_metadata(self, session_id: str) -> dict[str, str | None]:
        return self.meta


@pytest.mark.parametrize(
    ("meta", "model", "requested", "display"),
    [
        ({"model": "opus"}, None, "opus", "unknown (requested: opus)"),
        ({"model": None, "requested_model": "opus"}, None, "opus", "unknown (requested: opus)"),
        (
            {"model": "claude-opus-5-5", "requested_model": "opus"},
            "claude-opus-5-5",
            "opus",
            "claude-opus-5-5",
        ),
        ({"model": "gpt-6-sol", "requested_model": "gpt-sol"}, "gpt-6-sol", "gpt-sol", "gpt-6-sol"),
    ],
    ids=["legacy-unclassified", "legacy-classified", "claude", "codex"],
)
async def test_conversation_metadata_names_the_model_that_ran(
    meta: dict[str, str | None],
    model: str | None,
    requested: str,
    display: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes import conversations
    from syn_api.types import Ok

    async def _store() -> _ConversationStore:
        return _ConversationStore(meta)

    monkeypatch.setattr(conversations, "get_conversation_store", _store)

    result = await conversations.get_conversation_metadata(_SESSION_ID)

    assert isinstance(result, Ok)
    assert result.value is not None
    assert result.value.model == model
    assert result.value.requested_model == requested
    assert result.value.model_display == display


# ---------------------------------------------------------------------------
# Cost maps
# ---------------------------------------------------------------------------


def test_a_legacy_alias_cost_key_is_folded_into_the_unknown_bucket() -> None:
    from syn_api.routes.costs import _session_cost_to_api, session_cost_to_data

    cost = _legacy_cost()
    cost.cost_by_model = {
        "opus": Decimal("1.25"),
        UNKNOWN_MODEL_KEY: Decimal("0.75"),
        "claude-opus-5-5": Decimal("3"),
    }

    response = _session_cost_to_api(session_cost_to_data(cost))

    assert response.cost_by_model == {UNKNOWN_MODEL_KEY: "2.00", "claude-opus-5-5": "3"}
