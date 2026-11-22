"""GET /triggers/{id}/history reports what each firing's execution cost (#897 slice J).

The projection's ``cost_usd`` was never written, so every firing read ``null``
and the dashboard formatted nothing. The cost is now the execution's own Lane 2
cost, read for the whole page in one batch, with a ``cost_display`` that says
when the figure is unpriced or only partial.

Lane 2 is replaced by a double that counts its calls, and the projection by a
handler double, so the assertions are on the HTTP response the dashboard reads.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api.types import (
    Ok,
    TriggerHistoryEntryResponse,
    TriggerHistoryListResponse,
    TriggerHistoryResponse,
    TriggerSummary,
)
from syn_domain.contexts.github.domain.read_models.trigger_history_entry import (
    TriggerHistoryEntry,
)
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
    ExecutionCostsForIds,
)
from syn_shared.agents import ModelId
from syn_shared.display.formatters import EM_DASH, UNPRICED, format_cost

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    import asyncpg

    from syn_domain.contexts.github import GetTriggerHistoryQuery

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

TRIGGER = "trig-897"
FIRED = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


def _firing(execution_id: str, status: str = "dispatched") -> TriggerHistoryEntry:
    # A stored cost the read must ignore: it could only come from the projection.
    return TriggerHistoryEntry(
        trigger_id=TRIGGER,
        execution_id=execution_id,
        github_event_type="check_run.completed",
        fired_at=FIRED,
        status=status,
        cost_usd=99.0,
    )


def _cost(execution_id: str, usd: str, unpriced: int = 0) -> ExecutionCost:
    return ExecutionCost(
        execution_id=execution_id,
        total_cost_usd=Decimal(usd),
        input_tokens=10,
        output_tokens=10,
        unpriced_observation_count=unpriced,
    )


@dataclass
class _ExecutionCosts:
    """Lane 2's batched cost reader, counted."""

    costs: list[ExecutionCost] = field(default_factory=list)
    fail: bool = False
    calls: list[list[str]] = field(default_factory=list)

    async def list_costs_for_ids(self, execution_ids: list[str]) -> ExecutionCostsForIds:
        self.calls.append(list(execution_ids))
        if self.fail:
            raise RuntimeError("timescale unavailable")
        wanted = set(execution_ids)
        return ExecutionCostsForIds(
            costs=[c for c in self.costs if c.execution_id in wanted], tool_calls={}
        )


@dataclass
class _Manager:
    execution_cost: _ExecutionCosts


@dataclass
class _History:
    entries: list[TriggerHistoryEntry]

    async def handle(self, query: GetTriggerHistoryQuery) -> list[TriggerHistoryEntry]:
        return self.entries[: query.limit]


@pytest.fixture
def lane2(monkeypatch: pytest.MonkeyPatch) -> _ExecutionCosts:
    from syn_api.routes.triggers import queries

    fake = _ExecutionCosts()
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: _Manager(fake))

    async def _same_id(trigger_id: str) -> str:
        return trigger_id

    monkeypatch.setattr(queries, "_resolve_trigger_id", _same_id)
    return fake


@pytest.fixture
def history(monkeypatch: pytest.MonkeyPatch) -> _History:
    import syn_domain.contexts.github as github

    fake = _History(entries=[])
    monkeypatch.setattr(github, "get_trigger_history_handler", lambda: fake)
    return fake


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _entries(client: AsyncClient) -> dict[str, TriggerHistoryEntryResponse]:
    response = await client.get(f"/triggers/{TRIGGER}/history")
    assert response.status_code == 200, response.text
    body = TriggerHistoryResponse.model_validate(response.json())
    return {e.execution_id: e for e in body.entries}


async def test_priced_firing_reports_its_execution_cost(
    client: AsyncClient, lane2: _ExecutionCosts, history: _History
) -> None:
    history.entries = [_firing("exec-a")]
    lane2.costs = [_cost("exec-a", "1.25")]

    entry = (await _entries(client))["exec-a"]

    assert entry.cost_usd == 1.25
    assert entry.cost_display == "$1.25"
    assert entry.unpriced_observation_count == 0


async def test_partially_unpriced_firing_says_the_cost_is_a_lower_bound(
    client: AsyncClient, lane2: _ExecutionCosts, history: _History
) -> None:
    history.entries = [_firing("exec-partial"), _firing("exec-unpriced")]
    lane2.costs = [_cost("exec-partial", "0.40", unpriced=3), _cost("exec-unpriced", "0", 2)]

    entries = await _entries(client)

    assert entries["exec-partial"].cost_display == ">=$0.40 (partial)"
    assert entries["exec-partial"].unpriced_observation_count == 3
    assert entries["exec-unpriced"].cost_display == UNPRICED
    assert entries["exec-unpriced"].unpriced_observation_count == 2


async def test_blocked_firing_and_unknown_execution_have_no_cost(
    client: AsyncClient, lane2: _ExecutionCosts, history: _History
) -> None:
    # The projection records a blocked firing with execution_id "" (no execution).
    history.entries = [_firing("", status="blocked"), _firing("exec-no-cost-yet")]

    entries = await _entries(client)

    for entry in entries.values():
        assert entry.cost_usd is None
        assert entry.cost_display == EM_DASH
        assert entry.unpriced_observation_count == 0
    assert lane2.calls == [["exec-no-cost-yet"]]


