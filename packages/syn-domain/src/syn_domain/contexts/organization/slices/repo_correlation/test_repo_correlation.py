"""Tests for RepoCorrelationProjection."""

from __future__ import annotations

from typing import Any

import pytest

from syn_domain.contexts.organization.slices.repo_correlation.projection import (
    RepoCorrelationProjection,
    _extract_repo_name,
)


class FakeProjectionStore:
    """Minimal in-memory store for unit tests (no settings dependency)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())

    async def delete(self, projection: str, key: str) -> None:
        self._data.get(projection, {}).pop(key, None)

    async def delete_all(self, projection: str) -> None:
        self._data.pop(projection, None)


@pytest.mark.unit
class TestRepoCorrelationProjection:
    @pytest.mark.asyncio
    async def test_trigger_fired_creates_correlation(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        await proj.on_trigger_fired({
            "repository": "acme/backend",
            "execution_id": "exec-1",
            "workflow_id": "wf-1",
        })

        correlations = await proj.get_repos_for_execution("exec-1")
        assert len(correlations) == 1
        assert correlations[0].repo_full_name == "acme/backend"
        assert correlations[0].execution_id == "exec-1"
        assert correlations[0].correlation_source == "trigger"

    @pytest.mark.asyncio
    async def test_execution_started_creates_correlation_from_inputs(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        await proj.on_workflow_execution_started({
            "execution_id": "exec-2",
            "workflow_id": "wf-2",
            "inputs": {"repository_url": "https://github.com/acme/frontend"},
        })

        correlations = await proj.get_repos_for_execution("exec-2")
        assert len(correlations) == 1
        assert correlations[0].repo_full_name == "acme/frontend"
        assert correlations[0].correlation_source == "template"

    @pytest.mark.asyncio
    async def test_trigger_fired_skips_empty_repository(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        await proj.on_trigger_fired({
            "repository": "",
            "execution_id": "exec-3",
        })

        correlations = await proj.get_repos_for_execution("exec-3")
        assert len(correlations) == 0

    @pytest.mark.asyncio
    async def test_multi_repo_execution(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        await proj.on_trigger_fired({
            "repository": "acme/repo-a",
            "execution_id": "exec-4",
            "workflow_id": "wf-4",
        })
        await proj.on_trigger_fired({
            "repository": "acme/repo-b",
            "execution_id": "exec-4",
            "workflow_id": "wf-4",
        })

        correlations = await proj.get_repos_for_execution("exec-4")
        assert len(correlations) == 2
        names = {c.repo_full_name for c in correlations}
        assert names == {"acme/repo-a", "acme/repo-b"}

    @pytest.mark.asyncio
    async def test_get_executions_for_repo(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        await proj.on_trigger_fired({
            "repository": "acme/shared",
            "execution_id": "exec-5",
            "workflow_id": "wf-5",
        })
        await proj.on_trigger_fired({
            "repository": "acme/shared",
            "execution_id": "exec-6",
            "workflow_id": "wf-6",
        })

        correlations = await proj.get_executions_for_repo("acme/shared")
        assert len(correlations) == 2
        exec_ids = {c.execution_id for c in correlations}
        assert exec_ids == {"exec-5", "exec-6"}

    @pytest.mark.asyncio
    async def test_no_duplicate_correlation_from_trigger_and_template(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        # First from trigger
        await proj.on_trigger_fired({
            "repository": "acme/api",
            "execution_id": "exec-7",
            "workflow_id": "wf-7",
        })
        # Then from execution started (should be deduped)
        await proj.on_workflow_execution_started({
            "execution_id": "exec-7",
            "workflow_id": "wf-7",
            "inputs": {"repository": "acme/api"},
        })

        correlations = await proj.get_repos_for_execution("exec-7")
        assert len(correlations) == 1
        assert correlations[0].correlation_source == "trigger"

    @pytest.mark.asyncio
    async def test_uses_projection_store(self) -> None:
        """Verify the projection uses ProjectionStore (not in-memory singleton)."""
        store = FakeProjectionStore()
        proj = RepoCorrelationProjection(store)

        await proj.on_trigger_fired({
            "repository": "acme/check",
            "execution_id": "exec-8",
            "workflow_id": "wf-8",
        })

        # Data should be in the store
        key = "exec-8:acme/check"
        record = await store.get("repo_correlation", key)
        assert record is not None
        assert record["repo_full_name"] == "acme/check"


@pytest.mark.unit
class TestExtractRepoName:
    def test_owner_repo_passthrough(self) -> None:
        assert _extract_repo_name("acme/repo") == "acme/repo"

    def test_https_url(self) -> None:
        assert _extract_repo_name("https://github.com/acme/repo") == "acme/repo"

    def test_https_url_with_git_suffix(self) -> None:
        assert _extract_repo_name("https://github.com/acme/repo.git") == "acme/repo"

    def test_ssh_url(self) -> None:
        assert _extract_repo_name("git@github.com:acme/repo.git") == "acme/repo"

    def test_empty_string(self) -> None:
        assert _extract_repo_name("") == ""

    def test_trailing_slash(self) -> None:
        assert _extract_repo_name("https://github.com/acme/repo/") == "acme/repo"
