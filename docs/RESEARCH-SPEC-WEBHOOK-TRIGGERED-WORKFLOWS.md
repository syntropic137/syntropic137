# Research Spec: Phase 2 - Webhook-Triggered Workflows

**Status**: Superseded by [ADR-040](adrs/ADR-040-github-trigger-architecture.md) and [PROJECT-PLAN: GitHub Trigger System](../PROJECT-PLAN_20260204_GITHUB-TRIGGER-SYSTEM.md)
**Created**: 2025-12-11
**Related**: ADR-022, ADR-023, ADR-040, F15 (GitHub App)
**Priority**: Implemented

---

## Overview

Phase 2 enables **automatic workflow execution triggered by GitHub webhooks**. When certain GitHub events occur (issue created, PR comment, label added), the system automatically starts a workflow execution.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    GitHub       │     │   AEF Webhook   │     │   Workflow      │
│    Event        │────▶│   Handler       │────▶│   Executor      │
│ (Issue Created) │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │  Event Store    │
                        │  (Audit Trail)  │
                        └─────────────────┘
```

---

## Phase 1 Prerequisites (✅ Complete)

Before Phase 2 can work, Phase 1 must be complete:

| Prerequisite | Status |
|-------------|--------|
| GitHub App configured | ✅ |
| Installation tokens working | ✅ |
| WorkflowExecutionEngine with WorkspaceRouter DI | ✅ |
| Events flowing through aggregates | ✅ |
| Secure token architecture (ADR-022) | ✅ |
| Workspace-First execution (ADR-023) | ✅ |

---

## Webhook Events to Support

### Priority 1: Issue-Based Triggers

| GitHub Event | Trigger Condition | Workflow Type |
|--------------|-------------------|---------------|
| `issues.opened` | Issue created with label `aef:auto` | Research/Triage |
| `issues.labeled` | Label `aef:implement` added | Implementation |
| `issue_comment.created` | Comment starts with `/aef` | Command-based |

### Priority 2: PR-Based Triggers

| GitHub Event | Trigger Condition | Workflow Type |
|--------------|-------------------|---------------|
| `pull_request.opened` | PR opened with label `aef:review` | Code Review |
| `pull_request_review.submitted` | Review requests changes | Fix Review |
| `pull_request.synchronize` | New commits pushed | Re-review |

### Priority 3: Repository Events

| GitHub Event | Trigger Condition | Workflow Type |
|--------------|-------------------|---------------|
| `push` | Push to `main` with certain paths | CI/Validation |
| `release.published` | Release created | Documentation |
| `workflow_run.completed` | CI failed | Self-Healing |

---

## Architecture

### Component: Webhook Handler Service

```python
# aef-webhook/src/aef_webhook/handler.py

from fastapi import FastAPI, Request, HTTPException
from aef_domain.contexts.workflows import WorkflowExecutionEngine

app = FastAPI()

@app.post("/webhooks/github")
async def handle_github_webhook(request: Request):
    """Handle incoming GitHub webhooks."""

    # 1. Verify webhook signature (HMAC-SHA256)
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(await request.body(), signature):
        raise HTTPException(403, "Invalid signature")

    # 2. Parse event
    event_type = request.headers.get("X-GitHub-Event")
    payload = await request.json()

    # 3. Emit WebhookReceived event
    await emit_webhook_received_event(event_type, payload)

    # 4. Route to appropriate handler
    handler = get_handler_for_event(event_type, payload)
    if handler:
        execution_id = await handler.execute(payload)
        return {"status": "accepted", "execution_id": execution_id}

    return {"status": "ignored", "reason": "No handler for event"}
```

### Webhook Signature Verification

```python
import hmac
import hashlib

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

### Event-to-Workflow Mapping