async def test_cost_read_failure_returns_history_without_cost(
    client: AsyncClient, lane2: _ExecutionCosts, history: _History
) -> None:
    history.entries = [_firing("exec-a")]
    lane2.costs = [_cost("exec-a", "1.25")]
    lane2.fail = True

    entry = (await _entries(client))["exec-a"]

    assert entry.cost_usd is None
    assert entry.cost_display == EM_DASH


async def test_whole_page_is_priced_in_one_batched_read(
    client: AsyncClient, lane2: _ExecutionCosts, history: _History
) -> None:
    ids = [f"exec-{n}" for n in range(25)]
    history.entries = [_firing(e) for e in ids]
    lane2.costs = [_cost(e, "0.50") for e in ids]

    entries = await _entries(client)

    assert len(lane2.calls) == 1
    assert sorted(lane2.calls[0]) == sorted(ids)
    assert {e.cost_display for e in entries.values()} == {"$0.50"}


# --- Cost shapes the real converter produces ---------------------------------

_MILLION = 1_000_000
_OPUS = ModelId.CLAUDE_OPUS_5_5.value

#: A column value the grouped cost SQL can return.
_Cell = int | str | list[str] | Decimal | None


class _Row:
    """An asyncpg Record as the grouped cost SQL returns one."""

    def __init__(self, data: Mapping[str, _Cell]) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)


def _row(execution_id: str, model: str, **cells: _Cell) -> asyncpg.Record:
    """One grouped row with no input or output tokens: cache-only, or summary-only."""
    data: dict[str, _Cell] = {
        "model": model,
        "agent_model": model,
        "total_input": 0,
        "total_output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "session_ids": ["session-1"],
        "session_id": "session-1",
        "observation_count": 1,
        "num_turns": 1,
        "total_turns": 1,
        "duration_ms_val": 0,
        "started_at": None,
        "completed_at": None,
        "last_observation": None,
        "workspace_id": None,
        "execution_id": execution_id,
        "phase_id": None,
        **cells,
    }
    return _Row(data)  # type: ignore[return-value]  # duck-typed Record, as the converter reads it


def _cache_only(execution_id: str, model: str) -> ExecutionCost:
    row = _row(execution_id, model, cache_creation=_MILLION, cache_creation_1h=_MILLION)
    return ExecutionCostQueryService(Mock())._build_from_token_usage(execution_id, [row], {})


def _summary_only(execution_id: str, usd: str) -> ExecutionCost:
    row = _row(execution_id, _OPUS, sdk_cost=Decimal(usd))
    return ExecutionCostQueryService(Mock())._build_from_summary(execution_id, [row], {}, {})


async def test_cache_only_and_summary_only_costs_are_shown_with_their_coverage(
    client: AsyncClient, lane2: _ExecutionCosts, history: _History
) -> None:
    """No input or output tokens is not "no cost": cache writes and SDK totals are spend."""
    lane2.costs = [
        _cache_only("exec-cache", _OPUS),
        _cache_only("exec-cache-unknown-model", "unknown-review-model"),
        _summary_only("exec-summary", "2.25"),
        _summary_only("exec-summary-zero", "0"),
    ]
    history.entries = [_firing(c.execution_id) for c in lane2.costs]
    # The shapes the reader really returns, so the assertions below are not vacuous.
    assert [c.input_tokens + c.output_tokens for c in lane2.costs] == [0, 0, 0, 0]
    assert [c.unpriced_observation_count for c in lane2.costs] == [0, 1, 0, 0]

    entries = await _entries(client)

    for cost in lane2.costs:
        entry = entries[cost.execution_id]
        assert entry.cost_usd == float(cost.total_cost_usd), cost.execution_id
        assert entry.unpriced_observation_count == cost.unpriced_observation_count
        assert entry.cost_display == format_cost(
            cost.total_cost_usd, cost.unpriced_observation_count
        )
    assert entries["exec-cache"].cost_display == "$8.00"
    assert entries["exec-cache-unknown-model"].cost_display == UNPRICED
    assert entries["exec-summary"].cost_display == "$2.25"
    assert entries["exec-summary-zero"].cost_display == "$0.00"


async def test_global_history_reads_no_cost_however_many_triggers(
    client: AsyncClient,
    lane2: _ExecutionCosts,
    history: _History,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The global list carries no cost, so it must not price each trigger's page."""
    from syn_api.routes.triggers import queries

    names = [f"trig-{n}" for n in range(3)]
    history.entries = [
        TriggerHistoryEntry(trigger_id=name, execution_id=f"exec-{name}", fired_at=FIRED)
        for name in names
    ]
    lane2.costs = [_cost(f"exec-{name}", "1.00") for name in names]

    async def _triggers(
        repository: str | None = None, status: str | None = None
    ) -> Ok[list[TriggerSummary]]:
        return Ok(
            [
                TriggerSummary(
                    trigger_id=name,
                    name=name,
                    event="push",
                    repository="org/repo",
                    workflow_id="wf-1",
                    status="active",
                )
                for name in names
            ]
        )

    monkeypatch.setattr(queries, "list_triggers", _triggers)

    response = await client.get("/triggers/history?limit=1")

    assert response.status_code == 200, response.text
    assert len(TriggerHistoryListResponse.model_validate(response.json()).entries) == 1
    assert lane2.calls == []
