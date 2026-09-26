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

### 7. Resuming a terminal execution is a FORK, not a mutation (2026-09-26)

An execution that reached `FAILED`, `CANCELLED` or `INTERRUPTED` is terminal and
stays terminal. Resuming it creates a **new execution** with a new id that
records its parent, inherits the parent's contiguous prefix of completed phases
and their artifacts, and begins at the phase that did not finish. The parent is
never rewritten.

This extends the separation this ADR already draws. A template is reusable, an
execution is one run, so a resume is a NEW run that knows where it came from -
not a second pass over an existing run's history. Sections 1-6 did not address
terminal states at all, so nothing above is contradicted.

**Why a fork rather than reopening the phase in place.** Reopening keeps one
stream and needs no new identity, which is cheaper on paper. It also rewrites
the history of a run someone has already read, and makes "what did execution X
do" unanswerable afterwards. A fork keeps the audit trail intact and makes a bad
resume visible as its own row rather than entangled with the original.

**Ownership.** The PARENT aggregate decides whether a fork may exist and records
`ExecutionForked` on its own stream. "Already forked" is a fact about the parent,
and the parent stream's optimistic concurrency is the only race-free place to
enforce it. Admission MUST NOT be decided from a projection - see the fail-opens
below.

**What is inherited.**

| | Inherited | Measured |
|---|---|---|
| Completed phases (contiguous prefix) | yes, as `PhaseInherited` | - |
| Their artifacts, by id | yes, ATTRIBUTED TO THE FORK | EXP2 |
| The operator's inputs and task text | yes, byte-identical | EXP3 |
| The rendered phase prompt | **no** | EXP3 |
| The failed phase's work | no - it restarts from its beginning | - |
| In-phase reasoning context | no, and this is a stated gap | - |

**Artifact references are attributed to the fork at creation.** The tempting
design is "artifacts are addressed by id, so a fork just names the parent's
ids". Measured against this codebase, that does not work: the prior-phase
injection path resolves artifacts THROUGH THE CONSUMING EXECUTION, so a fork
naming a parent's artifact id receives nothing. Relinking the row to the fork
makes injection succeed, which identifies the read path - not the id - as the
constraint. The fork's opening append therefore attributes references to the
inherited ids to itself. Artifacts remain immutable and are not copied; only the
reference is new.

This also removes a hazard a review raised. If the fork resolved inherited
artifacts by querying the artifact list projection at start time, a projection
that is merely LAGGING is indistinguishable from a deleted artifact, and a
one-fork-per-parent rule would let that lag permanently consume the parent's
only fork. Writing attribution at creation keeps the decision on the event
stream, where lag cannot reach it.

**The rendered prompt is not reproducible, and the contract says so.** The
inputs round-trip byte-identically through the event store. The rendered prompt
does not: the execution id is interpolated into it, so a fork re-rendering the
same template differs from its parent by exactly that id. The `prompt_template`
text is also absent from the start event, so a template edited between runs
diverges further. The contract is "same inputs, re-rendered per fork", not "same
prompt".

**Which parents are forkable.**

- `FAILED`, `INTERRUPTED`: yes.
- `CANCELLED`: only on an explicit, separate operator action. A cancel is an
  instruction to stop; treating it as another retryable terminal label defeats
  it. The harm is concrete: an execution cancelled because it targeted the wrong
  repository, or because its task carried a secret, must not be re-runnable by a
  second operator or a queued retry without a fresh decision. Re-validate
  repository authorization and inputs at that point, and never include
  `CANCELLED` in automatic recovery.
- `COMPLETED`, `RUNNING`, `PAUSED`, `NOT_STARTED`: not forkable.

**A phase's failure is not a boundary for its external effects.** A phase can
push a branch or open a pull request and then fail before its completion event
is recorded, so re-running it from the beginning can repeat a non-repeatable
effect. The intra-phase retry path already refuses on exactly this basis,
permitting a retry only when the prior attempt did nothing observable. A fork
applies the same rule: where the failed attempt left evidence of external
effects, or left no readable evidence either way, the aggregate refuses unless
the request acknowledges it.

**Two fail-opens found while validating this, to be closed before a fork
endpoint ships.** Both are pre-existing and independent of forking:

1. The resume controller decides from the execution detail PROJECTION and never
   loads the aggregate. Against a rehydrated `CANCELLED` execution the aggregate
   rejects all twelve of its commands; the controller, reading a projection row
   that still says `paused`, returns success and queues a resume signal.

   SCOPE THIS PRECISELY. The control state is not an independent mutable store:
   `ProjectionControlStateAdapter.save_state` is a deliberate no-op and
   `get_state` reads the event-derived detail projection. So the divergence is
   not arbitrary injection - the experiment hand-set the row, which production
   cannot do. The reachable window is PROJECTION LAG: the aggregate records the
   cancel, the projection has not caught up, and a resume is admitted against an
   execution the aggregate would refuse. Narrow, but real, and it is the window
   a terminal-state guard exists to close. A guard is worth only as much as the
   staleness of what it reads.
2. `stream_exists` returns `False` when the event store is UNREACHABLE, which is
   indistinguishable from "no such stream". A pre-dispatch existence check built
   on it passes when it cannot see, so it must fail closed.

**Evidence.** Claims marked "measured" come from four experiments run against
this codebase rather than reasoning about it, kept in
`docs/experiments/resumability-fork/`: 200-way concurrent appends confirming
that optimistic concurrency and `NoStream` each admit exactly one writer, and
failing when `expected_version` is dropped so the guard is shown to be
load-bearing; a fork holding a parent's artifact id receiving nothing from the
injection path; the task surviving a round trip while the rendered prompt does
not; and every aggregate command refused on a rehydrated cancelled execution
while the HTTP route was not.

**Deliberately unsolved.** Continuation WITHIN a phase. A fork restarts the
unfinished phase from its beginning, so whatever reasoning context it had
accumulated is lost. Bounding that loss is a separate concern, not decided here.

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
