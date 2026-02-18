#!/usr/bin/env python3
"""Quick import smoke test - catches broken imports fast.

Run with: uv run python scripts/import_check.py

Note: We import and immediately use __name__ to satisfy linter F401 rule.
"""

from __future__ import annotations


def main() -> int:
    """Test critical imports from all packages."""
    print("=== Import Smoke Test ===")

    modules_tested = []

    try:
        # Domain aggregates
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
            WorkspaceAggregate,
        )

        modules_tested.append(WorkspaceAggregate.__name__)

        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )

        modules_tested.append(WorkflowTemplateAggregate.__name__)

        from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
            AgentSessionAggregate,
        )

        modules_tested.append(AgentSessionAggregate.__name__)

        from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
            ArtifactAggregate,
        )

        modules_tested.append(ArtifactAggregate.__name__)

        from syn_domain.contexts.github.domain.aggregate_installation.InstallationAggregate import (
            InstallationAggregate,
        )

        modules_tested.append(InstallationAggregate.__name__)

        # Apps
        from syn_dashboard.main import app as dashboard_app

        modules_tested.append(dashboard_app.title)

        from syn_cli.main import app as cli_app

        modules_tested.append(cli_app.info.name or "cli_app")

        # API
        import syn_api

        modules_tested.append(f"syn_api v{syn_api.__version__}")

        # Adapters
        from syn_adapters.storage import (
            ArtifactRepositoryProtocol,
            SessionRepositoryProtocol,
        )

        modules_tested.append(SessionRepositoryProtocol.__name__)
        modules_tested.append(ArtifactRepositoryProtocol.__name__)

        print(f"✅ All {len(modules_tested)} imports OK")
        return 0

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
