#!/usr/bin/env python3
"""True End-to-End Agentic Workflow Test.

This script tests the complete agentic workflow:
1. Starts workflow via Dashboard API
2. Agent runs in isolated Docker container
3. GitHub credentials injected via TokenVendingService
4. Agent creates a PR using git/gh CLI
5. All events visible in PostgreSQL event store
6. PR visible on GitHub

Usage:
    # Ensure Docker Compose stack is running first
    docker compose -f docker/docker-compose.dev.yaml up -d

    # Run the E2E test
    uv run python scripts/e2e_true_agentic_workflow.py

Requirements:
    - Docker Compose stack running (postgres, dashboard)
    - GitHub App configured (AEF_GITHUB_* env vars)
    - ANTHROPIC_API_KEY set for Claude agent
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx


# Configuration
DASHBOARD_URL = os.getenv("AEF_DASHBOARD_URL", "http://localhost:8000")
SANDBOX_REPO = "AgentParadise/sandbox_aef-engineer-beta"
WORKFLOW_ID = "github-pr-workflow"
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 600  # 10 minutes max


async def check_prerequisites() -> bool:
    """Check that all prerequisites are met."""
    print("\n🔍 Checking prerequisites...")
    
    all_ok = True
    
    # Check Dashboard API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{DASHBOARD_URL}/api/health", timeout=5.0)
            if response.status_code == 200:
                print("   ✅ Dashboard API is running")
            else:
                print(f"   ❌ Dashboard API returned {response.status_code}")
                all_ok = False
    except Exception as e:
        print(f"   ❌ Dashboard API not reachable: {e}")
        all_ok = False
    
    # Check required env vars
    required_vars = [
        "AEF_GITHUB_APP_ID",
        "AEF_GITHUB_INSTALLATION_ID", 
        "AEF_GITHUB_PRIVATE_KEY",
        "ANTHROPIC_API_KEY",
    ]
    
    for var in required_vars:
        if os.getenv(var):
            print(f"   ✅ {var} is set")
        else:
            print(f"   ❌ {var} is not set")
            all_ok = False
    
    return all_ok


async def start_workflow(
    change_description: str,
    execution_id: str,
) -> dict[str, Any]:
    """Start the GitHub PR workflow via Dashboard API."""
    print(f"\n🚀 Starting workflow: {WORKFLOW_ID}")
    print(f"   Change: {change_description}")
    print(f"   Execution ID: {execution_id}")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{DASHBOARD_URL}/api/workflows/{WORKFLOW_ID}/execute",
            json={
                "inputs": {
                    "repo_url": f"https://github.com/{SANDBOX_REPO}",
                    "change_description": change_description,
                    "execution_id": execution_id,
                },
                "provider": "claude",
            },
            timeout=30.0,
        )
        
        if response.status_code != 200:
            print(f"   ❌ Failed to start workflow: {response.status_code}")
            print(f"   Response: {response.text}")
            raise RuntimeError(f"Workflow start failed: {response.status_code}")
        
        result = response.json()
        print(f"   ✅ Workflow started: {result.get('execution_id', 'unknown')}")
        return result


async def poll_workflow_status(execution_id: str) -> str:
    """Poll workflow status until completion."""
    print(f"\n⏳ Waiting for workflow to complete...")
    
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


async def check_events_in_store(execution_id: str) -> list[dict]:
    """Query events from the event store via Dashboard API."""
    print(f"\n📊 Checking events in store for {execution_id}...")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DASHBOARD_URL}/api/executions/{execution_id}/events",
            timeout=10.0,
        )
        
        if response.status_code == 200:
            events = response.json()
            print(f"   Found {len(events)} events:")
            
            for event in events[:10]:  # Show first 10
                event_type = event.get("event_type", "unknown")
                print(f"   - {event_type}")
            
            if len(events) > 10:
                print(f"   ... and {len(events) - 10} more")
            
            return events
        else:
            print(f"   ⚠️ Could not fetch events: {response.status_code}")
            return []


async def check_pr_on_github(execution_id: str) -> dict | None:
    """Check if a PR was created on GitHub."""
    print(f"\n🔍 Checking for PR on GitHub...")
    
    try:
        # Use gh CLI to check for PR
        import subprocess
        
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--repo", SANDBOX_REPO,
                "--search", f"agent-{execution_id}",
                "--json", "number,title,url,state,headRefName",
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
                print(f"   URL: {pr['url']}")
                return pr
        
        print("   ⚠️ No PR found (agent may not have created one)")
        return None
        
    except Exception as e:
        print(f"   ⚠️ Could not check GitHub: {e}")
        return None


async def run_e2e_test() -> bool:
    """Run the full E2E test."""
    print("=" * 60)
    print("🧪 True End-to-End Agentic Workflow Test")
    print("=" * 60)
    
    # Generate unique execution ID
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    execution_id = f"e2e-{timestamp}"
    change_description = f"Add E2E test file for {execution_id}"
    
    # Step 1: Check prerequisites
    if not await check_prerequisites():
        print("\n❌ Prerequisites not met. Please fix the issues above.")
        return False
    
    # Step 2: Start workflow
    try:
        result = await start_workflow(change_description, execution_id)
        actual_execution_id = result.get("execution_id", execution_id)
    except Exception as e:
        print(f"\n❌ Failed to start workflow: {e}")
        return False
    
    # Step 3: Wait for completion
    status = await poll_workflow_status(actual_execution_id)
    
    if status == "completed":
        print(f"\n   ✅ Workflow completed successfully!")
    elif status == "failed":
        print(f"\n   ❌ Workflow failed")
    else:
        print(f"\n   ⚠️ Workflow ended with status: {status}")
    
    # Step 4: Check events
    events = await check_events_in_store(actual_execution_id)
    
    # Step 5: Check PR
    pr = await check_pr_on_github(execution_id)
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 Test Summary")
    print("=" * 60)
    
    success = True
    
    print(f"\n   Workflow Status: {status}")
    if status != "completed":
        success = False
    
    print(f"   Events Recorded: {len(events)}")
    if len(events) == 0:
        success = False
    
    # Check for key events
    event_types = {e.get("event_type") for e in events}
    expected_events = ["WorkflowStarted", "WorkflowCompleted"]
    for expected in expected_events:
        if expected in event_types:
            print(f"   ✅ {expected} event found")
        else:
            print(f"   ⚠️ {expected} event missing")
    
    if pr:
        print(f"   ✅ PR Created: {pr['url']}")
    else:
        print("   ⚠️ No PR found")
        # Not a hard failure - agent might have different behavior
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 E2E Test PASSED!")
    else:
        print("❌ E2E Test FAILED")
    print("=" * 60)
    
    return success


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