```python
# Configuration-driven mapping
WEBHOOK_TRIGGERS = {
    "issues.opened": {
        "condition": lambda p: "aef:auto" in [l["name"] for l in p["issue"]["labels"]],
        "workflow_template": "research-workflow-v1",
        "inputs_from": lambda p: {
            "issue_number": p["issue"]["number"],
            "issue_title": p["issue"]["title"],
            "issue_body": p["issue"]["body"],
            "repository": p["repository"]["full_name"],
        }
    },
    "issue_comment.created": {
        "condition": lambda p: p["comment"]["body"].startswith("/aef"),
        "workflow_template": "command-workflow-v1",
        "inputs_from": lambda p: {
            "command": parse_command(p["comment"]["body"]),
            "issue_number": p["issue"]["number"],
            "repository": p["repository"]["full_name"],
        }
    },
}
```

---

## Event Store Integration

### New Events

```python
# WebhookReceived - audit trail for all incoming webhooks
@dataclass
class WebhookReceived:
    webhook_id: str
    event_type: str  # e.g., "issues.opened"
    delivery_id: str  # X-GitHub-Delivery header
    repository: str
    sender: str
    timestamp: datetime
    payload_hash: str  # SHA-256 of payload (not full payload for size)

# WebhookTriggeredExecution - links webhook to execution
@dataclass
class WebhookTriggeredExecution:
    webhook_id: str
    execution_id: str
    workflow_template: str
    trigger_condition: str
```

### Aggregate: WebhookAggregate

```python
class WebhookAggregate:
    """Tracks webhook processing lifecycle."""

    def handle_receive(self, cmd: ReceiveWebhookCommand) -> None:
        self._apply(WebhookReceived(...))

    def handle_trigger(self, cmd: TriggerExecutionCommand) -> None:
        self._apply(WebhookTriggeredExecution(...))

    def handle_ignore(self, cmd: IgnoreWebhookCommand) -> None:
        self._apply(WebhookIgnored(reason=cmd.reason))

    def handle_fail(self, cmd: FailWebhookCommand) -> None:
        self._apply(WebhookFailed(error=cmd.error))
```

---

## Security Considerations

### 1. Webhook Secret Validation

```bash
# Environment variable
AEF_GITHUB_WEBHOOK_SECRET=<random-256-bit-secret>
```

Every incoming webhook MUST be validated against this secret.

### 2. Rate Limiting

Prevent webhook floods:

```python
from fastapi_limiter import FastAPILimiter

@app.post("/webhooks/github")
@limiter.limit("100/minute")
async def handle_github_webhook(request: Request):
    ...
```

### 3. Payload Size Limits

```python
@app.post("/webhooks/github")
async def handle_github_webhook(request: Request):
    body = await request.body()
    if len(body) > 10_000_000:  # 10MB max
        raise HTTPException(413, "Payload too large")
```

### 4. Execution Budget Per Webhook

Each webhook-triggered execution should have a default budget:

```python
DEFAULT_WEBHOOK_BUDGET = BudgetAllocation(
    max_input_tokens=50_000,
    max_output_tokens=20_000,
    max_cost_usd=Decimal("5.00"),
)
```

---

## API Endpoints

### Webhook Endpoint

```
POST /webhooks/github
Headers:
  X-GitHub-Event: issues
  X-GitHub-Delivery: abc123
  X-Hub-Signature-256: sha256=...
Body: <JSON payload>

Response:
  200 OK: {"status": "accepted", "execution_id": "exec-xyz"}
  200 OK: {"status": "ignored", "reason": "No handler"}
  403 Forbidden: {"error": "Invalid signature"}
  429 Too Many Requests: {"error": "Rate limited"}
```

### Webhook Status Endpoint

```
GET /api/webhooks/{webhook_id}
Response:
  {
    "webhook_id": "wh-abc123",
    "event_type": "issues.opened",
    "status": "triggered",
    "execution_id": "exec-xyz",
    "received_at": "2025-12-11T10:00:00Z"
  }
```

### Recent Webhooks List

```
GET /api/webhooks?limit=50
Response:
  {
    "webhooks": [
      {"webhook_id": "wh-abc", "event_type": "issues.opened", "status": "triggered"},
      {"webhook_id": "wh-def", "event_type": "push", "status": "ignored"},
    ]
  }
```

