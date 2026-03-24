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
        from syn_api.main import app as api_app

        modules_tested.append(api_app.title)

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

        print(f"✅ All {len(modules_tested)} package imports OK")

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1

    # ── Dev scripts: verify imports resolve ──
    # AST-parse scripts/ to catch stale imports after refactors.
    # Only fail on scripts referenced from the justfile (actively used);
    # warn on the rest (POC/demo scripts that may lag behind).
    import ast
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = Path(__file__).parent

    # Discover which scripts are actively called from the justfile
    justfile = repo_root / "justfile"
    active_scripts: set[str] = set()
    if justfile.exists():
        for match in re.finditer(r"scripts/([a-z_]+\.py)", justfile.read_text()):
            active_scripts.add(match.group(1))

    our_packages = ("syn_api", "syn_cli", "syn_domain", "syn_adapters", "syn_shared", "syn_collector", "syn_tokens")

    errors: list[str] = []
    warnings: list[str] = []

    for script in sorted(scripts_dir.glob("*.py")):
        if script.name == "import_check.py":
            continue
        try:
            tree = ast.parse(script.read_text(), filename=str(script))
        except SyntaxError:
            continue  # ruff catches syntax errors

        for node in ast.walk(tree):
            mod_name: str | None = None
            if isinstance(node, ast.Import):
                mod_name = node.names[0].name
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mod_name = node.module

            if mod_name is None or not any(mod_name.startswith(p) for p in our_packages):
                continue

            try:
                __import__(mod_name.split(".")[0])
                __import__(mod_name)
            except (ImportError, ModuleNotFoundError) as e:
                msg = f"  {script.name}: {mod_name} → {e}"
                if script.name in active_scripts:
                    errors.append(msg)
                else:
                    warnings.append(msg)

    if warnings:
        print(f"⚠️  {len(warnings)} broken import(s) in inactive scripts/ (not blocking):")
        for w in warnings:
            print(w)

    if errors:
        print(f"❌ {len(errors)} broken import(s) in active scripts/:")
        for e in errors:
            print(e)
        return 1

    print(f"✅ All active scripts/ imports OK")
    return 0


if __name__ == "__main__":
    exit(main())
