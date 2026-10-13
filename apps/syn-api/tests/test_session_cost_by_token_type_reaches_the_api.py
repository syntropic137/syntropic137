"""A session's cost by token type reaches GET /sessions/{id}.

The session detail meter splits cost into input, output, cache write and cache
read. The split is computed on the read model (``SessionCost``); these walk
it through every hop to the response - ``_load_cost_data`` -> ``_CostData`` ->
``SessionDetail`` -> ``SessionResponse`` - because a field dropped at any one
of them arrives as its default, which for this field is ``None`` and reads as
"could not be split" rather than as a bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.types import Ok, SessionDetail, TokenTypeCostResponse
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary as DomainSessionSummary,
)
from syn_shared.pricing import CostSplitBasis, TokenTypeCost

pytestmark = pytest.mark.unit

SPLIT = TokenTypeCost(
    input_usd=Decimal("0.01"),
    output_usd=Decimal("0.2"),
    cache_creation_usd=Decimal("0.03"),
    cache_read_usd=Decimal("0.06"),
)


@dataclass
class _StubSessionCostQuery:
    cost: SessionCost | None

    async def get(self, session_id: str) -> SessionCost | None:
        return self.cost


def _lane1_row() -> DomainSessionSummary:
    return DomainSessionSummary(
        id="sess-1",
        workflow_id="wf-1",
        agent_type="claude",
        status="completed",
        started_at=None,
        completed_at=None,
        total_tokens=0,
    )


async def _cost_data(cost: SessionCost, monkeypatch: pytest.MonkeyPatch):
    from syn_api.routes import sessions

    monkeypatch.setattr(sessions, "get_session_cost_query", lambda: _StubSessionCostQuery(cost))
    return await sessions._load_cost_data(_lane1_row())  # pyright: ignore[reportPrivateUsage]


async def test_the_split_and_its_basis_leave_the_read_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = SessionCost(
        session_id="sess-1",
        total_cost_usd=Decimal("0.3"),
        cost_by_token_type=SPLIT,
        cost_by_token_type_basis=CostSplitBasis.RATE_TABLE,
    )

    data = await _cost_data(cost, monkeypatch)

    assert data.cost_by_token_type == TokenTypeCostResponse(
        input_usd=Decimal("0.01"),
        output_usd=Decimal("0.2"),
        cache_creation_usd=Decimal("0.03"),
        cache_read_usd=Decimal("0.06"),
        basis=CostSplitBasis.RATE_TABLE,
    )


async def test_no_split_stays_null_not_zeroes(monkeypatch: pytest.MonkeyPatch) -> None:
    data = await _cost_data(SessionCost(session_id="sess-1"), monkeypatch)

    assert data.cost_by_token_type is None


async def test_the_endpoint_returns_the_split() -> None:
    from syn_api.routes.sessions import get_session_endpoint

    split = TokenTypeCostResponse.from_split(SPLIT, CostSplitBasis.ALLOCATED)
    detail = SessionDetail(id="sess-1", status="completed", cost_by_token_type=split)
    with (
        patch("syn_api.routes.sessions.get_projection_mgr", return_value=MagicMock()),
        patch("syn_api.prefix_resolver.resolve_or_raise", new=AsyncMock(return_value="sess-1")),
        patch("syn_api.routes.sessions.get_session", new=AsyncMock(return_value=Ok(detail))),
    ):
        resp = await get_session_endpoint("sess-1")

    assert resp.cost_by_token_type == split
    assert resp.model_dump(mode="json")["cost_by_token_type"]["basis"] == "allocated"
