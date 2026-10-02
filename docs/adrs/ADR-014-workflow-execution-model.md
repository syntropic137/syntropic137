# ADR-014: Workflow Execution Model

## Status
Accepted. Revised in place 2026-09-26 (section 7) and 2026-10-02 (section 8).

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

This section covers only the platform's own link from a session to the
execution that started it. Which sessions an execution actually ran, including
subagents and resumed transcripts the platform did not start, is the session
inventory: see [ADR-071](ADR-071-session-inventory-and-discovery.md).

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
   `ProjectionControlStateAdapter.save_state` is a deliberate no-op and the
   state lives only in the events. Load and rehydrate the aggregate before
   every command, never the projection.

2. The fork start event carries no source-commit pin and provisions at HEAD.
   The execution then fails during the failing phase, which is now stale. A fork
   that starts against a different commit than it should is indistinguishable
   from a success until the phase is pushed and CI runs. Record the source
   commit on execution start (EVENT 1 in the lifecycle) and use it as the fork
   provision base, rather than HEAD.
starts it through the same admission gate as any other execution. This keeps
the decision replay-safe and the start idempotent (ADR-025).

**Naming.** Until 2026-09-29 this was called "fork" in the code, and `resume`
meant un-pausing. Pause was deleted (nothing ever read its signal) and the name
was reassigned. `fork` is now reserved for a different, unbuilt operation:
starting a NEW run from an arbitrary point of a COMPLETED execution, the way a
git branch is taken from a commit. See
[docs/architecture/orchestration-ubiquitous-language.md](../architecture/orchestration-ubiquitous-language.md).

**API.** `POST /executions/{execution_id}/resume`, CLI `syn execution resume`.

### 8. A phase's deliverable and its side effects are separate outcomes (2026-10-02)

Issue: #1474. Public guide: `apps/syn-docs/content/docs/guide/phase-outcomes.mdx`.

**The problem.** Section 2 gives an execution one `status`. A phase does two
different kinds of thing, and one word cannot describe both: it produces a
DELIVERABLE (a report, a patch, a pushed branch), and it attempts SIDE EFFECTS
around it (a PR comment, a label, a push to a protected branch). Collapsed into
`status`, a phase whose analysis was finished and whose PR comment was then
refused looked identical to a phase that produced nothing. Operators re-ran
finished work to retry a write, and a failed run whose work survived read as
"nothing to see".

**Decision.** The phase outcome is three separate facts, and none of them is
derived from another.

| Fact | Who states it | Decides completion? | Where it is read |
|---|---|---|---|
| `success` | the agent, in its TASK_RESULT block | yes, together with the exit status and the artifact rule | phase and execution `status` |
| `side_effects` (`none` / `succeeded` / `denied` / `failed`) | the agent | **never** | `reported_side_effects` per phase and per execution |
| a stored artifact | the platform, by collecting `artifacts/output/` or recovering the last message | yes, a phase with no artifact fails | `deliverable_produced` on the execution, `deliverable_recovered` per phase |

1. **`success` is about the deliverable, not every action around it.** The
   prompt contract says so explicitly: a phase that produced its deliverable
   and was then refused a write reports `success: true, side_effects: denied`
   (`execute_workflow/workspace_prompt.py:350-364`). Completion is refused only
   on a FAILURE or UNREADABLE verdict (`phase_verdict.py:414-416`); the
   side-effects word is not consulted.
2. **`side_effects` is a report, never a measurement.** It is parsed leniently
   at the trust boundary (an unknown word is logged and stored as not reported,
   `value_objects.py:330-345`), carried on `AgentExecutionCompleted` and then
   on `PhaseCompleted` (`WorkflowExecutionAggregate.py:537`, `:589`). Nothing
   verifies it. A phase that FAILED does not complete, so its word is not
   recorded; this is accepted, because a failed phase's status already tells
   the operator to look.
3. **The execution-level side effect is the most severe phase report**,
   FAILED > DENIED > SUCCEEDED > NONE, or null when no phase reported one
   (`value_objects.py:348-358`, `workflow_execution_detail.py:328-335`). A
   refused write in one phase is not hidden by another phase's success.
4. **`deliverable_produced` is independent of `status`.** It is true when any
   phase this execution ran stored an artifact
   (`workflow_execution_detail.py:316-326`). Phases that fail or are interrupted
   keep their output before teardown (`WorkflowExecutionProcessor.py:758-769`,
   `:797-800`; `ArtifactCollector.collect_from_unfinished_phase`), so `failed`
   with `deliverable_produced: true` is a real and common state: the run failed
   and there is work to read.
5. **Every phase produces an artifact (#1195, #1300, #1479).** A phase that
   wrote no collectable file, or an empty one, has its last message recovered
   as a marked artifact if it says something a later phase could act on, and
   fails otherwise (`ArtifactCollector.py:640-720`,
   `artifact_recovery.py:224-319`). This is what makes `deliverable_produced`
   meaningful: an artifact exists for every phase that completed.
6. **The agent's failure word is kept apart from the platform's measurement
   for the same reason.** `reported_failure_reason` records what the agent
   wrote; `failure_classification` is what the platform concluded, and the
   agent's word may only withdraw a claim (`unknown` -> `unclassified`), never
   add one (`phase_verdict.py:482-528`). This predates #1474 (#1357, #1392)
   and is restated here because it is the same split: report beside
   measurement, never one overwriting the other.

Both execution-level fields are scoped to the phases the execution ran. A
resumed execution's inherited phases (section 7) are reported on the parent.

**Rejected alternatives.**

- *A new execution status such as `completed_with_warnings`.* It would make
  `status` carry the side-effects fact again, every consumer that switches on
  `status` would need a new branch, and it cannot express `failed` with a
  surviving deliverable.
- *Failing the phase when `side_effects` is `denied` or `failed`.* That throws
  away finished work to report a permission problem, which is the defect being
  fixed. It would also let an unverified agent report decide completion.
- *Verifying side effects by observing GitHub.* Desirable, and not this
  decision: it is a measurement that would sit beside the report, not replace
  this split.

**Consequences.** Operators read three fields instead of one. The API exposes
them (`GET /executions/{execution_id}`, `apps/syn-api/src/syn_api/routes/executions/queries.py:685-740`);
the CLI does not yet render them (#1501 item A).

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
- **ADR-071: Session Inventory and Discovery** - Which sessions an execution ran, beyond the
  platform-started session linked in section 4
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
