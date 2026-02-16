# GitHub App Setup Guide

This guide walks you through setting up a GitHub App for secure agent commits in AEF.

## Why Use a GitHub App?

| Approach | Token Lifetime | Audit Trail | Security |
|----------|----------------|-------------|----------|
| Personal Access Token | 30-90 days | User | ⚠️ Long-lived |
| **GitHub App** | **1 hour** | **Bot** | **✅ Auto-rotating** |

GitHub Apps provide:
- **Short-lived tokens**: Installation tokens expire after 1 hour
- **Clear attribution**: Commits show as `aef-agent[bot]` not a personal account
- **Fine-grained permissions**: Request only what's needed
- **Organization-level control**: Admins can manage app access centrally
- **Self-healing capabilities**: Read CI logs, respond to PR reviews, fix issues automatically

## Quick Start: Manifest Flow (Recommended)

The easiest way to create a GitHub App is the **manifest flow** — one click and all
permissions, events, and credentials are configured automatically.

```bash
# During full setup (includes GitHub App creation):
just setup

# Or run only the GitHub App stage:
python infra/scripts/setup.py --stage configure_github_app

# Or run the manifest flow standalone:
python infra/scripts/github_manifest.py
```

When you choose **"new"**, the setup wizard will:

1. Open your browser to GitHub with all permissions pre-filled
2. You click **"Create GitHub App"** — one click
3. GitHub redirects back to the setup wizard automatically
4. The wizard saves the private key, webhook secret, and app credentials
5. You install the app on your repositories
6. The Installation ID is **detected automatically** via the setup callback — no copy-paste needed

All permissions, webhook events, and secrets are handled automatically — no
manual field entry required.

> **Reconfiguring later**: To change repositories, permissions, or recreate the
> app at any time, run `just github-reconfigure`.

> **Note on the Workflows permission**: The manifest flow does **not** request
> `workflows: write` by default because it allows modifying GitHub Actions
> workflow files (`.github/workflows/*.yml`). If your agent needs to create or
> edit workflow files, add `"workflows": "write"` to the manifest permissions
> in `infra/scripts/github_manifest.py` and ensure branch protection rules
> require PR reviews for workflow changes.

---

## Manual Setup

If you prefer to create the GitHub App manually (or need to configure an
existing app), choose **"existing"** during `just setup` and follow the
steps below.

### Step 1: Create the GitHub App

#### For Organizations (Recommended)

If you have an organization (e.g., `AgentParadise`), create the app through the org:

1. Go to **https://github.com/organizations/YOUR_ORG/settings/apps**
2. Click **New GitHub App**

#### For Personal Accounts

