# 02 - Replay Safety: What Survives Replay

**Status:** COMPLETE

## Question

> "Which handlers are replay-safe, and which produce side effects?"

## Critical Finding: WorkflowDispatchProjection

**This is the root cause of the restart bug.**

`WorkflowDispatchProjection` is a **process manager masquerading as a
read model projection**. It subscribes to `TriggerFired` events and calls
`BackgroundWorkflowDispatcher.run_workflow()` - a side effect that
launches Docker containers and burns LLM tokens.

### The replay path

```
Service restart
  -> SubscriptionCoordinator starts catch-up from minimum checkpoint
  -> WorkflowDispatchProjection receives historical TriggerFired events
  -> projection.py:98 calls _on_trigger_fired()
  -> projection.py:148 calls self._execution_service.run_workflow()
  -> BackgroundWorkflowDispatcher fires asyncio.Task
  -> Docker container launched, LLM called, money spent
```

### The checkpoint gap

```python
# projection.py:97-107
if event_type == "github.TriggerFired":
    await self._on_trigger_fired(event_data)     # DISPATCH at line 98
                                                   # (money spent here)

await checkpoint_store.save_checkpoint(...)        # CHECKPOINT at line 100
                                                   # (crash here = re-dispatch)
```

Dispatch fires BEFORE checkpoint is saved. If the process crashes between
line 98 and line 100, the event is replayed on restart and the workflow
fires again.

### Missing mechanism

**There is no concept of "replay mode" anywhere in the codebase.**

Searched for: `is_replaying`, `is_catch_up`, `replay_mode`, `catching_up`
- **Zero results.** The system cannot distinguish replay from live processing.

The `EventEnvelope` has no replay flag. The `CheckpointedProjection`
interface has no replay context. The `SubscriptionCoordinator` does not
track catch-up state.

### Three scenarios that cause re-dispatch

| Scenario | Likelihood | Severity |
|----------|-----------|----------|
| Checkpoint loss (DB recreated, dev reset) | High in dev, medium in prod | All historical triggers replay |
| Projection version bump | Medium (any code change) | Full replay from position 0 |
| Crash between dispatch and checkpoint save | Low per event, cumulative | One duplicate per crash |

## Handler Classification

| Component | File | Bucket | Violation? |
|-----------|------|--------|-----------|
| WorkflowDispatchProjection | `contexts/github/slices/dispatch_triggered_workflow/projection.py` | **Side-effect execution** disguised as **pure reconstruction** | **YES - critical** |
| EvaluateWebhookHandler | `contexts/github/slices/evaluate_webhook/EvaluateWebhookHandler.py` | Decision-making + command issuance | Acceptable (command issuance is the output of decision) |
| EventPipeline | `contexts/github/slices/event_pipeline/pipeline.py` | Fact observation + dedup decision | Clean |
| SafetyGuards | `contexts/github/slices/evaluate_webhook/safety_guards.py` | Decision-making | Clean |
| BackgroundWorkflowDispatcher | `apps/syn-api/src/syn_api/_wiring.py:544-614` | Side-effect execution | Clean (but no idempotency check) |
| Coordinator projections (other 20) | Various | Pure reconstruction | Clean |

## The Fix

Per the project's own architecture (Processor To-Do List pattern from
AGENTS.md):

1. **Make WorkflowDispatchProjection pure** - it should only write
   dispatch records to its projection store, never call `run_workflow()`
2. **Add a separate Processor** that reads dispatch records (to-do list)
   and fires workflows, with idempotency checks against the execution
   repository
3. **Short-term mitigation**: Add a replay guard - compare event's
   `global_nonce` against projection's checkpoint at construction time.
   Skip dispatch for events below the watermark.
