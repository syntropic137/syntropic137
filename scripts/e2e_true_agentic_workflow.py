#!/usr/bin/env python3
"""True End-to-End Agentic Workflow Test with Direct DB Validation.

This script tests the complete agentic workflow:
1. Validates prerequisites (DB, API, env vars, Docker)
2. Starts workflow via Dashboard API
3. Agent runs in isolated Docker container
4. GitHub credentials injected via TokenVendingService
5. Agent creates a PR using git/gh CLI
6. Validates events DIRECTLY in PostgreSQL (not via API)
7. PR visible on GitHub

Usage:
    # Ensure Docker Compose stack is running first
    docker compose -f docker/docker-compose.dev.yaml up -d

    # Run the E2E test
    uv run python scripts/e2e_true_agentic_workflow.py

Requirements:
    - Docker Compose stack running (postgres, dashboard)
    - GitHub App configured (SYN_GITHUB_* env vars)
    - ANTHROPIC_API_KEY set for Claude agent
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

# Configuration
DASHBOARD_URL = os.getenv("SYN_DASHBOARD_URL", "http://localhost:8000")
SANDBOX_REPO = "syntropic137/sandbox_syn-engineer-beta"
# Use research workflow which is already registered
# github-pr-workflow requires event-based registration (future)
WORKFLOW_ID = os.getenv("SYN_E2E_WORKFLOW_ID", "research-workflow-v2")
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 600  # 10 minutes max

# PostgreSQL connection (via docker exec)
POSTGRES_CONTAINER = os.getenv("SYN_POSTGRES_CONTAINER", "syn-db")
POSTGRES_USER = "syn"
POSTGRES_DB = "syn"


def run_psql(query: str) -> tuple[bool, str]:
    """Run a PostgreSQL query via docker exec."""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                POSTGRES_CONTAINER,
                "psql",
                "-U",
                POSTGRES_USER,
                "-d",
                POSTGRES_DB,
                "-t",
                "-A",  # Tuples only, unaligned
                "-c",
                query,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


async def check_prerequisites() -> bool:
    """Check that all prerequisites are met."""
    print("\n🔍 Checking prerequisites...")

    all_ok = True

    # Check Docker is running
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("   ✅ Docker is running")
        else:
            print("   ❌ Docker is not running")
            all_ok = False
    except Exception as e:
        print(f"   ❌ Docker check failed: {e}")
        all_ok = False

    # Check PostgreSQL is reachable
    ok, output = run_psql("SELECT 1;")
    if ok and output == "1":
        print("   ✅ PostgreSQL is reachable")
    else:
        print(f"   ❌ PostgreSQL not reachable: {output}")
        all_ok = False

    # Check events table exists and has data
    ok, output = run_psql("SELECT COUNT(*) FROM events LIMIT 1;")
    if ok:
        print(f"   ✅ Events table exists ({output} total events)")
    else:
        print(f"   ❌ Events table check failed: {output}")
        all_ok = False

    # Check Dashboard API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{DASHBOARD_URL}/health", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Dashboard API is running (status: {data.get('status', 'ok')})")
            else:
                print(f"   ❌ Dashboard API returned {response.status_code}")
                all_ok = False
    except Exception as e:
        print(f"   ❌ Dashboard API not reachable: {e}")
        all_ok = False

    # Check required env vars
    # Note: GitHub vars only required for github workflows
    # The Dashboard process has these set, we just verify connectivity
    is_github_workflow = "github" in WORKFLOW_ID.lower() or "pr" in WORKFLOW_ID.lower()

    required_vars = [("ANTHROPIC_API_KEY", "Anthropic API Key", True)]  # Always required

    if is_github_workflow:
        required_vars.extend(
            [
                ("SYN_GITHUB_APP_ID", "GitHub App ID", True),
                ("SYN_GITHUB_INSTALLATION_ID", "GitHub Installation ID", True),
                ("SYN_GITHUB_PRIVATE_KEY", "GitHub Private Key", True),
            ]
        )

    for var, desc, required in required_vars:
        if os.getenv(var):
            # Mask sensitive values
            val = os.getenv(var, "")
            if "KEY" in var or "PRIVATE" in var:
                display = f"{val[:10]}..." if len(val) > 10 else "***"
            else:
                display = val[:20] if len(val) > 20 else val
            print(f"   ✅ {var} = {display}")
        else:
            if required:
                print(f"   ⚠️ {var} ({desc}) not set in test env")
                print("      (Dashboard may have it, continuing...)")
            else:
                print(f"   ⚠️ {var} ({desc}) is not set (optional)")
            # Don't fail - Dashboard process may have these

    return all_ok


async def start_workflow(
    topic: str,
    execution_id: str,
) -> dict[str, Any]:
    """Start the workflow via Dashboard API."""
    print(f"\n🚀 Starting workflow: {WORKFLOW_ID}")
    print(f"   Topic: {topic}")
    print(f"   Execution ID: {execution_id}")

    # Build inputs based on workflow type
    if "github" in WORKFLOW_ID.lower() or "pr" in WORKFLOW_ID.lower():
        inputs = {
            "repo_url": f"https://github.com/{SANDBOX_REPO}",
            "change_description": topic,
            "execution_id": execution_id,
        }
    else:
        # Research workflow uses 'topic'
        inputs = {"topic": topic}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{DASHBOARD_URL}/api/workflows/{WORKFLOW_ID}/execute",
            json={
                "inputs": inputs,
                "provider": "claude",
            },
            timeout=30.0,
        )

        if response.status_code not in (200, 201, 202):
            print(f"   ❌ Failed to start workflow: {response.status_code}")
            print(f"   Response: {response.text}")
            raise RuntimeError(f"Workflow start failed: {response.status_code}")

        result = response.json()
        print(f"   ✅ Workflow started: {result.get('execution_id', 'unknown')}")
        return result


async def poll_workflow_status(execution_id: str) -> str:
    """Poll workflow status until completion."""
    print("\n⏳ Waiting for workflow to complete...")

    start_time = time.time()
    last_status = None

    async with httpx.AsyncClient() as client:
        while True:
            elapsed = time.time() - start_time
            if elapsed > MAX_WAIT_SECONDS:
                print(f"   ❌ Workflow timed out after {MAX_WAIT_SECONDS}s")
                return "timeout"

            try:
                response = await client.get(
                    f"{DASHBOARD_URL}/api/executions/{execution_id}",
                    timeout=10.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status", "unknown")

                    if status != last_status:
                        print(f"   Status: {status} ({int(elapsed)}s elapsed)")
                        last_status = status

                    if status in ("completed", "failed", "cancelled"):
                        return status

            except Exception as e:
                print(f"   ⚠️ Poll error: {e}")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def validate_events_in_db(session_id: str) -> dict[str, Any]:
    """Query and validate events DIRECTLY from PostgreSQL."""
    print(f"\n📊 Validating events in PostgreSQL for session {session_id}...")

    result = {
        "total_events": 0,
        "event_types": [],
        "checks": [],
        "passed": True,
    }

    # Query all events for this session
    query = f"""
    SELECT event_type, aggregate_type, global_nonce
    FROM events
    WHERE correlation_id = '{session_id}'
       OR aggregate_id LIKE '%{session_id}%'
    ORDER BY global_nonce ASC;
    """

    ok, output = run_psql(query)
    if not ok:
        print(f"   ❌ Failed to query events: {output}")
        result["passed"] = False
        result["checks"].append({"name": "query_events", "passed": False, "error": output})
        return result

    # Parse events
    events = []
    if output:
        for line in output.strip().split("\n"):
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 3:
                    events.append(
                        {
                            "event_type": parts[0],
                            "aggregate_type": parts[1],
                            "global_nonce": int(parts[2]) if parts[2].isdigit() else 0,
                        }
                    )

    result["total_events"] = len(events)
    result["event_types"] = [e["event_type"] for e in events]

    print(f"   Found {len(events)} events in database")

    # Check 1: Has any events
    if len(events) > 0:
        print(f"   ✅ Events found in database: {len(events)}")
        result["checks"].append({"name": "has_events", "passed": True})
    else:
        print("   ❌ No events found in database")
        result["checks"].append({"name": "has_events", "passed": False})
        result["passed"] = False

    # Check 2: Event types present
    event_type_set = set(result["event_types"])

    # Event types use "WorkflowExecution*" pattern, not "Workflow*"
    expected_types = [
        ("WorkflowExecutionStarted", "Workflow lifecycle"),
        ("WorkflowCompleted", "Workflow lifecycle (optional - may still be running)"),
    ]

    for event_type, description in expected_types:
        if event_type in event_type_set:
            print(f"   ✅ {event_type} event present ({description})")
            result["checks"].append({"name": f"has_{event_type}", "passed": True})
        else:
            print(f"   ⚠️ {event_type} event missing ({description})")
            result["checks"].append({"name": f"has_{event_type}", "passed": False})
            # Not a hard failure for some events

    # Check 3: Event sequence (global_nonce should be monotonic)
    if len(events) >= 2:
        nonces = [e["global_nonce"] for e in events]
        is_monotonic = all(nonces[i] < nonces[i + 1] for i in range(len(nonces) - 1))
        if is_monotonic:
            print("   ✅ Event sequence is valid (monotonic global_nonce)")
            result["checks"].append({"name": "monotonic_sequence", "passed": True})
        else:
            print("   ❌ Event sequence is invalid (non-monotonic global_nonce)")
            result["checks"].append({"name": "monotonic_sequence", "passed": False})
            result["passed"] = False

    # Show event types found
    unique_types = list(dict.fromkeys(result["event_types"]))  # Preserve order
    print(f"   Event types: {', '.join(unique_types[:10])}")
    if len(unique_types) > 10:
        print(f"   ... and {len(unique_types) - 10} more types")

    return result


def validate_agent_events_in_db(session_id: str) -> dict[str, Any]:
    """Validate observability events in agent_events table.

    This is CRITICAL - validates the observability pipeline that feeds the UI.
    The agent_events table receives events from hooks (tool_started, tool_completed, etc.)
    and is queried by SessionToolsProjection for the UI.

    If this fails, the UI will show no tool operations even if the workflow succeeded.
    """
    print(f"\n📊 Validating agent_events (observability) for session {session_id}...")

    result = {
        "total_events": 0,
        "event_types": {},
        "checks": [],
        "passed": True,
    }

    # Query event counts by type
    query = f"""
    SELECT event_type, count(*)
    FROM agent_events
    WHERE session_id = '{session_id}'
    GROUP BY event_type
    ORDER BY count(*) DESC;
    """

    ok, output = run_psql(query)
    if not ok:
        print(f"   ❌ Failed to query agent_events: {output}")
        result["passed"] = False
        result["checks"].append({"name": "query_agent_events", "passed": False, "error": output})
        return result

    # Parse results
    if output:
        for line in output.strip().split("\n"):
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    event_type = parts[0].strip()
                    count = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
                    result["event_types"][event_type] = count
                    result["total_events"] += count

    print(f"   Found {result['total_events']} total events in agent_events")

    # Check 1: Has any events
    if result["total_events"] > 0:
        print(f"   ✅ Events found in agent_events: {result['total_events']}")
        result["checks"].append({"name": "has_agent_events", "passed": True})
    else:
        print("   ❌ No events found in agent_events table!")
        print("   This means the observability pipeline is broken.")
        print("   UI will show no tool operations.")
        result["checks"].append({"name": "has_agent_events", "passed": False})
        result["passed"] = False
        return result

    # Check 2: Required event types for observability
    # These are the events the UI needs to show tool operations
    # MUST match agentic_events.EventType (the producer)
    required_types = {
        "tool_execution_started": "Tool operations - shows what agent is doing",
        "tool_execution_completed": "Tool results - shows outcomes",
    }

    optional_types = {
        "token_usage": "Cost tracking",
        "session_started": "Session lifecycle",
        "session_completed": "Session lifecycle",
    }

    for event_type, description in required_types.items():
        if event_type in result["event_types"]:
            count = result["event_types"][event_type]
            print(f"   ✅ {event_type}: {count} events ({description})")
            result["checks"].append({"name": f"has_{event_type}", "passed": True, "count": count})
        else:
            print(f"   ❌ {event_type}: MISSING ({description})")
            result["checks"].append({"name": f"has_{event_type}", "passed": False})
            result["passed"] = False

    for event_type, description in optional_types.items():
        if event_type in result["event_types"]:
            count = result["event_types"][event_type]
            print(f"   ✅ {event_type}: {count} events ({description})")
        else:
            print(f"   ⚠️ {event_type}: not found ({description})")

    # Show all event types found
    print(f"   Event breakdown: {result['event_types']}")

    return result


def check_pr_on_github(execution_id: str) -> dict | None:
    """Check if a PR was created on GitHub."""
    print("\n🐙 Checking for PR on GitHub...")

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                SANDBOX_REPO,
                "--search",
                f"agent-{execution_id}",
                "--json",
                "number,title,url,state,headRefName,author",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0 and result.stdout.strip():
            prs = json.loads(result.stdout)
            if prs:
                pr = prs[0]
                print(f"   ✅ PR found: #{pr['number']}")
                print(f"   Title: {pr['title']}")
                print(f"   Branch: {pr['headRefName']}")
                print(f"   Author: {pr.get('author', {}).get('login', 'unknown')}")
                print(f"   URL: {pr['url']}")
                return pr

        print("   ⚠️ No PR found (agent may not have created one)")
        return None

    except FileNotFoundError:
        print("   ⚠️ gh CLI not installed, skipping PR check")
        return None
    except Exception as e:
        print(f"   ⚠️ Could not check GitHub: {e}")
        return None


def check_branch_on_github(execution_id: str) -> bool:
    """Check if a branch was created on GitHub."""
    print("\n🌿 Checking for branch on GitHub...")

    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{SANDBOX_REPO}/branches",
                "--jq",
                f'.[].name | select(contains("agent-{execution_id}"))',
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0 and result.stdout.strip():
            branches = result.stdout.strip().split("\n")
            print(f"   ✅ Branch found: {branches[0]}")
            return True

        print("   ⚠️ No matching branch found")
        return False

    except Exception as e:
        print(f"   ⚠️ Could not check branches: {e}")
        return False


async def run_e2e_test() -> bool:
    """Run the full E2E test with direct DB validation."""
    print("=" * 70)
    print("🧪 TRUE END-TO-END AGENTIC WORKFLOW TEST")
    print("   With Direct PostgreSQL Validation")
    print("=" * 70)

    # Generate unique execution ID
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    execution_id = f"e2e-{timestamp}"
    topic = f"E2E validation test for AEF workflow system - execution {execution_id}"

    # Step 1: Check prerequisites
    if not await check_prerequisites():
        print("\n❌ Prerequisites not met. Please fix the issues above.")
        return False

    # Step 2: Start workflow
    try:
        result = await start_workflow(topic, execution_id)
        session_id = result.get("session_id") or result.get("execution_id") or execution_id
    except Exception as e:
        print(f"\n❌ Failed to start workflow: {e}")
        return False

    # Step 3: Wait for completion
    status = await poll_workflow_status(session_id)

    if status == "completed":
        print("\n   ✅ Workflow completed successfully!")
    elif status == "failed":
        print("\n   ❌ Workflow failed")
    else:
        print(f"\n   ⚠️ Workflow ended with status: {status}")

    # Step 4: Validate events DIRECTLY in PostgreSQL
    event_validation = validate_events_in_db(session_id)

    # Step 4b: Validate observability events (CRITICAL for UI)
    # This validates the agent_events table that feeds the UI
    agent_events_validation = validate_agent_events_in_db(session_id)

    # Step 5 & 6: Check GitHub (only for github/pr workflows)
    is_github_workflow = "github" in WORKFLOW_ID.lower() or "pr" in WORKFLOW_ID.lower()
    branch_found = False
    pr = None

    if is_github_workflow:
        branch_found = check_branch_on_github(execution_id)
        pr = check_pr_on_github(execution_id)
    else:
        print("\n📝 Skipping GitHub checks (not a GitHub workflow)")

    # ==================== SUMMARY ====================
    print("\n" + "=" * 70)
    print("📋 TEST SUMMARY")
    print("=" * 70)

    checks_passed = 0
    checks_failed = 0
    checks_warning = 0

    # Workflow status
    print(f"\n   Workflow Status: {status}")
    if status == "completed":
        checks_passed += 1
    else:
        checks_failed += 1

    # Event validation (event sourcing)
    print(f"\n   Events in Database: {event_validation['total_events']}")
    if event_validation["passed"]:
        checks_passed += 1
    else:
        checks_failed += 1

    # Agent events validation (observability - CRITICAL for UI)
    print(f"\n   Agent Events (Observability): {agent_events_validation['total_events']}")
    if agent_events_validation["passed"]:
        checks_passed += 1
        print("   ✅ Observability pipeline working - UI will show tool operations")
    else:
        checks_failed += 1
        print("   ❌ OBSERVABILITY BROKEN - UI will not show tool operations!")
        print("   This is the bug we spent $100 debugging.")

    # Show tool event breakdown if available
    if agent_events_validation.get("event_types"):
        tool_started = agent_events_validation["event_types"].get("tool_execution_started", 0)
        tool_completed = agent_events_validation["event_types"].get("tool_execution_completed", 0)
        print(f"   Tool events: {tool_started} started, {tool_completed} completed")

    for check in event_validation["checks"]:
        if check["passed"]:
            print(f"   ✅ {check['name']}")
            checks_passed += 1
        else:
            # WorkflowCompleted missing is OK if status is timeout (still running)
            if check["name"] == "has_WorkflowCompleted" and status == "timeout":
                print(f"   ⚠️ {check['name']} (workflow may still be running)")
                checks_warning += 1
            elif check["name"] in ("has_events", "monotonic_sequence"):
                print(f"   ❌ {check['name']}")
                checks_failed += 1
            else:
                print(f"   ⚠️ {check['name']}")
                checks_warning += 1

    # GitHub checks (only for github workflows)
    if is_github_workflow:
        print()
        if branch_found:
            print("   ✅ Branch created on GitHub")
            checks_passed += 1
        else:
            print("   ⚠️ Branch not found on GitHub")
            checks_warning += 1

        if pr:
            print(f"   ✅ PR created: {pr['url']}")
            checks_passed += 1
        else:
            print("   ⚠️ No PR found on GitHub")
            checks_warning += 1

    # Final verdict
    print("\n" + "-" * 70)
    print(f"   ✅ Passed:   {checks_passed}")
    print(f"   ❌ Failed:   {checks_failed}")
    print(f"   ⚠️ Warnings: {checks_warning}")
    print("-" * 70)

    success = checks_failed == 0

    print("\n" + "=" * 70)
    if success:
        print("🎉 E2E TEST PASSED!")
    else:
        print("❌ E2E TEST FAILED")
    print("=" * 70)

    # Print useful links
    if pr:
        print(f"\n📎 PR: {pr['url']}")
    print(f"📎 Dashboard: {DASHBOARD_URL}/executions/{session_id}")

    return success


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
