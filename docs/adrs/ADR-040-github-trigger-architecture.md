# ADR-040: GitHub Trigger Architecture

## Status

Proposed

## Context

Syn137 provides orchestration and observability for agentic workflows. Currently, workflows are triggered manually via the dashboard API or CLI. There is no mechanism for GitHub events (CI failures, review comments) to automatically trigger corrective workflows.

### The Problem

1. **CI failures on PRs require manual intervention.** When a lint, type check, or test fails on a PR, a human or agent must manually notice, diagnose, and fix the issue. This is especially wasteful for simple failures (formatting, missing imports) on bot-created PRs.

2. **Review comments go unaddressed.** When reviewers (human or Copilot) leave feedback, someone must manually process each comment. For bot-created PRs, the bot should handle this autonomously.

3. **No programmatic trigger registration.** There is no way for an agent to say "enable self-healing for this repository" as part of project setup. Triggers should be a first-class API/CLI resource.

### Goals

1. Enable automatic workflow execution in response to GitHub webhook events
2. Provide CLI/API-first trigger rule management (register, pause, delete)
3. Prevent infinite loops and runaway costs via safety guards
4. Follow existing VSA conventions in the `github` bounded context
5. Keep trigger infrastructure thin - all behavior intelligence lives in workflow definitions

### Prerequisites (Complete)

- GitHub App with webhook delivery configured
- Webhook signature verification (HMAC-SHA256)
- `WorkflowExecutionEngine` with workspace isolation (ADR-023)
- Installation token management (ADR-024)

## Decision

### 1. Triggers Are a Domain Concept in the `github` Bounded Context

Trigger rules are managed as a new aggregate (`TriggerRuleAggregate`) in the `github` bounded context. This is appropriate because:

- Trigger rules are scoped to GitHub repositories
- Trigger evaluation processes GitHub webhook payloads
- The `github` context already owns webhook handling and installation tokens

If non-GitHub trigger sources are needed in the future (cron, Slack), the trigger aggregate can be extracted to a dedicated `triggers` bounded context.

### 2. Thin Triggers, Smart Workflows

The trigger layer is intentionally thin. It answers three questions:

1. **Did something relevant happen?** (event type + conditions match)
2. **Should we act on it?** (safety guards pass)
3. **Which workflow, with what inputs?** (dispatch to `WorkflowExecutionEngine`)

All behavioral intelligence (how to fix CI, how to respond to review comments, which branch to push to, how to format commit messages) lives in **workflow definitions**. This separation means:

- New trigger behaviors don't require code changes (just new workflows)
- Workflow prompts can be iterated without touching trigger infrastructure
- The same workflow can be triggered manually (API/CLI) or automatically (webhook)

### 3. Trigger Rule Lifecycle

```
RegisterTriggerCommand
        │
        ▼
    ┌────────┐     PauseTriggerCommand     ┌────────┐
    │ ACTIVE │ ──────────────────────────▶ │ PAUSED │
    │        │ ◀────────────────────────── │        │
    └────┬───┘     ResumeTriggerCommand    └────────┘
         │
         │ DeleteTriggerCommand
         ▼
    ┌─────────┐
    │ DELETED │
    └─────────┘
```

Trigger rules are event-sourced for full audit trail. Each state transition emits a domain event.

### 4. Safety Guards

Every trigger evaluation passes through safety guards before dispatching:

| Guard | `guard_name` | Purpose |
|-------|-------------|---------|
| **Concurrency** | `concurrency` | Block if execution already running for same (trigger, PR) — prevents catch-up storms |
| **Bot Sender Check** | — | Prevent infinite loops — don't trigger on the bot's own commits |
| **Max Attempts** | `max_attempts` | Cap retries per (PR, trigger) combination |
| **Cooldown** | `cooldown` | Minimum time between fires for the same PR (retryable) |
| **Daily Limit** | `daily_limit` | Maximum triggers per day per rule |
| **Idempotency** | `idempotency` | Don't process the same `X-GitHub-Delivery` twice |
| **Budget** | — | Maximum cost per triggered workflow execution |

Guards are evaluated in order. The concurrency guard runs first as the cheapest check and the most common block during event catch-up after restarts.

#### Concurrency Guard (Coalescing Key)

When the event poller catches up after a restart, it may deliver many events for the same PR simultaneously. Without coalescing, each event fires a separate execution — wasteful and potentially conflicting.