1. Go to [GitHub Settings > Developer settings > GitHub Apps](https://github.com/settings/apps)
2. Click **New GitHub App**

#### Basic Information

Fill in the app details:
- **GitHub App name**: `aef-agent` (or your preferred name, e.g., `agentparadise-bot`)
- **Homepage URL**: Your organization's URL (e.g., `https://github.com/AgentParadise`)
- **Webhook URL**: `https://your-domain.com/webhooks/github` (can leave blank for local dev)
- **Webhook secret**: Generate a strong random secret (e.g., `openssl rand -hex 32`)

#### Repository Permissions

Set these permissions for full agentic capabilities:

| Permission | Access | Why |
|------------|--------|-----|
| **Contents** | Read & Write | Push commits, read code, create branches |
| **Pull requests** | Read & Write | Create PRs, read/write review comments |
| **Actions** | Read-only | Read workflow runs, logs, artifacts for self-healing |
| **Checks** | Read & Write | Read check results, create check runs |
| **Commit statuses** | Read & Write | Set status checks on commits |
| **Issues** | Read & Write | Create/update issues from agent findings |
| **Metadata** | Read-only | Required for all GitHub Apps |

#### Subscribe to Events

Enable these webhook events for real-time notifications and full auditability.

#### Required Events (Self-Healing & CI)

| Event | Why | Triggers |
|-------|-----|----------|
| **Workflow run** | CI/CD lifecycle | `requested`, `completed` - **self-healing trigger** |
| **Workflow job** | Individual job tracking | `queued`, `in_progress`, `completed` |
| **Check run** | Check status | `created`, `completed`, `rerequested` |
| **Check suite** | Suite completion | `completed`, `rerequested` |

#### Required Events (Pull Requests)

| Event | Why | Triggers |
|-------|-----|----------|
| **Pull request** | PR lifecycle | `opened`, `closed`, `merged`, `synchronize`, `edited` |
| **Pull request review** | Review submitted | `submitted`, `edited`, `dismissed` |
| **Pull request review comment** | Line comments | `created`, `edited`, `deleted` - **Copilot feedback!** |
| **Pull request review thread** | Thread resolution | `resolved`, `unresolved` |

#### Required Events (Code & Commits)

| Event | Why | Triggers |
|-------|-----|----------|
| **Push** | Code pushed | Branch/tag pushes |
| **Commit comment** | Commit discussions | `created`, `edited`, `deleted` |
| **Status** | Commit status | External status updates |
| **Create** | Branch/tag created | New refs |
| **Delete** | Branch/tag deleted | Deleted refs |

#### Required Events (Issues & Labels)

| Event | Why | Triggers |
|-------|-----|----------|
| **Issues** | Issue lifecycle | `opened`, `closed`, `edited`, `labeled` |
| **Issue comment** | Issue discussions | `created`, `edited`, `deleted` |
| **Label** | Label management | `created`, `edited`, `deleted` |

#### Automatic Events (No Checkbox Needed)

These events are **automatically subscribed** for all GitHub Apps - they won't appear in the checkbox list:

| Event | Why | Triggers |
|-------|-----|----------|
| **Installation** | App lifecycle | `created`, `deleted`, `suspend`, `unsuspend` |
| **Installation repositories** | Repo access | `added`, `removed` |

#### Optional Events (Repository & Misc)

| Event | Why | Triggers |
|-------|-----|----------|
| **Repository** | Repo settings | `created`, `deleted`, `archived`, `renamed` |
| **Installation target** | Account renamed | Only if you need to track org/user renames |

#### Quick Checklist

When creating your GitHub App, check these events in the UI:

```
Subscribe to events (check these boxes):
  ☑️ Check run
  ☑️ Check suite
  ☑️ Commit comment
  ☑️ Create
  ☑️ Delete
  ☑️ Issue comment
  ☑️ Issues
  ☑️ Label
  ☑️ Pull request
  ☑️ Pull request review
  ☑️ Pull request review comment
  ☑️ Pull request review thread
  ☑️ Push
  ☑️ Repository
  ☑️ Status
  ☑️ Workflow job
  ☑️ Workflow run

Automatic (no checkbox, always received):
  ✅ Installation
  ✅ Installation repositories
```

> **Note:** All webhook events are captured as domain events for auditability, analytics, and debugging. You can query "show me all events for PR #123" or "how many CI failures this week?"

#### Installation Scope

Choose where the app can be installed:
- **Only on this account**: For your org only
- **Any account**: If you want others to install it

Click **Create GitHub App**

### Step 2: Generate Private Key

1. After creating the app, scroll down to "Private keys"
2. Click **Generate a private key**
3. Save the downloaded `.pem` file securely
4. **NEVER commit this file to git!**

### Step 3: Install the App

1. Go to your GitHub App's page
2. Click **Install App** in the left sidebar
3. Choose the account/organization
4. Select repositories:
   - **All repositories**: Full access
   - **Only select repositories**: Choose specific repos
5. Click **Install**
6. Note the Installation ID from the URL: `https://github.com/settings/installations/[INSTALLATION_ID]`

### Step 4: Configure Environment Variables

Set these environment variables in your deployment:

```bash
# Required: GitHub App credentials
AEF_GITHUB_APP_ID=123456                    # From app settings page
AEF_GITHUB_APP_NAME=aef-app                  # Your app's slug
AEF_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
...your private key content...
-----END RSA PRIVATE KEY-----"
AEF_GITHUB_INSTALLATION_ID=12345678         # From installation URL

# Optional: Webhook security
AEF_GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

#### For Docker/Kubernetes

When using Docker or Kubernetes, you may need to handle the multi-line private key specially:

```yaml
# docker-compose.yaml
services:
  aef-dashboard:
    environment:
      - AEF_GITHUB_APP_ID=123456
      - AEF_GITHUB_PRIVATE_KEY_FILE=/run/secrets/github_private_key
    secrets:
      - github_private_key

secrets:
  github_private_key:
    file: ./github-app-private-key.pem
```

Or base64 encode the key:

```bash
# Encode
cat private-key.pem | base64 -w0 > private-key.b64

# In environment
AEF_GITHUB_PRIVATE_KEY_B64=$(cat private-key.b64)
```

### Step 5: Verify Configuration

Test that everything is configured correctly:

```bash
# Start the dashboard
cd apps/aef-dashboard
uv run python -m aef_dashboard

# Check health endpoint
curl http://localhost:8000/health

# Trigger a test webhook (if configured)
curl -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -d '{"zen": "Test ping"}'
```

## How It Works

### Token Generation Flow

```
┌──────────────────┐     ┌─────────────────┐     ┌────────────────┐
│  AEF Agent       │────▶│  GitHub App     │────▶│   GitHub API   │
│  needs token     │     │  Client         │     │                │
└──────────────────┘     └─────────────────┘     └────────────────┘
                              │
                              ▼
                    1. Generate JWT using
                       private key (9 min TTL)
                              │
                              ▼
                    2. POST /app/installations/
                       {installation_id}/access_tokens
                              │
                              ▼
                    3. Receive installation token
                       (1 hour TTL)
                              │
                              ▼
                    4. Cache token until near expiry
```

### Commit Attribution

When an agent makes a commit, it appears as:

```
Author: aef-agent[bot] <123456+aef-agent[bot]@users.noreply.github.com>
Committer: aef-agent[bot] <123456+aef-agent[bot]@users.noreply.github.com>

fix(api): handle null response in user endpoint

Applied by AEF agent
- Workflow: code-review-123
- Execution: exec-abc
- Session: session-xyz

Co-authored-by: John Developer <john@example.com>
```

### Self-Healing Workflow

With the full permission set, agents can autonomously maintain codebases:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SELF-HEALING LOOP                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. CI FAILURE DETECTED (workflow_run event)                    │
│     │                                                           │
│     ▼                                                           │
│  2. READ LOGS (Actions: read)                                   │
│     GET /repos/{owner}/{repo}/actions/runs/{id}/logs            │
│     │                                                           │
│     ▼                                                           │
│  3. ANALYZE & FIX (Agent reasoning)                             │
│     Parse error → Generate fix → Validate locally               │
│     │                                                           │
│     ▼                                                           │
│  4. PUSH FIX (Contents: write)                                  │
│     git commit → git push                                       │
│     │                                                           │
│     ▼                                                           │
│  5. UPDATE STATUS (Commit statuses: write)                      │
│     POST /repos/{owner}/{repo}/statuses/{sha}                   │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  6. PR REVIEW RECEIVED (pull_request_review_comment event)      │
│     │                                                           │
│     ▼                                                           │
│  7. READ COMMENTS (Pull requests: read)                         │
│     GET /repos/{owner}/{repo}/pulls/{id}/comments               │
│     │                                                           │
│     ▼                                                           │
│  8. ADDRESS FEEDBACK (Agent reasoning)                          │
│     Understand comment → Apply fix → Commit                     │
│     │                                                           │
│     ▼                                                           │
│  9. REPLY TO REVIEW (Pull requests: write)                      │
│     POST /repos/{owner}/{repo}/pulls/{id}/comments              │
│     "✅ Fixed - Added error handling as suggested"              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### API Examples

```python
# Read workflow logs for self-healing
async def get_failed_logs(run_id: int) -> str:
    response = await github_client.get(
        f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
        headers={"Accept": "application/vnd.github+json"}
    )
    return response.content

# Read PR review comments
async def get_review_comments(pr_number: int) -> list:
    response = await github_client.get(
        f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    )
    return response.json()

# Reply to a review comment
async def reply_to_comment(pr_number: int, comment_id: int, body: str):
    await github_client.post(
        f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
        json={
            "body": body,
            "in_reply_to": comment_id
        }
    )
```

## Troubleshooting

### "Private key not found" Error

Ensure the key is correctly formatted with newlines preserved:

```python
# Check key format in Python
import os
key = os.environ.get("AEF_GITHUB_PRIVATE_KEY", "")
print(f"Key starts with: {key[:50]}")
print(f"Key length: {len(key)}")
```

### "Bad credentials" Error (401)

1. Verify the App ID matches your GitHub App
2. Confirm the private key is for this specific app
3. Check the Installation ID is correct

### "Resource not accessible by integration" Error (403)

The app doesn't have sufficient permissions:
1. Go to GitHub App settings
2. Update repository permissions
3. Users may need to re-approve the updated permissions

### Token Expired During Long Operation

The client automatically refreshes tokens, but if you're caching tokens externally:
- Check `expires_at` before using
- Refresh when less than 5 minutes remain
- Force refresh if you get a 401 error

## Security Best Practices

1. **Never log tokens**: Use `token_hash` property for logging
2. **Rotate the private key periodically**: Generate a new key every 90 days
3. **Use webhook secrets**: Always verify webhook signatures (HMAC-SHA256)
4. **Monitor installations**: Review which orgs/repos have access
5. **Audit agent actions**: All commits are attributed to `<app>[bot]` for traceability
6. **Limit repository access**: Install on specific repos rather than "all repositories" when possible

### Permission Justification

| Permission | Justification |
|------------|---------------|
| Contents: Write | Push commits, create branches for fixes |
| Pull requests: Write | Create PRs, respond to review comments |
| Actions: Read | Read CI logs to diagnose failures |
| Checks: Write | Create check runs for agent validations |
| Commit statuses: Write | Update commit status after agent actions |
| Issues: Write | Create issues for findings, track work |

> **Note**: All permissions are used for autonomous codebase maintenance. The agent cannot access private data beyond what's needed for code operations.

## Related Documentation

- [GitHub Apps Documentation](https://docs.github.com/en/apps)
- [Authenticating as a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app)
- [ADR-021: Isolated Workspace Architecture](../adrs/ADR-021-isolated-workspace-architecture.md)
