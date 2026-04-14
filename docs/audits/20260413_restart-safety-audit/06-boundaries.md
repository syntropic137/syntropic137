# 06 - Boundaries: Domain vs Integration vs Glue

**Status:** COMPLETE

## Question

> "What parts of this architecture are pure domain logic, what parts are
> integration logic, and what parts are orchestration glue?"

## File-to-Concern Mapping

| File | Concern | Clean? |
|------|---------|--------|
| `event_pipeline/pipeline.py` | **Observe** (dedup + route) | Clean |
| `event_pipeline/dedup_port.py` | **Observe** (dedup infra) | Clean |
| `event_pipeline/normalized_event.py` | **Observe** (normalization) | Clean |
| `event_pipeline/dedup_keys.py` | **Observe** (key computation) | Clean |
| `evaluate_webhook/condition_evaluator.py` | **Decide** (condition matching) | Clean |
| `evaluate_webhook/safety_guards.py` | **Decide** (rate/concurrency policy) | Clean |
| `evaluate_webhook/EvaluateWebhookHandler.py` | **Decide** + **Execute** | **VIOLATION** |
| `aggregate_trigger/TriggerRuleAggregate.py` | Should be **Decide**, actually just **Record** | Underused |
| `dispatch_triggered_workflow/projection.py` | **Observe** + **Execute** | **VIOLATION** |
| `_wiring.py` BackgroundWorkflowDispatcher | **Execute** (fire-and-forget) | Clean |
| `routes/executions/commands.py` | **Decide** + **Execute** | Acceptable (API boundary) |
| `ExecuteWorkflowHandler.py` | **Execute** (template + processor) | Clean |
| `github_event_poller.py` | **Observe** (poll + normalize) | Clean |
| `check_run_poller.py` | **Observe** (poll + synthesize) | Clean |

## Two Boundary Violations

### 1. EvaluateWebhookHandler spans Decide and Execute

Lines 199-241 (`_fire_trigger`) collapse the boundary:
- Evaluates conditions and guards (Decide)
- Loads aggregate, issues RecordTriggerFiredCommand, saves (Execute)
- Records fire in query store, invokes on_fire callback (Execute)

**Severity**: Medium. The handler is the only call site for `record_fired`,
and policy logic inherently needs the query store. Co-locating command
issuance with policy evaluation is acceptable if the aggregate had its own
guards. The real problem is the aggregate has no guards at all.

### 2. WorkflowDispatchProjection spans Observe and Execute

This is the critical violation. A projection should be pure reconstruction.
This one calls `execution_service.run_workflow()` (line 148) - a side
effect that launches Docker containers and burns LLM tokens.

**Severity**: Critical. This is the root cause of the restart bug and the
primary three-way-split violation.

## Pollers: Facts or Commands?

**Pollers publish facts. This is correct.**

- Events API poller: normalizes GitHub events into `NormalizedEvent`,
  passes to `EventPipeline.ingest()`. Does not decide policy.
- Check-run poller: synthesizes `check_run.completed` events from Checks
  API data, passes to `EventPipeline.ingest()`. Does not decide policy.
- Webhook endpoint: normalizes payload into `NormalizedEvent`, passes to
  `EventPipeline.ingest()`. Does not decide policy.

All three sources converge at `EventPipeline.ingest()` with content-based
dedup keys. This is good architecture.

## Convergence Point

**Single convergence at `EventPipeline.ingest()`.**

All three event sources (webhook, Events API poll, Check-run poll) produce
`NormalizedEvent` objects with identical content-based dedup keys. The
pipeline handles dedup and routes to `EvaluateWebhookHandler`.

This convergence is clean. The same logical event from webhooks and polling
produces the same dedup key and is processed once.

## The Spaghetti Hub

**`WorkflowDispatchProjection`** is the spaghetti hub.

It mixes:
1. Event subscription (observe - reading TriggerFired events)
2. Read model maintenance (observe - writing dispatch records)
3. Workflow dispatch (execute - calling run_workflow)
4. Checkpoint management (observe - saving position)

It should only do #1, #2, and #4. Step #3 should be in a separate
Processor that reads the dispatch records (to-do list pattern).

**Secondary hub: `EvaluateWebhookHandler`** mixes policy evaluation with
command issuance and fire recording. This is less severe because the
co-location is defensible, but the aggregate should own more of the
invariants.