The concurrency guard uses a **coalescing key** of `(trigger_id, pr_number)`. If an execution is already RUNNING for that key, new triggers are blocked. For non-PR events, the key is just `trigger_id`.

Execution tracking piggybacks on `record_fire()` — when a trigger fires, the execution is marked as running in an **in-memory** set. When the workflow completes (via `WorkflowCompletedEvent` or `WorkflowFailedEvent`), it's cleared via `complete_execution()`.

Running-execution state is intentionally **not persisted**. On restart, no executions survive because containers are ephemeral (see AGENTS.md crash recovery). The in-memory set starts empty, so the poller catch-up after restart won't be blocked by stale running-execution entries. Fire records (persisted via projection) track *history* only — they are never used to infer running state.

### 5. Debounce for Review Comments

When a reviewer leaves multiple comments rapidly, the system debounces:

- First comment arrives → start timer (default 60s)
- More comments arrive → reset timer
- Timer expires → fire trigger once, workflow reads ALL unresolved threads

This prevents N triggers for N comments. The workflow always reads the complete picture via the GitHub GraphQL API.

### 6. Built-In Presets

Two presets ship with the system:

- **`self-healing`**: Triggers on `check_run.completed` with `conclusion == "failure"`, dispatches `ci-fix-workflow`
- **`review-fix`**: Triggers on `pull_request_review.submitted` with `state == "changes_requested"`, dispatches `fix-review-workflow`

Presets are registered via `syn triggers enable <preset> --repository <repo>`.

### 7. Input Mapping

Trigger rules include an `input_mapping` that extracts workflow inputs from the webhook payload using dot-notation paths:

```json
{
  "repository": "repository.full_name",
  "pr_number": "check_run.pull_requests[0].number",
  "branch": "check_run.pull_requests[0].head.ref",
  "check_name": "check_run.name"
}
```

This keeps trigger rules declarative and avoids custom code per trigger type.

### 8. Trigger Observability — TriggerBlockedEvent

When a trigger is blocked (by a safety guard, conditions not met, or concurrency), the system emits a `TriggerBlockedEvent` into the event store. This provides a complete audit trail for trigger decisions — not just fires, but blocks too.

```
github.TriggerBlocked (v1)
├── trigger_id        # Which trigger was blocked
├── guard_name        # "concurrency", "max_attempts", "cooldown", "daily_limit",
│                     #  "idempotency", "conditions_not_met"
├── reason            # Human-readable explanation
├── webhook_delivery_id
├── github_event_type
├── repository
├── pr_number
└── payload_summary   # Same shape as TriggerFiredEvent
```

The `TriggerHistoryProjection` projects both `TriggerFiredEvent` and `TriggerBlockedEvent` into a unified history view. Entries have a `status` field: `dispatched`, `completed`, `failed`, or `blocked`.

This enables:
- `syn triggers history <id>` shows blocked entries alongside fires
- Operators can answer "why didn't this trigger fire?" without grepping logs
- Future guards (#580 contributor allowlist) emit `TriggerBlockedEvent` automatically

## Consequences

### Positive

- Agents can programmatically register self-healing for repositories
- CI failures and review comments are handled automatically
- Full audit trail via event-sourced trigger rules
- Safety guards prevent infinite loops and cost overruns
- Workflow definitions are reusable (manual or triggered)
- CLI/API-first design enables integration with any client

### Negative

- Additional complexity in the `github` bounded context (new aggregate, 6 slices)
- In-memory debounce state is lost on restart (acceptable for v1)
- Condition evaluation is limited to simple operators (no complex expressions)
- Only GitHub triggers supported initially

### Neutral

- Existing webhook handler is modified to route unhandled events to trigger evaluation
- Two new workflow YAML files added to `workflows/triggers/`
- CLI gains a new `triggers` subcommand group

## References

- [ADR-023: Workspace-First Execution Model](ADR-023-workspace-first-execution-architecture.md)
- [ADR-024: Setup Phase Secrets](ADR-024-setup-phase-secrets.md)
- [Research Spec: Webhook-Triggered Workflows](../RESEARCH-SPEC-WEBHOOK-TRIGGERED-WORKFLOWS.md)
- [GitHub Webhook Events and Payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- [GitHub Apps: check_run event](https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_run)
- [GitHub Apps: pull_request_review event](https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review)
