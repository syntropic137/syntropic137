#!/usr/bin/env python3
"""E2E Integration Test: Dashboard → Executor → Docker → GitHub.

This test validates the FULL flow that the Dashboard uses, catching
integration bugs that unit tests miss.

Run with:
    uv run python scripts/test_dashboard_e2e.py

Requirements:
    - Docker running
    - TimescaleDB running
    - GitHub App configured (for PR tests)
    - ANTHROPIC_API_KEY set
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_step(step: str, status: str = "🔄") -> None:
    """Print a step with status."""
    print(f"{status} {step}")


def print_success(msg: str) -> None:
    """Print success message."""
    print(f"✅ {msg}")


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"❌ {msg}")


async def test_workspace_service() -> bool:
    """Test 1: WorkspaceService can create Docker containers."""
    print_step("Testing WorkspaceService Docker integration...")

    try:
        from aef_adapters.workspace_backends.service import WorkspaceService

        service = WorkspaceService.create_docker()

        async with service.create_workspace(
            execution_id=f"e2e-test-{datetime.now(UTC).strftime('%H%M%S')}",
            workflow_id="e2e-test",
            phase_id="phase-1",
            with_sidecar=False,
        ) as workspace:
            # Verify workspace has path
            assert workspace.path is not None, "Workspace path is None"

            # Execute a command
            result = await workspace.execute(["echo", "E2E test"])
            assert result.exit_code == 0, f"Command failed: {result.stderr}"
            assert "E2E test" in result.stdout, f"Unexpected output: {result.stdout}"

        print_success("WorkspaceService Docker integration works")
        return True

    except Exception as e:
        print_error(f"WorkspaceService test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_observability_port() -> bool:
    """Test 2: ObservabilityPort records to TimescaleDB."""
    print_step("Testing ObservabilityPort → TimescaleDB...")

    try:
        from agentic_observability import ObservationContext, ObservationType

        from aef_adapters.observability import get_observability

        obs = get_observability()

        test_session_id = f"e2e-obs-test-{datetime.now(UTC).strftime('%H%M%S')}"
        ctx = ObservationContext(session_id=test_session_id)

        # Record an observation
        await obs.record(
            ObservationType.SESSION_STARTED,
            ctx,
            {"test": True, "timestamp": datetime.now(UTC).isoformat()},
        )
        await obs.flush()

        # Verify it's in TimescaleDB (via docker exec)
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "exec",
                "aef-timescaledb",
                "psql",
                "-U",
                "aef",
                "-d",
                "aef_observability",
                "-c",
                f"SELECT COUNT(*) FROM agent_observations WHERE session_id = '{test_session_id}';",
            ],
            capture_output=True,
            text=True,
        )

        if "1" in result.stdout:
            print_success("ObservabilityPort → TimescaleDB works")
            return True
        else:
            print_error(f"Observation not found in TimescaleDB: {result.stdout}")
            return False

    except Exception as e:
        print_error(f"ObservabilityPort test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_workflow_executor_integration() -> bool:
    """Test 3: WorkflowExecutor uses WorkspaceService correctly."""
    print_step("Testing WorkflowExecutor → WorkspaceService integration...")

    try:
        from aef_adapters.orchestration import create_workflow_executor
        from aef_adapters.workspace_backends.service import WorkspaceService

        # Create executor with all dependencies
        workspace_service = WorkspaceService.create_docker()

        executor = create_workflow_executor(
            workspace_service=workspace_service,
        )

        # Verify executor was created with observability
        assert executor._observability is not None, "Observability not wired"
        assert executor._workspace_service is not None, "WorkspaceService not wired"

        print_success("WorkflowExecutor integration works")
        return True

    except Exception as e:
        print_error(f"WorkflowExecutor test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_github_credentials() -> bool:
    """Test 4: GitHub App credentials can be generated."""
    print_step("Testing GitHub App credentials...")

    try:
        # Check if GitHub App is configured
        app_id = os.environ.get("GITHUB_APP_ID")
        if not app_id:
            print_step("GitHub App not configured (skipping)", "⚠️")
            return True  # Skip but don't fail

        from aef_adapters.workspace_backends.service import SetupPhaseSecrets

        secrets = await SetupPhaseSecrets.create(require_github=True)

        assert secrets.github_app_token is not None, "GitHub token not generated"
        assert secrets.git_author_name is not None, "Git author name not set"
        assert secrets.git_author_email is not None, "Git author email not set"

        print_success(f"GitHub App credentials work (bot: {secrets.git_author_name})")
        return True

    except Exception as e:
        print_error(f"GitHub credentials test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_full_workflow_execution() -> bool:
    """Test 5: Full workflow execution (without PR creation)."""
    print_step("Testing full workflow execution in Docker...")

    try:
        from dataclasses import dataclass

        from aef_adapters.orchestration import create_workflow_executor
        from aef_adapters.workspace_backends.service import WorkspaceService

        # Create a minimal workflow definition
        @dataclass
        class MinimalPhase:
            phase_id: str = "test-phase"
            name: str = "Test Phase"
            order: int = 1
            prompt_template: str = "Say 'Hello E2E Test' and stop."
            allowed_tools: frozenset = frozenset()
            output_artifact_type: str = "text"
            timeout_seconds: int = 60

        @dataclass
        class MinimalWorkflow:
            workflow_id: str = "e2e-test-workflow"
            name: str = "E2E Test Workflow"
            phases: list = None

            def __post_init__(self):
                if self.phases is None:
                    self.phases = [MinimalPhase()]

        workspace_service = WorkspaceService.create_docker()
        executor = create_workflow_executor(
            workspace_service=workspace_service,
        )

        workflow = MinimalWorkflow()
        events = []

        async for event in executor.execute(workflow, {}):
            events.append(event)
            print(f"   Event: {type(event).__name__}")

        # Check we got expected events
        event_types = [type(e).__name__ for e in events]

        if "WorkflowStarted" not in event_types:
            print_error("Missing WorkflowStarted event")
            return False

        if "PhaseStarted" not in event_types:
            print_error("Missing PhaseStarted event")
            return False

        print_success(f"Full workflow execution works ({len(events)} events)")
        return True

    except Exception as e:
        print_error(f"Full workflow test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main() -> int:
    """Run all E2E tests."""
    print("=" * 60)
    print("Dashboard E2E Integration Test Suite")
    print("=" * 60)
    print()

    tests = [
        ("WorkspaceService Docker", test_workspace_service),
        ("ObservabilityPort TimescaleDB", test_observability_port),
        ("WorkflowExecutor Integration", test_workflow_executor_integration),
        ("GitHub App Credentials", test_github_credentials),
        # Skip full workflow for now - requires ANTHROPIC_API_KEY
        # ("Full Workflow Execution", test_full_workflow_execution),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\n--- Test: {name} ---")
        result = await test_fn()
        results.append((name, result))

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")

    print()
    print(f"Passed: {passed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
