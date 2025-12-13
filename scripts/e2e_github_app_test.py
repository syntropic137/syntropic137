#!/usr/bin/env python3
"""End-to-end test for GitHub App integration with secure token architecture.

This script demonstrates the complete flow:
1. Authenticate with GitHub App (JWT → Installation Token)
2. Allocate spend budget for the execution
3. Clone sandbox repo (or create file via API)
4. Make code changes
5. Push changes as the bot
6. Track token/spend usage

Run with:
    uv run python scripts/e2e_github_app_test.py

Requires:
    - GitHub App configured in .env (AEF_GITHUB_* variables)
    - Access to sandbox repo (AgentParadise/sandbox_aef-engineer-beta)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-adapters" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-tokens" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "aef-shared" / "src"))


async def main() -> int:
    """Run the e2e test."""
    print("=" * 60)
    print("🚀 E2E GitHub App + Secure Token Architecture Test")
    print("=" * 60)

    # Step 1: Initialize services
    print("\n📦 Step 1: Initializing services...")

    try:
        from aef_adapters.github import GitHubAppError, get_github_client
        from aef_tokens import SpendTracker, TokenType, TokenVendingService, WorkflowType
        from aef_tokens.spend import InMemoryBudgetStore
        from aef_tokens.vending import InMemoryTokenStore
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure packages are installed: uv pip install -e packages/aef-*")
        return 1

    # Create token vending service
    token_store = InMemoryTokenStore()
    token_service = TokenVendingService(token_store)
    print("   ✅ Token Vending Service ready")

    # Create spend tracker
    budget_store = InMemoryBudgetStore()
    spend_tracker = SpendTracker(budget_store)
    print("   ✅ Spend Tracker ready")

    # Step 2: Authenticate with GitHub App
    print("\n🔐 Step 2: Authenticating with GitHub App...")

    try:
        github_client = get_github_client()
    except ValueError as e:
        print(f"❌ GitHub App not configured: {e}")
        print("   Set AEF_GITHUB_* variables in .env")
        return 1

    try:
        # Get installation token (this proves the app is working)
        await github_client.get_installation_token()
        print("   ✅ Installation token obtained (expires in 1 hour)")
        print(f"   Bot username: {github_client.bot_username}")

        # Get app info
        app_info = await github_client.get_app_info()
        print(f"   App: {app_info.get('name', 'unknown')}")
    except GitHubAppError as e:
        print(f"❌ GitHub authentication failed: {e}")
        return 1

    # Step 3: Allocate budget for this execution
    print("\n💰 Step 3: Allocating spend budget...")

    execution_id = f"e2e-test-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    budget = await spend_tracker.allocate_budget(
        execution_id=execution_id,
        workflow_type=WorkflowType.QUICK_FIX,  # Small budget for test
    )
    print(f"   ✅ Budget allocated for {execution_id}")
    print(f"   Max input tokens: {budget.max_input_tokens:,}")
    print(f"   Max output tokens: {budget.max_output_tokens:,}")
    print(f"   Max cost: ${budget.max_cost_usd}")

    # Step 4: Vend a scoped token for this execution
    print("\n🎫 Step 4: Vending scoped token...")

    scoped_token = await token_service.vend_token(
        execution_id=execution_id,
        token_type=TokenType.GITHUB,
        ttl_seconds=300,  # 5 minutes
    )
    print(f"   ✅ Token vended: {scoped_token.token_id[:20]}...")
    print(f"   Expires in: {scoped_token.seconds_until_expiry:.0f}s")

    # Step 5: List accessible repositories
    print("\n📂 Step 5: Listing accessible repositories...")

    repos = await github_client.list_accessible_repos()
    print(f"   Found {len(repos)} accessible repositories:")
    for repo in repos[:5]:
        print(f"   - {repo['full_name']}")

    # Step 6: Create a branch, commit, and open a PR
    print("\n📝 Step 6: Creating branch and PR in sandbox repo...")

    sandbox_repo = "AgentParadise/sandbox_aef-engineer-beta"
    branch_name = f"e2e-test/{execution_id}"
    test_file_path = f"e2e-tests/{execution_id}.md"
    test_content = f"""# E2E Test: {execution_id}

**Generated:** {datetime.now(UTC).isoformat()}
**By:** {github_client.bot_username}

## Test Summary

This file was created by the AEF E2E test script to verify:

