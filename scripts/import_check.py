#!/usr/bin/env python3
"""Quick import smoke test - catches broken imports fast.

Run with: uv run python scripts/import_check.py
"""


def main() -> int:
    """Test critical imports from all packages."""
    print("=== Import Smoke Test ===")

    try:
        # Domain aggregates
        from aef_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
            WorkspaceAggregate,
        )
        from aef_domain.contexts.orchestration.domain.aggregate_workflow.WorkflowAggregate import (
            WorkflowAggregate,
        )
        from aef_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
            ArtifactAggregate,
        )
        from aef_domain.contexts.github.domain.aggregate_installation.InstallationAggregate import (
            InstallationAggregate,
        )

        # Apps
        from aef_dashboard.main import app as dashboard_app
        from aef_cli.main import app as cli_app

        # Adapters
        from aef_adapters.storage import (
            SessionRepositoryProtocol,
            ArtifactRepositoryProtocol,
        )

        print("✅ All imports OK")
        return 0

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
