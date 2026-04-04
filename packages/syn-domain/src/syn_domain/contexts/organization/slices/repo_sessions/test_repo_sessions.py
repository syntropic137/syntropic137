"""Tests for GetRepoSessionsHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
    GetRepoSessionsQuery,
)
from syn_domain.contexts.organization.slices.conftest import FakeProjectionStore
from syn_domain.contexts.organization.slices.repo_sessions.GetRepoSessionsHandler import (
    GetRepoSessionsHandler,
)


@pytest.mark.unit
class TestGetRepoSessionsHandler:
    @pytest.mark.asyncio
    async def test_returns_sessions_for_correlated_executions(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoSessionsHandler(store)

        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "session_summaries",
            "sess-1",
            {
                "id": "sess-1",
                "execution_id": "exec-1",
                "status": "completed",
                "started_at": "2026-03-06T10:00:00",
            },
        )
        await store.save(
            "session_summaries",
            "sess-2",
            {
                "id": "sess-2",
                "execution_id": "exec-99",
                "status": "completed",
                "started_at": "2026-03-06T11:00:00",
            },
        )

        result = await handler.handle(GetRepoSessionsQuery(repo_id="acme/api"))
        assert len(result) == 1
        assert result[0].id == "sess-1"
        assert result[0].execution_id == "exec-1"
        assert result[0].status == "completed"
        assert result[0].started_at == "2026-03-06T10:00:00"

    @pytest.mark.asyncio
    async def test_matches_by_repo_full_name_not_repo_id(self) -> None:
        """Handler should match correlations using repo_full_name, not UUID repo_id."""
        store = FakeProjectionStore()
        handler = GetRepoSessionsHandler(store)

        await store.save(
            "repo_correlation",
            "exec-1:owner/repo",
            {
                "repo_full_name": "owner/repo",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "session_summaries",
            "sess-1",
            {
                "id": "sess-1",
                "execution_id": "exec-1",
                "status": "completed",
                "started_at": "2026-03-06T10:00:00",
            },
        )

        # Query with a UUID repo_id but the correct repo_full_name
        result = await handler.handle(
            GetRepoSessionsQuery(
                repo_id="a1b2c3d4-0000-0000-0000-000000000000",
                repo_full_name="owner/repo",
            )
        )
        assert len(result) == 1
        assert result[0].id == "sess-1"

        # Without repo_full_name, UUID alone should not match
        result_empty = await handler.handle(
            GetRepoSessionsQuery(
                repo_id="a1b2c3d4-0000-0000-0000-000000000000",
            )
        )
        assert len(result_empty) == 0

    @pytest.mark.asyncio
    async def test_empty_for_unknown_repo(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoSessionsHandler(store)

        result = await handler.handle(GetRepoSessionsQuery(repo_id="unknown/repo"))
        assert len(result) == 0
