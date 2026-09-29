# ADR-014: Workflow Execution Model

## Status
Accepted

## Date
2025-12-04

## Context

The original data model conflated **Workflow Templates** (reusable workflow definitions) with **Workflow Executions** (individual runs of a workflow). This caused several issues:

1. **Metrics aggregation confusion**: Token usage and costs were accumulated at the template level, making it impossible to see metrics for individual runs
2. **Session orphaning**: Sessions belonged to workflows but couldn't be traced to specific executions
3. **History limitations**: No way to see execution history or compare different runs

### Original Model (Problematic)

```
WorkflowDefinition (Template)
├── id: "implementation-workflow-v1"
├── name: "Implementation Workflow"
├── phases: [research, innovate, plan, execute, review]
└── (metrics aggregated across ALL runs)  ← PROBLEM

Sessions
├── session-1 (phase-1, workflow: impl-v1)
├── session-2 (phase-2, workflow: impl-v1)
└── ... (no link to specific execution)   ← PROBLEM
```

## Decision

### 1. Separate Workflow Template from Workflow Execution

Introduce a clear separation between:

- **WorkflowDefinition**: Reusable template defining phases, agents, and configuration
- **WorkflowExecution**: Individual run of a workflow with its own metrics and state

### Target Model

```
WorkflowDefinition (Template)
├── id: "implementation-workflow-v1"
├── name: "Implementation Workflow"
└── phases: [research, innovate, plan, execute, review]

WorkflowExecution (Run)
├── execution_id: "exec-abc123"
├── workflow_id: "implementation-workflow-v1"
├── status: "completed"
├── started_at / completed_at
├── total_tokens, total_cost
└── phases: [
    ├── {phase_id: "research", status: "completed", metrics...}
    └── ...
    ]

Sessions
├── session-1 (phase: research, execution_id: "exec-abc123")
└── session-2 (phase: innovate, execution_id: "exec-abc123")
```

### 2. New Read Models

#### WorkflowExecutionSummary
```python
@dataclass(frozen=True)
class WorkflowExecutionSummary:
    """Summary for listing workflow executions."""
    execution_id: str
    workflow_id: str
    status: str  # pending, running, completed, failed
    started_at: datetime | None
    completed_at: datetime | None
    completed_phases: int
    total_phases: int
    total_tokens: int
    total_cost_usd: Decimal
```

#### WorkflowExecutionDetail
```python
@dataclass(frozen=True)
class WorkflowExecutionDetail:
    """Full detail of a workflow execution."""
    execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    phases: tuple[PhaseExecutionDetail, ...]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Decimal
    artifact_ids: tuple[str, ...]
    error_message: str | None
```

### 3. New Projections

| Projection | Purpose | Key Events |
|------------|---------|------------|
| `WorkflowExecutionListProjection` | List executions for a workflow | WorkflowExecutionStarted, PhaseCompleted, WorkflowCompleted, WorkflowFailed |
| `WorkflowExecutionDetailProjection` | Per-execution phase metrics | Same as above |

### 4. Session-Execution Linkage

Sessions now include `execution_id` to trace back to specific workflow runs:

```python
# SessionStartedEvent
class SessionStartedEvent(DomainEvent):
    session_id: str
    workflow_id: str
    execution_id: str | None  # NEW: Links to specific run
    phase_id: str
    ...
```

### 5. New API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/workflows/{workflow_id}/runs` | List executions for a workflow |
| `GET /api/executions/{execution_id}` | Get execution detail with phase metrics |

Existing endpoints updated:
- `GET /api/workflows/{id}` now includes `runs_count` and `runs_link`
- `GET /api/sessions` now includes `execution_id`

### 6. UI Flow

```
/workflows/{id}         → Template view with "Runs" card showing count
    ↓ Click "View Runs"
/workflows/{id}/runs    → List of all executions
    ↓ Click execution row
/executions/{exec_id}   → Execution detail with per-phase metrics
```

### 7. Resume - continuing an Execution that did not finish

**Added 2026-09-29.** Roughly fifteen code sites cite "ADR-014 s7"; until this
date the section they cited did not exist. It is written here in place rather
than in a new ADR, because it is part of the execution model this ADR defines.

An Execution is immutable once terminal. Resuming one therefore does NOT
restart it: it creates a SECOND Execution that inherits the first's completed
work and begins at the first phase that did not finish. The parent stays
terminal and its record stays true.

