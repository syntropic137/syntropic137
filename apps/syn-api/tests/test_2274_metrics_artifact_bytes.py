"""#2274: GET /metrics reports the artifact bytes the projection summed.

Seeded through the dashboard_metrics handler and read over HTTP, so a value
the projection writes but the route or response model drops still fails here.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_domain.contexts.agent_sessions import CanonicalTotals

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


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


class _NoObservedSessions:
    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        return CanonicalTotals()


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    from syn_api._wiring import ensure_connected
    from syn_api.main import create_app
    from syn_api.routes import metrics

    await ensure_connected()
    monkeypatch.setattr(metrics, "get_canonical_usage_query", _NoObservedSessions)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def test_metrics_returns_the_projected_artifact_bytes(client: AsyncClient) -> None:
    from syn_api._wiring import get_projection_mgr

    counters = get_projection_mgr().dashboard_metrics
    await counters.on_artifact_created({"artifact_id": "a-1", "size_bytes": 4096})
    await counters.on_artifact_created({"artifact_id": "a-2", "size_bytes": 904})

    metrics = (await client.get("/metrics")).json()

    assert metrics["total_artifacts"] == 2
    assert metrics["total_artifact_bytes"] == 5000