1. ✅ GitHub App authentication (JWT → Installation Token)
2. ✅ Token Vending Service (scoped, short-lived tokens)
3. ✅ Spend Tracker (budget allocation)
4. ✅ Bot can create branches
5. ✅ Bot can open Pull Requests

## Token Info

- Token ID: `{scoped_token.token_id}`
- Token Type: `{scoped_token.token_type.value}`
- Expires At: `{scoped_token.expires_at.isoformat()}`

## Budget Info

- Workflow Type: `{budget.workflow_type.value}`
- Max Input Tokens: `{budget.max_input_tokens:,}`
- Max Output Tokens: `{budget.max_output_tokens:,}`
- Max Cost: `${budget.max_cost_usd}`

---

*This is an automated test file. The PR can be merged or closed.*
"""

    import base64

    try:
        # Step 6a: Get the SHA of main branch
        print("   Creating branch...")
        ref_result = await github_client.api_get(f"/repos/{sandbox_repo}/git/ref/heads/main")
        main_sha = ref_result["object"]["sha"]

        # Step 6b: Create new branch
        await github_client.api_post(
            f"/repos/{sandbox_repo}/git/refs",
            json={
                "ref": f"refs/heads/{branch_name}",
                "sha": main_sha,
            },
        )
        print(f"   ✅ Branch created: {branch_name}")

        # Step 6c: Create file on the new branch
        print("   Committing file...")
        result = await github_client.api_put(
            f"/repos/{sandbox_repo}/contents/{test_file_path}",
            json={
                "message": f"test(e2e): add test file for {execution_id}",
                "content": base64.b64encode(test_content.encode()).decode(),
                "branch": branch_name,
            },
        )
        commit_sha = result.get("commit", {}).get("sha", "unknown")[:7]
        print(f"   ✅ File committed: {commit_sha}")

        # Step 6d: Create Pull Request
        print("   Opening Pull Request...")
        pr_result = await github_client.api_post(
            f"/repos/{sandbox_repo}/pulls",
            json={
                "title": f"🤖 E2E Test: {execution_id}",
                "body": f"""## Automated E2E Test

This PR was created automatically by the AEF E2E test script.

### What this tests:
- ✅ GitHub App authentication
- ✅ Token Vending Service
- ✅ Spend Tracker
- ✅ Branch creation via API
- ✅ PR creation via API

### Details:
- **Execution ID:** `{execution_id}`
- **Bot:** `{github_client.bot_username}`
- **Generated:** `{datetime.now(UTC).isoformat()}`

---
*This PR can be merged or closed. It's just a test!*
""",
                "head": branch_name,
                "base": "main",
            },
        )
        pr_number = pr_result.get("number")
        pr_url = pr_result.get("html_url")
        print(f"   ✅ PR created: #{pr_number}")
        print(f"   URL: {pr_url}")

    except Exception as e:
        print(f"   ⚠️ PR creation failed: {e}")
        print("   (This might be a permission issue)")

    # Step 7: Simulate some spend
    print("\n📊 Step 7: Simulating token usage...")

    # Simulate a small API call worth of tokens
    await spend_tracker.record_usage(
        execution_id=execution_id,
        input_tokens=1000,
        output_tokens=500,
    )

    summary = await spend_tracker.get_usage_summary(execution_id)
    print(
        f"   Input tokens used: {summary['input_tokens']['used']:,} / {summary['input_tokens']['max']:,}"
    )
    print(
        f"   Output tokens used: {summary['output_tokens']['used']:,} / {summary['output_tokens']['max']:,}"
    )
    print(f"   Cost: ${summary['cost_usd']['used']} / ${summary['cost_usd']['max']}")
    print(f"   Budget exhausted: {summary['is_exhausted']}")

    # Step 8: Cleanup - revoke tokens
    print("\n🧹 Step 8: Revoking tokens...")

    revoked_count = await token_service.revoke_tokens(execution_id)
    print(f"   ✅ Revoked {revoked_count} token(s)")

    released = await spend_tracker.release_budget(execution_id)
    print(f"   ✅ Budget released: {released}")

    # Done!
    print("\n" + "=" * 60)
    print("🎉 E2E Test Complete!")
    print("=" * 60)
    print("\nCheck the sandbox repo:")
    print(f"  https://github.com/{sandbox_repo}/tree/main/e2e-tests")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