---

## Infrastructure Requirements

### 1. Cloudflare Tunnel (Local Dev)

For local development, expose webhook endpoint via Cloudflare Tunnel:

```bash
# Install cloudflared
brew install cloudflared

# Create tunnel
cloudflared tunnel create aef-webhooks

# Route to local service
cloudflared tunnel route dns aef-webhooks webhooks.aef.dev

# Start tunnel
cloudflared tunnel run --url http://localhost:8001 aef-webhooks
```

### 2. Docker Service

```yaml
# docker-compose.dev.yaml
services:
  aef-webhook:
    build: ./packages/aef-webhook
    ports:
      - "8001:8001"
    environment:
      - AEF_GITHUB_WEBHOOK_SECRET=${AEF_GITHUB_WEBHOOK_SECRET}
      - AEF_EVENT_STORE_URL=http://aef-event-store:50051
    depends_on:
      - aef-event-store
      - aef-postgres
```

### 3. GitHub App Webhook Configuration

In GitHub App settings:
- Webhook URL: `https://webhooks.aef.dev/webhooks/github`
- Webhook Secret: (generate and store in AEF_GITHUB_WEBHOOK_SECRET)
- Events: issues, issue_comment, pull_request, pull_request_review, push

---

## Milestones

### Milestone 1: Webhook Handler Service (4h)
- [ ] Create `packages/aef-webhook/` package
- [ ] Implement FastAPI webhook endpoint
- [ ] Implement signature verification
- [ ] Add rate limiting
- [ ] Add tests

### Milestone 2: Event Store Integration (3h)
- [ ] Create WebhookAggregate
- [ ] Create WebhookReceived, WebhookTriggeredExecution events
- [ ] Add WebhookRepository
- [ ] Add tests

### Milestone 3: Event-to-Workflow Mapping (4h)
- [ ] Create configuration-driven trigger mapping
- [ ] Implement condition evaluation
- [ ] Implement input extraction
- [ ] Connect to WorkflowExecutionEngine
- [ ] Add tests

### Milestone 4: Dashboard Integration (3h)
- [ ] Add /api/webhooks endpoints to dashboard
- [ ] Create WebhooksPage component
- [ ] Show webhook → execution link
- [ ] Real-time updates via SSE

### Milestone 5: E2E Test (2h)
- [ ] Create test repository
- [ ] Configure GitHub App webhooks
- [ ] Create issue with `aef:auto` label
- [ ] Verify workflow execution starts
- [ ] Verify events in event store

---

## Estimated Effort

| Milestone | Effort |
|-----------|--------|
| Webhook Handler Service | 4h |
| Event Store Integration | 3h |
| Event-to-Workflow Mapping | 4h |
| Dashboard Integration | 3h |
| E2E Test | 2h |
| **Total** | **16h** |

---

## Success Criteria

1. ✅ Webhook endpoint receives GitHub events
2. ✅ Signature validation rejects invalid requests
3. ✅ Rate limiting prevents floods
4. ✅ WebhookReceived events in event store
5. ✅ Issue with `aef:auto` label triggers workflow
6. ✅ `/aef` comment triggers command workflow
7. ✅ Dashboard shows webhook history
8. ✅ Execution linked to triggering webhook

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Webhook floods | High | Rate limiting, queue processing |
| Signature bypass | Critical | Always validate, fail closed |
| Runaway executions | High | Default budget limits |
| Duplicate deliveries | Medium | Idempotency via delivery_id |

---

## Open Questions

1. **Retry Policy**: Should failed webhook processing be retried?
2. **Queue vs Sync**: Process webhooks synchronously or via queue?
3. **Multi-Tenant**: How to handle multiple GitHub App installations?
4. **Approval Flow**: Should some triggers require human approval?

---

## Next Steps

1. Review and approve this research spec
2. Create GitHub issue for tracking
3. Set up Cloudflare Tunnel for local testing
4. Start with Milestone 1: Webhook Handler Service
