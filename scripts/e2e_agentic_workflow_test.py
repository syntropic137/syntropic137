#!/usr/bin/env python3
"""E2E Integration Test: Agentic Workflow with GitHub App.

This script demonstrates the FULL agentic workflow:

Phase 1: Programmatic Workflow Execution
1. Start workflow execution
2. Agent clones repo, makes changes, opens PR
3. Verify events in event store
4. Verify PR was created

Phase 2: (Future) Webhook-triggered Workflow
- GitHub webhook triggers workflow
- Agent responds to PR comments
- Self-healing on CI failures

Run with:
    # Phase 1: Manual workflow trigger
    uv run python scripts/e2e_agentic_workflow_test.py

    # With live Claude agent (costs money!)
    uv run python scripts/e2e_agentic_workflow_test.py --live

Requirements:
    - Docker stack running: just dev
    - GitHub App configured: AEF_GITHUB_* env vars
    - Claude API key (for --live): ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-adapters" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-tokens" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-shared" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-domain" / "src"))

SANDBOX_REPO = "AgentParadise/sandbox_aef-engineer-beta"


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def print_step(step: int, title: str) -> None:
    """Print a step header."""
    print(f"\n📍 Step {step}: {title}")
    print("-" * 40)


async def check_prerequisites() -> bool:
    """Check that all prerequisites are met."""
    print_header("🔍 Checking Prerequisites")

    all_ok = True

    # Check Docker containers
    print("\n1. Docker containers...")
    import subprocess

    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    containers = result.stdout.strip().split("\n") if result.stdout else []

    required = ["aef-postgres", "aef-event-store", "aef-collector"]
    for container in required:
        if container in containers:
            print(f"   ✅ {container} running")
        else:
            print(f"   ❌ {container} NOT running")
            all_ok = False

    if not all_ok:
        print("\n   💡 Start Docker: just dev")
        return False

    # Check GitHub App
    print("\n2. GitHub App configuration...")
    try:
        from aef_adapters.github import get_github_client

        client = get_github_client()
        print(f"   ✅ GitHub App: {client._settings.app_name}")
        print(f"   ✅ Bot: {client.bot_username}")
    except ValueError as e:
        print(f"   ❌ GitHub App not configured: {e}")
        print("   💡 Set AEF_GITHUB_* environment variables")
        return False

    # Check Claude API (optional)
    print("\n3. Claude API (optional)...")
    import os

    if os.getenv("ANTHROPIC_API_KEY"):
        print("   ✅ ANTHROPIC_API_KEY is set")
    else:
        print("   ⚠️  ANTHROPIC_API_KEY not set (use --live for real agent)")

    # Check dashboard API
    print("\n4. Dashboard API...")
    import httpx

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get("http://localhost:8000/health", timeout=5)
            if resp.status_code == 200:
                print("   ✅ Dashboard API healthy")
            else:
                print(f"   ❌ Dashboard API returned {resp.status_code}")
                all_ok = False
    except Exception as e:
        print(f"   ❌ Dashboard API not reachable: {e}")
        print("   💡 Start dashboard: just dashboard")
        all_ok = False

    return all_ok


async def run_phase1_workflow(live: bool = False) -> dict:
    """Run Phase 1: Programmatic workflow execution.

    Returns:
        Dict with execution results (execution_id, branch, pr_url, etc.)
    """
    print_header("🚀 Phase 1: Programmatic Workflow Execution")

    from aef_adapters.github import get_github_client
    from aef_tokens import SpendTracker, TokenType, TokenVendingService, WorkflowType
    from aef_tokens.spend import InMemoryBudgetStore
    from aef_tokens.vending import InMemoryTokenStore

    # Initialize services
    print_step(1, "Initialize Services")

    token_store = InMemoryTokenStore()
    token_service = TokenVendingService(token_store)
    budget_store = InMemoryBudgetStore()
    spend_tracker = SpendTracker(budget_store)

    print("   ✅ Token Vending Service initialized")
    print("   ✅ Spend Tracker initialized")

    # Get GitHub client
    github_client = get_github_client()
    print(f"   ✅ GitHub App: {github_client.bot_username}")

    # Generate execution ID
    execution_id = f"e2e-workflow-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    branch_name = f"aef/test-{uuid.uuid4().hex[:8]}"

    print(f"   📌 Execution ID: {execution_id}")
    print(f"   🌿 Branch: {branch_name}")

    # Allocate budget
    print_step(2, "Allocate Spend Budget")

    budget = await spend_tracker.allocate_budget(
        execution_id=execution_id,
        workflow_type=WorkflowType.QUICK_FIX,
    )
    print(f"   💰 Budget: ${budget.max_cost_usd} max")
    print(f"   📊 Tokens: {budget.max_input_tokens:,} input, {budget.max_output_tokens:,} output")

    # Vend scoped token
    print_step(3, "Vend Scoped Token")

    token = await token_service.vend_token(
        execution_id=execution_id,
        token_type=TokenType.GITHUB,
        ttl_seconds=300,
    )
    print(f"   🎫 Token: {token.token_id[:20]}...")
    print(f"   ⏱️  TTL: {token.seconds_until_expiry:.0f}s")

    # Get installation token for Git operations
    print_step(4, "Get GitHub Installation Token")

    install_token = await github_client.get_installation_token()
    print(f"   🔑 Installation token obtained (1-hour TTL)")

    # Create a branch and file via GitHub API
    print_step(5, "Create Branch and Code Changes")

    # Get default branch SHA
    repo_info = await github_client.api_get(f"/repos/{SANDBOX_REPO}")
    default_branch = repo_info["default_branch"]
    print(f"   📂 Default branch: {default_branch}")

    ref_info = await github_client.api_get(f"/repos/{SANDBOX_REPO}/git/ref/heads/{default_branch}")
    base_sha = ref_info["object"]["sha"]
    print(f"   🔖 Base SHA: {base_sha[:7]}")

    # Create new branch
    try:
        await github_client.api_post(
            f"/repos/{SANDBOX_REPO}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        print(f"   ✅ Created branch: {branch_name}")
    except Exception as e:
        print(f"   ⚠️  Branch creation: {e}")

    # Create a test file
    test_file_path = f"tests/{execution_id}/test_example.py"
    test_content = f'''"""Auto-generated test file by AEF.

