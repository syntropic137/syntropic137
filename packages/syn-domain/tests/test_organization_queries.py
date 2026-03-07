"""Validation tests for organization query DTOs.

Verifies that queries reject invalid inputs.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.queries.get_global_cost import (
    GetGlobalCostQuery,
)
from syn_domain.contexts.organization.domain.queries.get_global_overview import (
    GetGlobalOverviewQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_activity import (
    GetRepoActivityQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_cost import (
    GetRepoCostQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_failures import (
    GetRepoFailuresQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_health import (
    GetRepoHealthQuery,
)
from syn_domain.contexts.organization.domain.queries.get_repo_sessions import (
    GetRepoSessionsQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_activity import (
    GetSystemActivityQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_cost import (
    GetSystemCostQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_history import (
    GetSystemHistoryQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_patterns import (
    GetSystemPatternsQuery,
)
from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)


@pytest.mark.unit
class TestRepoQueryValidation:
    def test_get_repo_health_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="repo_id is required"):
            GetRepoHealthQuery(repo_id="")

    def test_get_repo_health_accepts_valid_id(self) -> None:
        q = GetRepoHealthQuery(repo_id="repo-123")
        assert q.repo_id == "repo-123"
        assert q.window_hours == 168

    def test_get_repo_activity_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="repo_id is required"):
            GetRepoActivityQuery(repo_id="")

    def test_get_repo_activity_accepts_valid_id(self) -> None:
        q = GetRepoActivityQuery(repo_id="repo-1", limit=10, offset=5)
        assert q.limit == 10
        assert q.offset == 5

    def test_get_repo_failures_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="repo_id is required"):
            GetRepoFailuresQuery(repo_id="")

    def test_get_repo_cost_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="repo_id is required"):
            GetRepoCostQuery(repo_id="")

    def test_get_repo_sessions_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="repo_id is required"):
            GetRepoSessionsQuery(repo_id="")


@pytest.mark.unit
class TestSystemQueryValidation:
    def test_get_system_status_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="system_id is required"):
            GetSystemStatusQuery(system_id="")

    def test_get_system_status_accepts_valid_id(self) -> None:
        q = GetSystemStatusQuery(system_id="sys-1")
        assert q.system_id == "sys-1"

    def test_get_system_activity_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="system_id is required"):
            GetSystemActivityQuery(system_id="")

    def test_get_system_cost_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="system_id is required"):
            GetSystemCostQuery(system_id="")

    def test_get_system_patterns_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="system_id is required"):
            GetSystemPatternsQuery(system_id="")

    def test_get_system_history_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="system_id is required"):
            GetSystemHistoryQuery(system_id="")


@pytest.mark.unit
class TestGlobalQueryValidation:
    def test_get_global_overview_creates_with_query_id(self) -> None:
        q = GetGlobalOverviewQuery()
        assert q.query_id

    def test_get_global_cost_default_window(self) -> None:
        q = GetGlobalCostQuery()
        assert q.window_hours == 720

    def test_get_global_cost_custom_window(self) -> None:
        q = GetGlobalCostQuery(window_hours=168)
        assert q.window_hours == 168
