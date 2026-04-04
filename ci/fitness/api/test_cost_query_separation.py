"""Fitness function: cost routes must use query services, not projections.

Cost data lives exclusively in TimescaleDB (Lane 2). The projection store
is empty for cost data. This test ensures API routes never accidentally
query the projection store for cost reads.

See #532 for the architectural rationale.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.mark.architecture
class TestCostQuerySeparation:
    def test_cost_routes_use_query_service_not_projection(self) -> None:
        """Cost routes must import query services, not access projections directly."""
        costs_file = (
            _repo_root() / "apps" / "syn-api" / "src" / "syn_api" / "routes" / "costs.py"
        )
        content = costs_file.read_text(encoding="utf-8")

        violations: list[str] = []

        # Should not access projections via manager for cost reads
        if "manager.session_cost" in content:
            violations.append(
                "costs.py accesses manager.session_cost — use SessionCostQueryService"
            )
        if "manager.execution_cost" in content:
            violations.append(
                "costs.py accesses manager.execution_cost — use ExecutionCostQueryService"
            )

        # Should not call projection.get_all() for cost data
        if "projection.get_all" in content:
            violations.append(
                "costs.py calls projection.get_all() — use query_service.list_all()"
            )

        # Should not import get_projection_mgr for cost reads
        if "get_projection_mgr" in content:
            violations.append(
                "costs.py imports get_projection_mgr — use get_session_cost_query / "
                "get_execution_cost_query"
            )

        if violations:
            joined = "\n  ".join(violations)
            pytest.fail(
                f"Cost routes must use CostQueryService (TimescaleDB), not projections:\n"
                f"  {joined}\n\n"
                f"Cost data lives in TimescaleDB (Lane 2). Projection stores are empty.\n"
                f"See #532 and apps/syn-api/src/syn_api/routes/costs.py docstring."
            )

    def test_query_services_exist(self) -> None:
        """Query service files must exist in the expected locations."""
        session_qs = (
            _repo_root()
            / "packages"
            / "syn-domain"
            / "src"
            / "syn_domain"
            / "contexts"
            / "agent_sessions"
            / "slices"
            / "session_cost"
            / "query_service.py"
        )
        execution_qs = (
            _repo_root()
            / "packages"
            / "syn-domain"
            / "src"
            / "syn_domain"
            / "contexts"
            / "orchestration"
            / "slices"
            / "execution_cost"
            / "query_service.py"
        )

        missing: list[str] = []
        if not session_qs.exists():
            missing.append(f"Missing: {session_qs.relative_to(_repo_root())}")
        if not execution_qs.exists():
            missing.append(f"Missing: {execution_qs.relative_to(_repo_root())}")

        if missing:
            joined = "\n  ".join(missing)
            pytest.fail(
                f"Cost query service files are missing:\n  {joined}\n\n"
                f"See #532 for the expected file locations."
            )

    def test_query_services_use_asyncpg_pool(self) -> None:
        """Query services must require asyncpg.Pool (not optional)."""
        session_qs = (
            _repo_root()
            / "packages"
            / "syn-domain"
            / "src"
            / "syn_domain"
            / "contexts"
            / "agent_sessions"
            / "slices"
            / "session_cost"
            / "query_service.py"
        )
        execution_qs = (
            _repo_root()
            / "packages"
            / "syn-domain"
            / "src"
            / "syn_domain"
            / "contexts"
            / "orchestration"
            / "slices"
            / "execution_cost"
            / "query_service.py"
        )

        violations: list[str] = []
        for qs_file, name in [
            (session_qs, "SessionCostQueryService"),
            (execution_qs, "ExecutionCostQueryService"),
        ]:
            if not qs_file.exists():
                continue
            content = qs_file.read_text(encoding="utf-8")
            # Pool must NOT be optional (no `| None`, no `Optional`)
            if "pool: Any | None" in content or "pool: Optional" in content:
                violations.append(
                    f"{name} has optional pool — TimescaleDB pool must be required"
                )

        if violations:
            joined = "\n  ".join(violations)
            pytest.fail(
                f"Query services must require asyncpg.Pool:\n  {joined}\n\n"
                f"These services ONLY work with TimescaleDB — no fallback path."
            )