**What is resumable.** `FAILED` and `INTERRUPTED` only. Both ended without
anyone deciding the work should stop, so running the rest is what the operator
wanted all along. `CANCELLED` is a decision to stop - it may have been issued
because the run targeted the wrong repository or its task held a secret - so it
is resumable only when the request says `override_cancellation`, separately and
explicitly. `COMPLETED` has nothing left to run; `RUNNING` is still live, and
resuming it would put two runs on one piece of work; an Execution that never
started has nothing to inherit.

**What is inherited.** The parent's *contiguous* prefix of completed phases, in
phase order, with the artifact ids each produced. The prefix stops at the first
phase that did not complete, so a phase completed after a gap is NOT inherited:
the resume re-runs the gap, and that later phase's output was built on a
predecessor the resume will produce afresh.

**One resume per parent.** "Already resumed" is a fact about the parent, so the
parent stream's optimistic concurrency is what makes two concurrent requests
resolve to one. The loser gets 409 naming the winner.

**External effects.** When the phase the resume begins at had already started in
the parent without leaving evidence that it changed nothing outside its
workspace, re-running it may repeat a push or a publish. The request must say
`acknowledge_external_effects` before that is admitted, and the acknowledgement
is recorded so it is never indistinguishable from a phase that was safe.

**The event and the start are separate.** `ExecutionResumed` on the parent's
stream is the parent's decision and nothing more; the child does not exist yet.
`ResumeStartProcessManager` reads that event, creates the child's stream and
starts it through the same admission gate as any other execution. This keeps
the decision replay-safe and the start idempotent (ADR-025).

**Naming.** Until 2026-09-29 this was called "fork" in the code, and `resume`
meant un-pausing. Pause was deleted (nothing ever read its signal) and the name
was reassigned. `fork` is now reserved for a different, unbuilt operation:
starting a NEW run from an arbitrary point of a COMPLETED execution, the way a
git branch is taken from a commit. See
[docs/architecture/orchestration-ubiquitous-language.md](../architecture/orchestration-ubiquitous-language.md).

**API.** `POST /executions/{execution_id}/resume`, CLI `syn execution resume`.

## Consequences

### Positive
- Clear separation of concerns (template vs instance)
- Per-execution metrics enable comparison and debugging
- Sessions traceable to specific workflow runs
- Better UX with execution history

### Negative
- Additional projections to maintain
- Slightly more complex event model
- Migration needed if existing sessions lack execution_id (nullable field handles this)

### Neutral
- Follows existing event sourcing patterns
- Consistent with aggregate modeling principles
- No changes to existing WorkflowDefinition projection

## Entity Relationships

```
┌──────────────────┐      1:N     ┌─────────────────────┐
│WorkflowDefinition│─────────────▶│  WorkflowExecution  │
│  (Template)      │              │      (Run)          │
└──────────────────┘              └─────────────────────┘
                                           │
                                           │ 1:N
                                           ▼
                                  ┌─────────────────────┐
                                  │      Session        │
                                  │ (execution_id ref)  │
                                  └─────────────────────┘
```

## Related ADRs
- ADR-013: Event Sourcing Projection Consistency
- ADR-012: Artifact Storage
- **ADR-023: Workspace-First Execution Model** - Specifies how `WorkflowExecutionEngine`
  implements this model with required workspace isolation and event persistence
- **ADR-048: Workflows as Claude Code Commands** - Extends this model with input declarations,
  `$ARGUMENTS` substitution, and per-phase model overrides (ISS-211)

## Files Changed
- `packages/syn-domain/.../read_models/workflow_execution_summary.py` - New
- `packages/syn-domain/.../read_models/workflow_execution_detail.py` - New
- `packages/syn-domain/.../list_executions/projection.py` - New
- `packages/syn-domain/.../get_execution_detail/projection.py` - New
- `packages/syn-adapters/.../manager.py` - Updated event handlers
- `apps/syn-dashboard/.../api/executions.py` - New endpoint
- `apps/syn-dashboard/.../api/workflows.py` - Updated with runs_link
- `packages/syn-domain/.../SessionStartedEvent.py` - Added execution_id
- `packages/syn-domain/.../SessionSummary.py` - Added execution_id
