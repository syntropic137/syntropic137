"""GET /metrics/shipped: the wire contract, and the merge recorder feeding it."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from syn_adapters.events.shipped_ledger_memory import InMemoryShippedLedger
from syn_domain.contexts.github import EventSource, NormalizedEvent
from syn_domain.contexts.orchestration import (
    CommitShipped,
    PullRequestMerged,
    PullRequestOpened,
    ShippedMetricsQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

TODAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
EARLIER = datetime(2026, 9, 20, 12, tzinfo=UTC)


async def _seeded() -> InMemoryShippedLedger:
    ledger = InMemoryShippedLedger()
    await ledger.record_commit(CommitShipped("a", "e1", "wf", "Implement", "acme/api", NOW))
    await ledger.record_commit(CommitShipped("b", "e1", "wf", "Implement", "acme/api", EARLIER))
    url = "https://github.com/acme/api/pull/7"
    await ledger.record_pull_request_opened(
        PullRequestOpened("acme/api", 7, url, "e1", "wf", "Implement", NOW)
    )
    await ledger.record_pull_request_merged(PullRequestMerged("acme/api", 7, NOW))
    await ledger.record_pull_request_merged(PullRequestMerged("me/own", 1, NOW))
    return ledger


async def _connected() -> None:
    return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    import asyncio

    from syn_api.routes import metrics

    ledger = asyncio.run(_seeded())
    app = FastAPI()
    app.include_router(metrics.router)
    service = ShippedMetricsQueryService(ledger, today=lambda: TODAY)
    with (
        patch.object(metrics, "ensure_connected", _connected),
        patch.object(metrics, "get_shipped_metrics_query", lambda: service),
    ):
        yield TestClient(app)


def test_contract_shape(client: TestClient) -> None:
    body = client.get("/metrics/shipped").json()
    assert body["window"] == {"days": 14, "from": "2026-09-26", "to": "2026-10-09"}
    assert body["previous"] == {"from": "2026-09-12", "to": "2026-09-25"}
    commits = body["commits"]
    assert (commits["total"], commits["previous_total"], commits["delta"]) == (1, 1, 0)
    assert (commits["delta_display"], commits["delta_unit"]) == ("0%", "percent")
    assert len(commits["series"]) == 14
    assert commits["series"][-1] == {"date": "2026-10-09", "value": 1}
    assert body["repos"] == ["acme/api"]
    assert body["by_workflow"] == [
        {
            "workflow_id": "wf",
            "name": "Implement",
            "commits": 1,
            "prs_opened": 1,
            "prs_merged": 1,
            "repos_touched": 1,
        }
    ]
    assert (body["prs_opened"]["total"], body["prs_merged"]["total"]) == (1, 1)  # not me/own#1
    assert body["merge_rate"]["total"] == 100.0  # percent 0-100, the UI contract
    assert body["merge_rate"]["delta_unit"] == "points"
    assert body["prs_opened"]["reason"] is None
    assert body["prs_opened"]["delta_percent"] is None  # previous window was zero
    assert body["unavailable"] == []
    assert "commits_without_workflow" not in body


def test_workflow_filter_empties_by_workflow(client: TestClient) -> None:
    body = client.get("/metrics/shipped", params={"days": 7, "workflow_id": "wf"}).json()
    assert body["window"]["days"] == 7
    assert body["workflow_id"] == "wf"
    assert body["by_workflow"] == []


@pytest.mark.parametrize("days", [1, 13, 31])
def test_other_windows_are_refused(client: TestClient, days: int) -> None:
    assert client.get("/metrics/shipped", params={"days": days}).status_code == 422


@pytest.mark.asyncio
async def test_a_store_failure_is_503_not_zero() -> None:
    from syn_api.routes import metrics

    class _Boom(Exception):
        pass

    with (
        patch.object(metrics, "ensure_connected", _connected),
        patch.object(metrics, "get_shipped_metrics_query", side_effect=_Boom("db down")),
        pytest.raises(HTTPException) as caught,
    ):
        await metrics.get_shipped_metrics_endpoint(days=14, workflow_id=None)
    assert caught.value.status_code == 503


def _pr_event(
    action: str,
    merged: bool | None = None,
    merged_at: str | None = None,
    repository: str = "acme/api",
    repository_id: int | None = None,
) -> NormalizedEvent:
    payload = {
        "number": 7,
        "pull_request": {"merged": merged, "merged_at": merged_at},
        "repository": {"id": repository_id, "full_name": repository},
    }
    return NormalizedEvent(
        event_type="pull_request",
        action=action,
        repository=repository,
        installation_id="1",
        dedup_key="k",
        source=EventSource.WEBHOOK,
        payload=payload,
        received_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )


def test_a_merged_close_is_a_merge_on_its_merged_at() -> None:
    from syn_api.services.shipped_ledger import PullRequestMerge

    merge = PullRequestMerge.from_event(_pr_event("closed", True, "2026-10-08T23:30:00Z"))
    assert merge is not None
    assert (merge.repository, merge.number) == ("acme/api", 7)
    assert merge.merged_at == datetime(2026, 10, 8, 23, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("action", "merged"), [("closed", False), ("opened", False), ("synchronize", None)]
)
def test_anything_else_is_not_a_merge(action: str, merged: bool | None) -> None:
    from syn_api.services.shipped_ledger import PullRequestMerge

    assert PullRequestMerge.from_event(_pr_event(action, merged)) is None


@pytest.mark.asyncio
async def test_a_redelivered_merge_is_recorded_once() -> None:
    """Fail-open dedup can deliver the same merge twice; the ledger keeps one."""
    from syn_api.services import shipped_ledger as service

    ledger = InMemoryShippedLedger()
    await ledger.record_pull_request_opened(
        PullRequestOpened("acme/api", 7, "u", "e1", "wf", "Implement", NOW)
    )

    class _Store:
        shipped_ledger = ledger

        async def initialize(self) -> None:
            return None

    with patch("syn_api._wiring.get_event_store_instance", lambda: _Store()):
        for _ in range(3):
            await service.record_pull_request_merge(
                _pr_event("closed", True, "2026-10-08T23:30:00Z")
            )
        await service.record_pull_request_merge(_pr_event("opened"))
    rows = await ledger.daily(date(2026, 10, 1), date(2026, 10, 31))
    assert sum(r.prs_merged for r in rows) == 1


@pytest.mark.asyncio
async def test_a_transferred_repositorys_pr_still_merges() -> None:
    """Opened as acme/old#7; the repo moves to neworg/api (same id); merged there."""
    from syn_api.services import shipped_ledger as service

    ledger = InMemoryShippedLedger()
    await ledger.record_pull_request_opened(
        PullRequestOpened("acme/old", 7, "u", "e1", "wf", "Implement", NOW)
    )

    class _Store:
        shipped_ledger = ledger

        async def initialize(self) -> None:
            return None

    with patch("syn_api._wiring.get_event_store_instance", lambda: _Store()):
        await service.record_pull_request_merge(
            _pr_event("opened", repository="acme/old", repository_id=77)
        )
        await service.record_pull_request_merge(
            _pr_event("closed", True, "2026-10-08T23:30:00Z", "neworg/api", 77)
        )
    rows = await ledger.daily(date(2026, 10, 1), date(2026, 10, 31))
    assert sum(r.prs_merged for r in rows) == 1
    assert sum(r.prs_opened_merged for r in rows) == 1