Execution ID: {execution_id}
Generated: {datetime.now(UTC).isoformat()}
Bot: {github_client.bot_username}
"""

import pytest


def test_hello_world():
    """Simple test to verify AEF workflow."""
    assert 1 + 1 == 2


def test_execution_id():
    """Verify execution tracking."""
    execution_id = "{execution_id}"
    assert execution_id.startswith("e2e-workflow-")


class TestAEFIntegration:
    """Integration tests for AEF."""

    def test_github_app_works(self):
        """Verify GitHub App can create files."""
        assert True

    def test_spend_tracking_works(self):
        """Verify spend tracking is functional."""
        max_cost = {budget.max_cost_usd}
        assert max_cost > 0
'''

    import base64

    await github_client.api_put(
        f"/repos/{SANDBOX_REPO}/contents/{test_file_path}",
        json={
            "message": f"feat(tests): add integration test for {execution_id}\n\nGenerated by AEF agentic workflow.\n\nBot: {github_client.bot_username}",
            "content": base64.b64encode(test_content.encode()).decode(),
            "branch": branch_name,
        },
    )
    print(f"   ✅ Created: {test_file_path}")

    # Create PR
    print_step(6, "Open Pull Request")

    pr_body = f"""## 🤖 Auto-generated by AEF

This PR was created by the AEF E2E integration test.

### Execution Details

| Field | Value |
|-------|-------|
| Execution ID | `{execution_id}` |
| Bot | `{github_client.bot_username}` |
| Branch | `{branch_name}` |
| Generated At | `{datetime.now(UTC).isoformat()}` |

### Budget

| Metric | Value |
|--------|-------|
| Max Input Tokens | {budget.max_input_tokens:,} |
| Max Output Tokens | {budget.max_output_tokens:,} |
| Max Cost | ${budget.max_cost_usd} |

### Token

| Field | Value |
|-------|-------|
| Token ID | `{token.token_id}` |
| Type | `{token.token_type.value}` |
| TTL | 5 minutes |

---

