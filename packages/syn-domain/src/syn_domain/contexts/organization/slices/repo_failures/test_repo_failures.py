"""Tests for GetRepoFailuresHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.queries.get_repo_failures import (
    GetRepoFailuresQuery,
)
from syn_domain.contexts.organization.slices.conftest import FakeProjectionStore
from syn_domain.contexts.organization.slices.repo_failures.GetRepoFailuresHandler import (
    GetRepoFailuresHandler,
)


@pytest.mark.unit
class TestGetRepoFailuresHandler:
    @pytest.mark.asyncio
    async def test_returns_only_failed_executions(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoFailuresHandler(store)

        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "repo_correlation",
            "exec-2:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-2",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "completed",
                "completed_at": "2026-03-06T10:00:00",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-2",
            {
                "workflow_execution_id": "exec-2",
                "status": "failed",
                "completed_at": "2026-03-06T11:00:00",
                "error_message": "Container crashed",
                "error_type": "crash",
            },
        )

        result = await handler.handle(GetRepoFailuresQuery(repo_id="acme/api"))
        assert len(result) == 1
        assert result[0].execution_id == "exec-2"
        assert result[0].error_message == "Container crashed"
        assert result[0].error_type == "crash"

    @pytest.mark.asyncio
    async def test_empty_when_no_failures(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoFailuresHandler(store)

        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "completed",
            },
        )

        result = await handler.handle(GetRepoFailuresQuery(repo_id="acme/api"))
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_sorting_by_failed_at(self) -> None:
        """Failures should be sorted by failed_at descending (newest first)."""
        store = FakeProjectionStore()
        handler = GetRepoFailuresHandler(store)

        for i in range(3):
            await store.save(
                "repo_correlation",
                f"exec-{i}:acme/api",
                {
                    "repo_full_name": "acme/api",
                    "execution_id": f"exec-{i}",
                },
            )
            await store.save(
                "workflow_executions",
                f"exec-{i}",
                {
                    "workflow_execution_id": f"exec-{i}",
                    "status": "failed",
                    "completed_at": f"2026-03-0{i + 4}T10:00:00",
                    "error_message": f"Error {i}",
                },
            )

        result = await handler.handle(GetRepoFailuresQuery(repo_id="acme/api"))
        assert len(result) == 3
        # Newest first
        assert result[0].failed_at == "2026-03-06T10:00:00"
        assert result[1].failed_at == "2026-03-05T10:00:00"
        assert result[2].failed_at == "2026-03-04T10:00:00"

    @pytest.mark.asyncio
    async def test_empty_error_fields(self) -> None:
        """Missing error_type and error_message should default to empty strings."""
        store = FakeProjectionStore()
        handler = GetRepoFailuresHandler(store)

        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "failed",
                "completed_at": "2026-03-06T10:00:00",
                # No error_message or error_type
            },
        )

        result = await handler.handle(GetRepoFailuresQuery(repo_id="acme/api"))
        assert len(result) == 1
        assert result[0].error_message == ""
        assert result[0].error_type == ""
