# HANDOFF: Phase 2 - Webhook-Triggered Workflows

**Date:** 2025-12-13
**Status:** Research Spec
**Prerequisites:** Phase 1 (Workspace-First Execution) must be complete
**Priority:** P1 (High - enables self-healing and GitHub integration)

---

## Executive Summary

Phase 2 enables **GitHub webhook-triggered agentic workflows**. Instead of manually starting workflows, GitHub events (push, PR comment, CI failure) automatically trigger agent execution.

### Use Cases

| Trigger | Agent Response |
|---------|---------------|
| `@aef-engineer-beta fix this` comment on PR | Agent analyzes code, creates fix, pushes to branch |
| CI workflow fails | Agent reads logs, diagnoses issue, opens fix PR |
| New issue created with `bug` label | Agent triages, reproduces, proposes fix |
| Push to `main` branch | Agent runs code review, adds comments |

---

## Context

### Current State (After Phase 1)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Manual Trigger                               │
│  User runs: aef workflow run implementation-workflow-v1              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WorkflowExecutionEngine                           │
│  - Uses WorkspaceRouter (isolated execution)                         │
│  - Persists events via aggregate pattern                             │
│  - Injects credentials via sidecar                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Target State (Phase 2)

```
┌─────────────────────────────────────────────────────────────────────┐
│                       GitHub Webhooks                                │
│  push, pull_request, issue_comment, workflow_run, etc.              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTPS POST
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Webhook Receiver (FastAPI)                        │
│  POST /webhooks/github                                               │
│  - Verify signature (X-Hub-Signature-256)                            │
│  - Parse event type (X-GitHub-Event header)                          │
│  - Route to appropriate handler                                      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Event Router                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ PR Comment      │  │ CI Failure      │  │ Issue Created       │  │
│  │ Handler         │  │ Handler         │  │ Handler             │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘  │
│           │                    │                      │              │
│           └────────────────────┼──────────────────────┘              │
│                                │                                     │
└────────────────────────────────┼─────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WorkflowExecutionEngine                           │
│  (Same as Phase 1 - isolated, event-sourced)                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Research Questions

### RQ1: Webhook Delivery & Security

1. How do we verify GitHub webhook signatures?
2. How do we handle webhook retries and idempotency?
3. What's the latency budget for webhook response (GitHub times out at 10s)?
4. How do we queue long-running workflows triggered by webhooks?

### RQ2: Event Routing

1. Which GitHub events should trigger workflows?
2. How do we map events to workflow types?
3. How do we handle event filtering (e.g., only PRs to `main`)?
4. How do we prevent infinite loops (agent commit triggers webhook)?

### RQ3: Self-Healing Workflows

1. How do we access CI failure logs via GitHub API?
2. How do we parse different CI systems (GitHub Actions, CircleCI, etc.)?
3. How do we determine if a failure is fixable by an agent?
4. How do we limit retry attempts to prevent cost runaway?

### RQ4: PR Comment Commands

1. What command syntax should we use? (`@bot fix`, `/aef fix`, etc.)
2. How do we handle permissions (who can trigger agent)?
3. How do we provide feedback (reactions, comments)?
4. How do we handle long-running tasks (progress updates)?

### RQ5: Infrastructure

1. Do we need a message queue (Redis, RabbitMQ) for async processing?
2. How do we expose the webhook endpoint publicly (Cloudflare Tunnel, ngrok)?
3. How do we handle multiple concurrent webhook triggers?
4. How do we scale webhook processing?

---

## GitHub Events Reference

### Recommended Events to Handle

| Event | Trigger | Use Case |
|-------|---------|----------|
| `issue_comment` | Comment on issue/PR | `@bot fix this` commands |
| `pull_request` | PR opened/updated | Auto-review, suggestions |
| `push` | Code pushed to branch | Code quality checks |
| `workflow_run` | CI workflow completes | Self-healing on failure |
| `issues` | Issue created/labeled | Auto-triage, bug fixes |
| `check_run` | Check completed | React to check failures |

### Event Payloads

```python
# issue_comment event
{
    "action": "created",
    "issue": {
        "number": 123,
        "title": "Bug in login",
        "body": "...",
        "pull_request": {...}  # Present if PR comment
    },
    "comment": {
        "body": "@aef-engineer-beta fix this",
        "user": {"login": "neuralempowerment"}
    },
    "repository": {
        "full_name": "AgentParadise/sandbox_aef-engineer-beta"
    },
    "installation": {
        "id": 99311335
    }
}

# workflow_run event (CI failure)
{
    "action": "completed",
    "workflow_run": {
        "conclusion": "failure",
        "logs_url": "https://api.github.com/repos/.../actions/runs/.../logs",
        "head_branch": "feature-x",
        "head_sha": "abc123"
    },
    "repository": {...},
    "installation": {...}
}
```

---

## Proposed Architecture

### Webhook Receiver

```python
# apps/aef-dashboard/src/aef_dashboard/api/webhooks.py

