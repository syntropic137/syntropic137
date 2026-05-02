# 01 - Ownership: Who Decides What

**Status:** COMPLETE

## Question

> "For each behavior in this system, which component is the single owner
> of the decision to trigger it?"

## Finding: The Aggregate Is Not the Decision-Maker

The AGENTS.md rule says: "Aggregates MUST be the decision-makers." But
`TriggerRuleAggregate.record_fired()` (line 221-237) does **zero
validation**. It emits `TriggerFiredEvent` unconditionally. The
`can_fire()` method exists (line 257-259) but is **never called** by
`record_fired` or by `EvaluateWebhookHandler`.

All policy decisions are in `EvaluateWebhookHandler` (application layer):
- Status check (line 107)
- Condition evaluation (line 109)
- Safety guards 1-7 (line 144)

**Risk**: If any other code path calls `record_fired()` directly, there
are no domain-level guards. The aggregate is a dumb event emitter.

## Ownership Map

### "Should this trigger fire?"

| Step | Owner | File:Line |
|------|-------|-----------|
| Status gate | EvaluateWebhookHandler | `EvaluateWebhookHandler.py:107` |
| Condition matching | condition_evaluator | `EvaluateWebhookHandler.py:109` |
| Safety guards (7) | SafetyGuards | `EvaluateWebhookHandler.py:144` |
| Record the fire | TriggerRuleAggregate | `TriggerRuleAggregate.py:221` (no guards) |

**Single owner for the decision: EvaluateWebhookHandler**
**Aggregate role: recorder only (violation of DDD principle)**

### "Should this workflow launch?"

**No single owner. Two independent paths:**

| Path | Entry | Validation | Guard |
|------|-------|-----------|-------|
| API route | `POST /workflows/{id}/execute` | GitHub App access, input validation, repo resolution | Moderate |
| Dispatch projection | `TriggerFired` event | `if not workflow_id` only | **Minimal** |

Both paths converge at `ExecuteWorkflowHandler.handle()`, but the
dispatch projection bypasses all API-level validation. If a trigger fires
with invalid inputs, the error surfaces deep inside the processor rather
than at the gate.

### "Has this workflow already been dispatched?"

**No owner. Nobody checks.**

- `WorkflowDispatchProjection`: no dedup (line 148, unconditional dispatch)
- `BackgroundWorkflowDispatcher`: no dedup (line 556, fire-and-forget)
- `ExecuteWorkflowHandler`: no dedup (creates new aggregate each time)
- `WorkflowExecutionAggregate.start_execution()`: checks `self.id is not None`
  but this is per-instance only - each dispatch creates a new instance
- Event store: no `ExpectedVersion.NoStream` guard on execution streams

## Trigger Fire Lifecycle

**There is no explicit trigger-fire state machine.**

The lifecycle is scattered:

| State | Where tracked | How |
|-------|--------------|-----|
| Fired | Aggregate event stream | `TriggerFiredEvent` |
| Dispatched | Projection store record | `dispatched_at` field |
| Running | TriggerQueryStore | `record_fire()` for concurrency guard |
| Completed | Execution aggregate | Separate bounded context |

**Missing**: A unified state machine (pending/fired/dispatched/running/
completed/failed) and domain events to close the lifecycle loop
(`TriggerDispatchCompleted`, `TriggerDispatchFailed`).

## Dual-Ownership Risks

1. **API route + dispatch projection** can independently launch workflows
   with different validation levels
2. **Aggregate has no guards** - anything calling `record_fired()` bypasses
   all policy
3. **No dispatch dedup** anywhere in the chain from TriggerFired to
   workflow execution
