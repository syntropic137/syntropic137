"""Tests for GetRepoSessionsHandler."""

from __future__ import annotations

from typing import Any

import pytest

from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
    GetRepoSessionsQuery,
)
from syn_domain.contexts.organization.slices.repo_sessions.handler import (
    GetRepoSessionsHandler,
)


class FakeProjectionStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())


@pytest.mark.unit
class TestGetRepoSessionsHandler:
    @pytest.mark.asyncio
    async def test_returns_sessions_for_correlated_executions(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoSessionsHandler(store)

        await store.save("repo_correlation", "exec-1:acme/api", {
            "repo_full_name": "acme/api", "execution_id": "exec-1",
        })
        await store.save("session_summaries", "sess-1", {
            "id": "sess-1", "execution_id": "exec-1",
            "status": "completed", "started_at": "2026-03-06T10:00:00",
        })
        await store.save("session_summaries", "sess-2", {
            "id": "sess-2", "execution_id": "exec-99",
            "status": "completed", "started_at": "2026-03-06T11:00:00",
        })

        result = await handler.handle(GetRepoSessionsQuery(repo_id="acme/api"))
        assert len(result) == 1
        assert result[0]["id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_empty_for_unknown_repo(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoSessionsHandler(store)

        result = await handler.handle(GetRepoSessionsQuery(repo_id="unknown/repo"))
        assert len(result) == 0
