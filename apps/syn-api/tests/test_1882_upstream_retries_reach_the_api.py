"""GET /observability/upstream-retries: in-phase retries per provider and model (#1882)."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from syn_adapters.events.queries import UPSTREAM_RETRY_COUNTS_SQL, UpstreamRetryCount
from syn_shared.upstream_failure import UpstreamRetryObservation

if TYPE_CHECKING:
    from datetime import datetime

pytestmark = [pytest.mark.unit]


class _Store:
    def __init__(self, rows: list[UpstreamRetryCount]) -> None:
        self._rows = rows
        self.asked_since: datetime | None = None

    async def query_upstream_retry_counts(self, *, since: datetime) -> list[UpstreamRetryCount]:
        self.asked_since = since
        return self._rows


class _DownStore:
    async def query_upstream_retry_counts(self, *, since: datetime) -> list[UpstreamRetryCount]:
        del since
        raise ConnectionError("observability db down")


def _client() -> TestClient:
    from syn_api.routes import observability

    app = FastAPI()
    app.include_router(observability.router)
    return TestClient(app)


def test_the_counts_reach_the_wire_per_provider_and_model() -> None:
    store = _Store(
        [
            UpstreamRetryCount("codex", "gpt-5.5-codex", "capacity", 7),
            UpstreamRetryCount("claude", None, "rate_limited", 2),
        ]
    )
    with patch("syn_api._wiring.get_event_store_instance", lambda: store):
        body = _client().get("/observability/upstream-retries", params={"window": "7d"}).json()

    assert body["window"] == "7d"
    assert body["total"] == 9
    assert body["counts"] == [
        {
            "provider": "codex",
            "requested_model": "gpt-5.5-codex",
            "upstream_kind": "capacity",
            "retries": 7,
        },
        {
            "provider": "claude",
            "requested_model": None,
            "upstream_kind": "rate_limited",
            "retries": 2,
        },
    ]
    assert store.asked_since is not None
    assert body["since"] == store.asked_since.isoformat()


@pytest.mark.asyncio
async def test_a_store_failure_is_503_not_zero() -> None:
    """Zero retries would tell an operator there is no quota pressure."""
    from syn_api.routes import observability

    with (
        patch("syn_api._wiring.get_event_store_instance", lambda: _DownStore()),
        pytest.raises(HTTPException) as caught,
    ):
        await observability.get_upstream_retries(window="24h")

    assert caught.value.status_code == 503


def test_the_count_groups_by_the_keys_the_writer_writes() -> None:
    """The writer serialises `UpstreamRetryObservation`; the SQL reads its keys.

    A field renamed on one side and not the other would count every retry
    under NULL, which no test at either end alone can see.
    """
    written = dataclasses.asdict(
        UpstreamRetryObservation(
            provider="codex", requested_model="m", upstream_kind="capacity", attempt=2
        )
    )

    for key in ("provider", "requested_model", "upstream_kind"):
        assert key in written
        assert f"data->>'{key}' AS {key}" in UPSTREAM_RETRY_COUNTS_SQL