from fastapi import APIRouter, Request, HTTPException, Header
import hmac
import hashlib

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_hub_signature_256: str = Header(...),
    x_github_delivery: str = Header(...),
):
    """Receive GitHub webhook events."""
    # 1. Verify signature
    body = await request.body()
    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(401, "Invalid signature")

    # 2. Parse payload
    payload = await request.json()

    # 3. Check idempotency (prevent duplicate processing)
    if await is_already_processed(x_github_delivery):
        return {"status": "already_processed"}

    # 4. Route to handler (async - return immediately)
    await enqueue_webhook_event(
        event_type=x_github_event,
        delivery_id=x_github_delivery,
        payload=payload,
    )

    # 5. Return quickly (GitHub times out at 10s)
    return {"status": "accepted", "delivery_id": x_github_delivery}


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature."""
    secret = settings.github_webhook_secret.get_secret_value()
    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

### Event Router

```python
# packages/aef-domain/src/aef_domain/contexts/webhooks/router.py

class WebhookEventRouter:
    """Routes GitHub webhook events to appropriate handlers."""

    def __init__(
        self,
        workflow_engine: WorkflowExecutionEngine,
        github_client: GitHubAppClient,
    ):
        self._engine = workflow_engine
        self._github = github_client

    async def route(self, event_type: str, payload: dict) -> None:
        """Route webhook event to appropriate handler."""
        handler = self._get_handler(event_type, payload)
        if handler:
            await handler.handle(payload)

    def _get_handler(self, event_type: str, payload: dict):
        """Get handler for event type."""
        if event_type == "issue_comment":
            if self._is_command(payload):
                return PRCommandHandler(self._engine, self._github)

        if event_type == "workflow_run":
            if payload.get("action") == "completed":
                if payload["workflow_run"]["conclusion"] == "failure":
                    return CIFailureHandler(self._engine, self._github)

        if event_type == "issues":
            if payload.get("action") == "opened":
                return IssueTriageHandler(self._engine, self._github)

        return None

    def _is_command(self, payload: dict) -> bool:
        """Check if comment is a bot command."""
        body = payload.get("comment", {}).get("body", "")
        return "@aef-engineer-beta" in body or "/aef" in body
```

### PR Command Handler

```python
# packages/aef-domain/src/aef_domain/contexts/webhooks/handlers/pr_command.py

class PRCommandHandler:
    """Handles @bot commands in PR comments."""

    COMMANDS = {
        "fix": "quick-fix-workflow",
        "review": "code-review-workflow",
        "explain": "code-explanation-workflow",
        "test": "add-tests-workflow",
    }

    async def handle(self, payload: dict) -> None:
        """Handle PR command."""
        comment = payload["comment"]["body"]
        command = self._parse_command(comment)

        if not command:
            await self._reply_help(payload)
            return

        # React to show we're processing
        await self._github.api_post(
            f"/repos/{payload['repository']['full_name']}/issues/comments/{payload['comment']['id']}/reactions",
            json={"content": "eyes"}
        )

        # Start workflow
        workflow_id = self.COMMANDS[command]
        result = await self._engine.execute(
            workflow_id=workflow_id,
            inputs={
                "repo": payload["repository"]["full_name"],
                "pr_number": payload["issue"]["number"],
                "command": command,
                "comment": comment,
                "requested_by": payload["comment"]["user"]["login"],
            }
        )

        # Reply with result
        await self._reply_result(payload, result)
```

### CI Failure Handler (Self-Healing)

```python
# packages/aef-domain/src/aef_domain/contexts/webhooks/handlers/ci_failure.py

class CIFailureHandler:
    """Handles CI workflow failures - attempts self-healing."""

    MAX_RETRIES = 3

    async def handle(self, payload: dict) -> None:
        """Handle CI failure - attempt to fix."""
        workflow_run = payload["workflow_run"]

        # Check retry count
        if await self._exceeded_retries(workflow_run):
            await self._notify_human(payload)
            return

        # Download failure logs
        logs = await self._github.download_logs(workflow_run["logs_url"])

        # Parse failure reason
        failure = self._parse_failure(logs)

        if not failure.is_fixable:
            await self._notify_human(payload, failure)
            return

        # Start fix workflow
        result = await self._engine.execute(
            workflow_id="ci-fix-workflow",
            inputs={
                "repo": payload["repository"]["full_name"],
                "branch": workflow_run["head_branch"],
                "sha": workflow_run["head_sha"],
                "failure_type": failure.type,
                "failure_details": failure.details,
                "logs_excerpt": failure.relevant_logs,
            }
        )

        # If fix succeeded, commit and push
        if result.is_success:
            await self._push_fix(payload, result)
```

---

## Infinite Loop Prevention

Critical: Agent commits should NOT trigger new webhooks that trigger new agent runs.

### Strategies

1. **Bot Detection**: Ignore events from bot accounts
   ```python
   if payload["sender"]["type"] == "Bot":
       return  # Ignore bot-triggered events
   ```

2. **Commit Message Convention**: Skip commits with `[skip-agent]` or `[bot]`
   ```python
   if "[skip-agent]" in commit_message:
       return
   ```

3. **Branch Pattern**: Ignore pushes to agent-created branches
   ```python
   if branch.startswith("aef/"):
       return  # Agent branches start with aef/
   ```

4. **Cooldown Period**: Don't process events within N minutes of agent action
   ```python
   if await recently_processed(repo, branch, minutes=5):
       return
   ```

---

## Infrastructure Requirements

### Local Development

```yaml
# docker/docker-compose.dev.yaml additions

services:
  # Webhook receiver (part of dashboard)
  aef-dashboard:
    ports:
      - "8000:8000"
    environment:
      - AEF_GITHUB_WEBHOOK_SECRET=${AEF_GITHUB_WEBHOOK_SECRET}

  # Message queue for async webhook processing
  aef-redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # Cloudflare tunnel for local webhook testing
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --url http://aef-dashboard:8000
    # Outputs public URL for GitHub webhook config
```

### Production

- Kubernetes ingress with TLS
- Horizontal pod autoscaler for webhook receiver
- Redis cluster for webhook queue
- Dead letter queue for failed webhooks

---

## Testing Strategy

### Unit Tests

```python
def test_verify_signature():
    """Test GitHub signature verification."""
    ...

def test_parse_pr_command():
    """Test parsing @bot commands."""
    ...

def test_infinite_loop_prevention():
    """Test bot events are ignored."""
    ...
```

### Integration Tests

```python
async def test_webhook_triggers_workflow():
    """Test webhook → workflow execution."""
    # 1. Send mock webhook
    # 2. Verify workflow started
    # 3. Verify events in event store
    ...

async def test_ci_failure_self_healing():
    """Test CI failure triggers fix workflow."""
    # 1. Send workflow_run failure event
    # 2. Verify fix workflow started
    # 3. Verify PR created with fix
    ...
```

### E2E Test

```python
async def test_full_webhook_flow():
    """Test real GitHub webhook → agent → PR."""
    # 1. Create test issue with @bot command
    # 2. Wait for webhook delivery
    # 3. Verify agent executed
    # 4. Verify PR/comment created
    ...
```

---

## Dependencies

| Dependency | Purpose | Status |
|------------|---------|--------|
| Phase 1 (Workspace-First) | Isolated agent execution | **REQUIRED** |
| GitHub App | Webhook receiver, API access | ✅ Complete |
| Token Vending Service | Scoped tokens for agents | ✅ Complete |
| Spend Tracker | Budget for webhook-triggered runs | ✅ Complete |
| Redis (optional) | Async webhook queue | ⬜ To implement |
| Cloudflare Tunnel | Local webhook testing | ⬜ To configure |

---

## Estimated Effort

| Milestone | Effort |
|-----------|--------|
| Webhook receiver + signature verification | 3 hours |
| Event router + handlers | 4 hours |
| PR command handling | 4 hours |
| CI failure self-healing | 6 hours |
| Infinite loop prevention | 2 hours |
| Integration tests | 4 hours |
| E2E test with real GitHub | 3 hours |
| Documentation | 2 hours |
| **Total** | **28 hours** |

---

## Open Questions for Research

1. **Webhook Secret Rotation**: How do we rotate the webhook secret without downtime?
2. **Multi-Installation**: How do we handle webhooks from multiple GitHub App installations?
3. **Rate Limiting**: How do we handle GitHub API rate limits during high webhook volume?
4. **Cost Control**: How do we prevent runaway costs from webhook storms?
5. **Observability**: What metrics/dashboards do we need for webhook health?

---

## Next Steps (For Receiving Agent)

1. **ERM**: Research GitHub webhook best practices and security
2. **EIM**: Explore queue architecture options (Redis vs in-memory)
3. **EPM**: Create detailed project plan with milestones
4. **EEM**: Implement starting with webhook receiver

---

## References

- [GitHub Webhooks Documentation](https://docs.github.com/en/webhooks)
- [GitHub App Webhooks](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/using-webhooks-with-github-apps)
- [Securing Webhooks](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- [ADR-022: Secure Token Architecture](./docs/adrs/ADR-022-secure-token-architecture.md)
- [ADR-023: Workspace-First Execution Model](./docs/adrs/ADR-023-workspace-first-execution-model.md)