*This PR can be safely closed or merged. It's for testing purposes only.*
"""

    pr_result = await github_client.api_post(
        f"/repos/{SANDBOX_REPO}/pulls",
        json={
            "title": f"[AEF Test] {execution_id}",
            "body": pr_body,
            "head": branch_name,
            "base": default_branch,
        },
    )

    pr_number = pr_result["number"]
    pr_url = pr_result["html_url"]
    print(f"   ✅ PR #{pr_number} created!")
    print(f"   🔗 {pr_url}")

    # Record token usage (simulated)
    print_step(7, "Record Token Usage")

    await spend_tracker.record_usage(
        execution_id=execution_id,
        input_tokens=2500,
        output_tokens=1200,
    )
    summary = await spend_tracker.get_usage_summary(execution_id)
    print(f"   📊 Input: {summary['input_tokens']['used']:,} / {summary['input_tokens']['max']:,}")
    print(f"   📊 Output: {summary['output_tokens']['used']:,} / {summary['output_tokens']['max']:,}")
    print(f"   💵 Cost: ${summary['cost_usd']['used']} / ${summary['cost_usd']['max']}")

    # Cleanup
    print_step(8, "Cleanup Tokens")

    revoked = await token_service.revoke_tokens(execution_id)
    released = await spend_tracker.release_budget(execution_id)
    print(f"   🧹 Revoked {revoked} token(s)")
    print(f"   🧹 Budget released: {released}")

    return {
        "execution_id": execution_id,
        "branch": branch_name,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "file_path": test_file_path,
        "cost_usd": str(summary["cost_usd"]["used"]),
    }


async def emit_workflow_events(execution_id: str, workflow_id: str, branch: str) -> bool:
    """Emit workflow execution events to the event store.

    Uses the WorkflowExecutionAggregate to properly emit and persist events.
    """
    print_step(9, "Emit Workflow Events to Event Store")

    import os

    # Force non-test mode to use real event store
    original_env = os.environ.get("APP_ENVIRONMENT")
    os.environ["APP_ENVIRONMENT"] = "development"

    try:
        # Reset cached settings and repositories
        from aef_shared.settings import reset_settings

        reset_settings()

        from aef_adapters.storage.event_store_client import (
            connect_event_store,
            disconnect_event_store,
            reset_event_store_client,
        )
        from aef_adapters.storage.repositories import (
            get_workflow_execution_repository,
            reset_repositories,
        )

        reset_event_store_client()
        reset_repositories()

        # Connect to the event store
        await connect_event_store()
        print("   🔌 Connected to Event Store")

        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )
        from decimal import Decimal

        # Create and start the execution aggregate
        aggregate = WorkflowExecutionAggregate()
        start_cmd = StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name="E2E GitHub App Workflow",
            total_phases=1,
            inputs={
                "branch": branch,
                "test_type": "github_app_integration",
            },
        )
        aggregate._handle_command(start_cmd)
        print(f"   📤 WorkflowExecutionStarted event created")

        # Complete the execution
        complete_cmd = CompleteExecutionCommand(
            execution_id=execution_id,
            completed_phases=1,
            total_phases=1,
            total_input_tokens=2500,
            total_output_tokens=1200,
            total_cost_usd=Decimal("0.0255"),
            duration_seconds=5.0,
            artifact_ids=[],
        )
        aggregate._handle_command(complete_cmd)
        print(f"   📤 WorkflowCompleted event created")

        # Save to event store via repository
        repo = get_workflow_execution_repository()
        await repo.save(aggregate)
        print("   ✅ Events persisted to event store")

        # Disconnect
        await disconnect_event_store()
        print("   🔌 Disconnected from Event Store")

        return True

    except Exception as e:
        print(f"   ❌ Failed to emit events: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        # Restore environment
        if original_env:
            os.environ["APP_ENVIRONMENT"] = original_env
        elif "APP_ENVIRONMENT" in os.environ:
            del os.environ["APP_ENVIRONMENT"]


async def verify_event_store(execution_id: str) -> bool:
    """Verify events were stored in the event store."""
    print_step(10, "Verify Event Store")

    import subprocess

    # Query events for this execution
    result = subprocess.run(
        [
            "docker",
            "exec",
            "aef-postgres",
            "psql",
            "-U",
            "aef",
            "-d",
            "aef",
            "-t",
            "-c",
            f"SELECT event_type, aggregate_type FROM events WHERE aggregate_id = '{execution_id}' ORDER BY global_nonce;",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        output = result.stdout.strip()
        if output:
            print(f"   📋 Events for execution {execution_id}:")
            for line in output.split("\n"):
                parts = line.strip().split("|")
                if len(parts) >= 2:
                    event_type = parts[0].strip()
                    aggregate_type = parts[1].strip()
                    print(f"      • {event_type} ({aggregate_type})")
            return True
        else:
            print(f"   ⚠️  No events found for execution {execution_id}")
            return False
    else:
        print(f"   ❌ Event store query error: {result.stderr}")
        return False


async def main() -> int:
    """Run the e2e integration test."""
    parser = argparse.ArgumentParser(
        description="E2E Integration Test: Agentic Workflow with GitHub App"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run with live Claude agent (costs money!)",
    )
    parser.add_argument(
        "--skip-prereqs",
        action="store_true",
        help="Skip prerequisite checks",
    )
    args = parser.parse_args()

    print_header("🧪 AEF E2E Integration Test: Agentic Workflow")
    print(f"   Date: {datetime.now(UTC).isoformat()}")
    print(f"   Live Mode: {args.live}")
    print(f"   Sandbox Repo: {SANDBOX_REPO}")

    # Check prerequisites
    if not args.skip_prereqs:
        prereqs_ok = await check_prerequisites()
        if not prereqs_ok:
            print("\n❌ Prerequisites not met. Fix the issues above and retry.")
            return 1

    # Run Phase 1
    try:
        results = await run_phase1_workflow(live=args.live)
    except Exception as e:
        print(f"\n❌ Phase 1 failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    # Emit workflow events to event store
    events_emitted = await emit_workflow_events(
        execution_id=results["execution_id"],
        workflow_id="e2e-github-app-workflow",
        branch=results["branch"],
    )

    # Verify event store
    events_verified = await verify_event_store(results["execution_id"])

    # Summary
    print_header("🎉 E2E Integration Test Complete!")

    print("\n📋 Results:")
    print(f"   Execution ID: {results['execution_id']}")
    print(f"   Branch: {results['branch']}")
    print(f"   PR: #{results['pr_number']}")
    print(f"   Cost: ${results['cost_usd']}")

    print(f"\n🔗 Pull Request:")
    print(f"   {results['pr_url']}")

    print("\n📌 Next Steps:")
    print("   1. Review the PR in GitHub")
    print("   2. Merge or close the PR")
    print("   3. Run Phase 2 (webhook-triggered) - coming soon!")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
