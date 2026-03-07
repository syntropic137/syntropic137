"""Tests for GetRepoFailuresHandler."""

from __future__ import annotations

from typing import Any

import pytest

from syn_domain.contexts.organization.domain.queries.get_repo_failures import (
    GetRepoFailuresQuery,
)
from syn_domain.contexts.organization.slices.repo_failures.handler import (
    GetRepoFailuresHandler,
)


class FakeProjectionStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())


@pytest.mark.unit
class TestGetRepoFailuresHandler:
    @pytest.mark.asyncio
    async def test_returns_only_failed_executions(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoFailuresHandler(store)

        await store.save("repo_correlation", "exec-1:acme/api", {
            "repo_full_name": "acme/api", "execution_id": "exec-1",
        })
        await store.save("repo_correlation", "exec-2:acme/api", {
            "repo_full_name": "acme/api", "execution_id": "exec-2",
        })
        await store.save("workflow_executions", "exec-1", {
            "workflow_execution_id": "exec-1", "status": "completed",
            "completed_at": "2026-03-06T10:00:00",
        })
        await store.save("workflow_executions", "exec-2", {
            "workflow_execution_id": "exec-2", "status": "failed",
            "completed_at": "2026-03-06T11:00:00",
            "error_message": "Container crashed",
        })

        result = await handler.handle(GetRepoFailuresQuery(repo_id="acme/api"))
        assert len(result) == 1
        assert result[0].execution_id == "exec-2"
        assert result[0].error_message == "Container crashed"

    @pytest.mark.asyncio
    async def test_empty_when_no_failures(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoFailuresHandler(store)

        await store.save("repo_correlation", "exec-1:acme/api", {
            "repo_full_name": "acme/api", "execution_id": "exec-1",
        })
        await store.save("workflow_executions", "exec-1", {
            "workflow_execution_id": "exec-1", "status": "completed",
        })

        result = await handler.handle(GetRepoFailuresQuery(repo_id="acme/api"))
        assert len(result) == 0
