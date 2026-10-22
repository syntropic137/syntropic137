# Final plan: capability matching on claim for a mixed fleet (owner decision 2026-10-14)

**Scope.** Docs only. The work edits two plan files in place on branch
`docs/runtime-research-20261012` (PR #1874):

- `docs/plans/20261014_pool-priority-placement.md`
- `docs/plans/20261013_selfhosted-microvm-pool.md`

There are no source changes. This plan is self-contained: whoever approves it does not need the
research, the first plan or the review.

**What this phase did and did not do.** This phase had only Read/Grep/Glob/Write: no git and no
shell. It wrote this file only. It did **not** edit the #1874 docs, commit or push. Those are the
implement phase's job, which executes §9. Every citation to `main` below was re-read in this phase
at `main` = `1ffef8404`. Citations marked **@#1874** (branch `origin/docs/runtime-research-20261012`
at `f5ddc382`) or **@#1931** (`feat/executor-pools-pr0-pr1` at `0ef4ea3fd`) come from the research
and the review. I could not open those refs, so the implementer must re-read each one before
editing.

---

## 1. The problem

**Today: any live executor with room claims the oldest admitted run.**

- Claim locks its own budget row (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:125-127`).
- It then filters runs only on `state='admitted' AND retry_at<=clock_timestamp() AND writer_epoch<=$2`,
  ordered `admitted_at,execution_id ... FOR UPDATE SKIP LOCKED LIMIT 1`
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:140-143`).
- No run carries a requirement.

**Why that fails in a mixed fleet.** Take flywheel (the VPS, `docs/north-star.md:11`) running
containers alongside KVM boxes running microVMs. Flywheel would claim work that needs nested Docker
or microVM isolation, and run it under weaker isolation than it asked for.

**What the docs on #1874 say now:**

- **MicroVM plan, decision 4** recommends retiring flywheel as an executor (@#1874
  `docs/plans/20261013_selfhosted-microvm-pool.md:464-467`). The owner rejected that on 2026-10-14.
- **The placement plan** already designs a matching predicate. But a run that no registered pool
  satisfies "stays `admitted`, counted as `unplaceable`" (@#1874
  `docs/plans/20261014_pool-priority-placement.md:93`, `:416`). The caller then sees RUNNING +
  `queued: true` (ADR-072 D11, `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:591-598`)
  with no end and no reason.
- **The requirement source is open** as placement-plan decision D4: "workflow YAML / metadata /
  trigger" (@#1874 `:920-921`).

**What the owner decided:**

1. The VPS stays an executor.
2. A workflow or phase declares what it needs. An executor claims only work it can satisfy.
3. A run no executor can ever satisfy fails fast, with a clear error. It does not queue forever.

**Naming collision.** "D4" in the brief is the placement plan's decision D4 (requirement source).
It is not ADR-072 D4, which is lease timing
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:241`). It is also not the microVM
plan's "decision 4", which is a third numbering. This plan writes each one out in full.

---

## 2. The requirement model (placement plan §3; closes D8)

### `RunRequirements`

`RunRequirements` is a frozen, `extra="forbid"` Pydantic model. It lives in
`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py`, beside
the `Capability`, `IsolationLevel`, `ExecutorPool` and `PoolId`/`RegionId`/`ProviderId` values that
#1931 adds there. It keeps the placement plan's existing fields (@#1874 `:377-400`) and adds `pools`.

| Field | Type | Empty means | Satisfied by pool `p` when |
|---|---|---|---|
| `min_isolation` | `IsolationLevel` (`CONTAINER=10 < MICROVM=30`) | `CONTAINER` | `p.isolation >= min_isolation` |
| `capabilities` | `frozenset[Capability]` | none | `capabilities ⊆ p.capabilities` |
| `regions` | `frozenset[RegionId]` | any | `p.region ∈ regions` |
| `pools` | `frozenset[PoolId]` (**new**: the owner's "location/pool") | any | `p.pool_id ∈ pools` |
| `providers` | `frozenset[ProviderId]` | any | `p.provider ∈ providers` |

**Isolation is an ordered minimum, not an equality (closes placement-plan D8).**

- A MICROVM pool may take CONTAINER work. Otherwise the KVM boxes sit idle while flywheel queues.
- The gaps in the integers leave room for a later level (for example gVisor at 20) without
  renumbering.

**Capability is an enum. v1 has `NESTED_DOCKER` only.**

- Platform code must understand every member.
- **No `GPU` in v1.** A `GPU` member would let a run claim a GPU host while nothing passes devices
  into the workspace container. Passing devices through is image and harness work in
  agentic-workspace (CLAUDE.md, "Where does this change belong?").
- GPU arrives later as one enum member plus a backend that honours it. This is flagged for the
  owner in §12.

**Region, pool and provider are operator slugs, not enums.** They are operator data, not platform
vocabulary.

**Harness fields are not placement.** `agent.provider` and `agent.sandbox`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:259`,
`:271`) stay out of placement, as the placement plan already says (@#1874 `:446-449`).

### Operations on the model

**`combine`** merges two requirements:

- the max of the isolations;
- the union of the capabilities;
- the intersection of each non-empty slug set.

An empty intersection of two non-empty slug sets is a contradiction. The YAML loader refuses it
when the workflow is authored.

**`assess(pools: Sequence[ExecutorPool]) -> PlacementAssessment`** is new; it replaces the first
plan's `satisfied_by` and the review's I2 is the reason. It returns two things:

- `satisfying: tuple[PoolId, ...]`;
- `mismatches`: for each pool that fails, the first clause it fails, as a typed value. For example:
  `flywheel: isolation container < microvm`.

`satisfied_by(pool)` is kept as the one-pool special case, `bool(assess([pool]).satisfying)`.
The error message is derived from the same clauses that decide the match. No second matcher is
written for diagnostics.

### Placement is per execution, not per phase

The run queue leases a whole execution: `execution_runs` has one row per `execution_id`
(`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:107`).

- A phase may *declare* a requirement. Its only effect is to raise the whole execution's
  requirement through `combine`.
- Running different phases of one execution on different executors would need a run per phase.
  That is out of scope, and the docs say so plainly.

---

## 3. Where requirements are declared: D4 resolved as **workflow YAML**

### Declaration

- Add an optional `requires:` block on the workflow root, `WorkflowDefinition`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:745`).
- Add the same block on `PhaseYamlDefinition`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:352`).
- Both models are `extra="forbid"`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:366`, `:755`).
- The loader `combine`s the workflow block and every phase block into **one** `RunRequirements`
  when it parses the YAML.

### Storage: one combined value at the top level of the template event

- Add `run_requirements: RunRequirements | None = None` to `WorkflowTemplateCreatedEvent`. This
  follows the defaulted-field pattern already used there
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/WorkflowTemplateCreatedEvent.py:48-92`).
- **Not per phase in template `PhaseDefinition`.** That model is `ConfigDict(frozen=True)` and so
  ignores unknown fields
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/value_objects.py:131-143`).
  An older API rehydrating a newer template would silently **drop** a per-phase requirement.
- A top-level field on a `DomainEvent` is different. `DomainEvent` is `extra="forbid"`
  (`lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/event.py:31`), so an
  older reader fails **loudly** instead.
- What is lost: the record of which phase asked for what. That is acceptable while placement is per
  execution. Per-phase placement, if it ever comes, brings its own field.

### Pinned at start and carried through resume (review B3)

Adding a field to `StartPins` is not enough on its own. Every handoff copies fields explicitly, so
the implementer must name each one. The full chain:

| # | Handoff | Where (main) |
|---|---|---|
| 1 | `StartExecutionCommand` gains `run_requirements` | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py:43` |
| 2 | The processor passes it in when it builds the start command, from the template | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:375-388` (and `ExecuteWorkflowHandler`, which loads the template) |
| 3 | `WorkflowExecutionStartedEvent.run_requirements: RunRequirements \| None = None` | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/WorkflowExecutionStartedEvent.py` (beside `pinned_phases`, `:79`) |
| 4 | `StartPins.run_requirements` | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/start_pins.py:76-98` |
| 5 | Event → pins on replay: `read_start_pins` reads it. Absent means empty, so a pre-change execution replays unconstrained, which is how it actually ran | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/start_pins.py:235-248` |
| 6 | Parent pins → `StartResumeCommand`: `resume_start_command` copies `pins.run_requirements` | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_start.py:140-155` |
| 7 | `StartResumeCommand.__init__` gains the field | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py:78-114` |
| 8 | Command → the child's start event: `resume_started_event` writes it | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_start.py:184-199` |
| 9 | `reserve(execution_id, writer_epoch, requirements, *, is_resume)` writes it to the run row, taken from `aggregate.start_pins`, for a fresh start and a resume alike | port `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:126`; adapter `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:104-114`; caller `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/run_reservation.py:45`, `:69` |

**A resume inherits its parent's pinned requirement, never the template's current one.** This is
the same rule `workflow_version` already follows
(`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/start_pins.py:96-98`,
`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_start.py:154`).

### Older installs and `extra="forbid"`

| Old component | Meets | Outcome | Acceptable because |
|---|---|---|---|
| An older `syn`/API parsing YAML | a `requires:` key | the whole workflow is refused: "extra fields not permitted" | Fail fast beats running on the wrong host. The docs name the minimum version in that error's troubleshooting entry. |
| An older API process | a template event carrying `run_requirements` | the event fails to load | It is loud, and it is the price of not silently dropping the field. |
| An older executor | a start event with `run_requirements` | it never claims the run | The start-event schema changes, so `ORCHESTRATION_EVENT_EPOCH` goes 1→2 (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:13`). Claim already filters `writer_epoch<=` the host's epoch (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:142`). Deploy order: upgrade executors first (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:483-484`). |

**Caveat: nothing enforces the bump yet.** ADR-072 D9 specifies a fitness function that fails an
unbumped schema change (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:479-481`).
The epoch module says it is "not built yet (#1310 Phase 1)"
(`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:4-6`). So the
bump is a reviewed manual step in PR4, pinned by a test. See §11.

### Rejected sources

- **Trigger.** `TriggerConfig` holds safety limits only
  (`packages/syn-domain/src/syn_domain/contexts/github/domain/aggregate_trigger/TriggerConfig.py:12-30`).
  It is also the wrong owner:
  - what a workflow needs does not depend on what fired it;
  - HTTP and CLI starts have no trigger;
  - two triggers for one workflow would be two places that must agree, with nothing making them.
- **"Metadata".** No metadata surface exists apart from YAML. Phase frontmatter is a separate
  `extra="forbid"` schema
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:699-710`).
  A new surface would be a third format for one field.
- **Reusing `tags`** (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:799-801`).
  That turns free-form labels into stringly-typed semantics, and a typo would mean "any host".
- **A start-time override** (a CLI flag or API field) is **deferred, not rejected.** It would
  `combine` with the template's value, so it could only tighten placement. It needs an API type
  change through `just codegen`.

---

## 4. Claim: match without breaking priority and overflow order (placement plan §2/§3, @#1874 `:281-326`)

**New columns on `execution_runs`:**

- `min_isolation SMALLINT NOT NULL DEFAULT 10`;
- `capabilities TEXT[] NOT NULL DEFAULT '{}'`;
- `regions`, `pools` and `providers`, each `TEXT[] NOT NULL DEFAULT '{}'`.

The defaults are the empty requirement, so existing rows stay claimable.

**One predicate.** `{SATISFIES}` is one SQL constant, parameterised by a run alias and a pool alias:

```
r.min_isolation <= p.isolation
AND r.capabilities <@ p.capabilities
AND (cardinality(r.regions)   = 0 OR p.region   = ANY(r.regions))
AND (cardinality(r.pools)     = 0 OR p.pool_id  = ANY(r.pools))
AND (cardinality(r.providers) = 0 OR p.provider = ANY(r.providers))
```

**Where it goes in claim.** The candidate CTE
(`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:140-143`) joins the claiming
host's own pool through `execution_budget.pool_id` (#1931). Its filter becomes:

```
state='admitted' AND retry_at<=clock_timestamp() AND writer_epoch<=$2
AND ( {SATISFIES r, own}                                          -- runnable here
   OR NOT EXISTS (SELECT 1 FROM executor_pools p WHERE {SATISFIES r, p}) )  -- unplaceable anywhere
ORDER BY admitted_at, execution_id FOR UPDATE SKIP LOCKED LIMIT 1
```

The `RETURNING` gains `'unplaceable', NOT {SATISFIES r, own}`. The second branch is how an
admitted run that became unplaceable is failed; §5 explains it.

**Ordering is unchanged among the runs a host can take.**

- Matching filters *before* `ORDER BY admitted_at, execution_id`. So a host never takes a run it
  cannot satisfy.
- A run a host cannot satisfy does not block the head of that host's queue. Flywheel skips a
  MICROVM run and takes the next CONTAINER run.
- ADR-072 D3 is unchanged. The host locks only its own budget row
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:163-179`).
- Claim reads `executor_pools` rows and never locks them.

**Overflow: keep the existing capability-aware predicate (review I1).** The placement plan already
holds back a lower-priority pool only for a higher-priority executor that meets all of these
(@#1874 `:265`, `:299`, `:322`):

- it satisfies the run;
- it meets the run's writer epoch;
- it is heartbeating;
- it is claiming with room;
- it was not recently full.

Revise that predicate. Do not replace it.

- Its satisfies-clause becomes the shared `{SATISFIES}` constant.
- Its `higher` CTE must also project `pool_id` (@#1874 `:300`). The new `pools` clause needs it.
- An idle, dead or full higher pool must still never suppress overflow. That property already
  exists and must survive the edit.

The first plan's shorter "EXISTS a higher-priority pool that satisfies" would have let a dead
flywheel hold MICROVM-compatible CONTAINER work back for `overflow_delay_s`. That form is withdrawn.

**The memory double runs the same scenario table.** The double
(`packages/syn-adapters/src/syn_adapters/execution_runs/memory.py`) calls
`RunRequirements.satisfied_by`. One scenario table runs against both adapters (@#1874 `:322-326`).
That table is what keeps the SQL and the Python identical.

---

## 5. Fail fast: a run no executor can ever satisfy (review B1, B2)

### What "can ever satisfy" means

It means a **defined pool**: an `executor_pools` row. #1931 inserts and updates those rows but
never deletes them (@#1931 `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:58`,
`:75`, `:309-340`).

- It does **not** mean a *live* pool. Judging by liveness would let a restarting KVM box fail
  microVM work spuriously.
- A defined pool with no live member is a capacity problem, not a contradiction. Its runs wait, as
  ADR-072 D11 already allows, and the placement report counts them `starved`.
- #1931 seeds a `default` pool row (@#1931 `packages/syn-adapters/src/syn_adapters/execution_runs/schema.sql:24-48`).
  It is CONTAINER with no capabilities, so the empty requirement is always placeable. That is why
  PR3 can ship before any producer exists.

### The shape of the guarantee

There are two layers, and the layering is what makes the guarantee implementable.

**1. Precheck, before anything is accepted.** This is the common case: a synchronous, clear refusal
with no execution ever created.

**2. Settlement, after acceptance.** Anything that becomes unplaceable once accepted is failed
**only where an execution stream already exists**. It is recorded as an ordinary FAILED execution
with the same message.

There is **no** placement refusal at `reserve`. The first plan's three-way `reserve` outcome is
withdrawn, and the review's B1 is why:

- `reserve` runs before `journal.open`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/run_reservation.py:68-79`).
- In run-queue mode `_run_started` returns before `_drain`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:430-437`).
- `_drain`'s handler is the only thing that records a failure
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:533`, `:574-594`).
- So a refusal raised at `reserve` would have no stream to record FAILED in. It would recreate the
  "ghost execution" the route's docstring warns about
  (`apps/syn-api/src/syn_api/routes/executions/commands.py:533-537`).

`reserve` only writes the requirement columns. Its duplicate-start logic, which decides a
duplicate from the stream rather than the row, is untouched
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/run_reservation.py:31-50`).

### Layer 1: `require_placeable(requirements, catalog)`

`require_placeable` is a domain function beside `validate_phase_declarations`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py:188-222`).
It works over a new read port, `PlacementCatalog.defined_pools() -> list[ExecutorPool]`.

- The Postgres adapter is a plain `SELECT` over `executor_pools`.
- Matching happens in Python, through `RunRequirements.assess`.
- It raises `UnplaceableRunError`, naming the requirement, every defined pool, and the first clause
  each pool fails.

It runs at the **acceptance points only**: every place where, today, nothing has yet been written.

| Entry point | Where (main) | Outcome |
|---|---|---|
| HTTP `POST /execute` | in `_validate_execution_request`, beside `_check_phase_declarations` (`apps/syn-api/src/syn_api/routes/executions/commands.py:692`) | **422**. It runs before `record_execution_request` (`apps/syn-api/src/syn_api/routes/executions/commands.py:817`), so no request record and no execution id exist. |
| Trigger dispatcher | `validate_stored_declarations` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py:610-623`), called at `apps/syn-api/src/syn_api/_wiring_admission.py:509`, `:609`, `:646` | The dispatch is recorded `failed`, not `dispatched`. It gains a placement check against the template's stored `run_requirements`. |
| Resume `POST /executions/{id}/resume` | after `refuse_resume_start` and before `executions.save(parent)` (`apps/syn-api/src/syn_api/routes/executions/resume.py:151-163`) | **409**, like every other resume refusal (`apps/syn-api/src/syn_api/routes/executions/resume.py:98-99`). It checks the **parent's pinned** requirement, never the template's, so the parent's one resume is not spent. |

**No placement check at the handler boundary.** `_get_executable_phases`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py:643-658`)
gets none. A refusal there comes before the stream, which is exactly B1's ghost. A direct
in-process caller that skipped the route is settled by layer 2 instead, with a real FAILED
execution.

### Layer 2: settlement where a stream exists

Two execution modes need covering. `run_queue_enabled` defaults to **off** on main
(`packages/syn-shared/src/syn_shared/settings/execution.py:95-103`). None of the earlier documents
covered the inline mode.

**Run queue on: the unplaceable claim (§4).**

- Any live executor with room and a new enough epoch claims an admitted run that no defined pool
  satisfies. It gets `ClaimedRun.unplaceable=True`, a new defaulted field on the frozen model
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:52-59`).
- `run_claimed`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:470-512`)
  reloads the aggregate. The stream exists, because claim sees only `admitted` rows and promotion
  happens after `journal.open`.
- For an unplaceable run it short-circuits before any provisioning. It reads
  `aggregate.start_pins.run_requirements` and the catalogue, builds `UnplaceableRunError` through
  `assess`, and records it through the existing failure path, `_fail_execution` →
  `record_failed_execution`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/failed_execution.py:65`).
- The claimer then `close`s the run row.
- No new aggregate, event type or execution status is added. ADR-072 D11's "no new domain status"
  holds.

**Run queue off: the inline drain.**

- `_drain` runs `require_placeable` against the admitting process's own pool, as the first step
  inside its `try`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:533`).
- A raise there is recorded FAILED by the existing handler (`:574-594`).
- In this mode the catalogue is that one implicit local pool. It is CONTAINER, with capabilities
  from the backend adapter's report (PR2), and is the same pool the layer-1 prechecks use.

### Why this closes every race the review found (B2)

The unplaceable branch is evaluated at **claim time**, against the catalogue as it is then. So
however a run became unplaceable, the first executor to look at it fails it:

- reserve → pool redefined → promote;
- promotion by the opening sweep
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:266`, via `_promote` at
  `:323-331`, which accepts `opening` and `abandoned`);
- a deferred run returning to `admitted`
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:181-191`);
- two pools redefined concurrently;
- a resume child whose last compatible pool changed after the resume route checked it.

This needs:

- no cross-pool lock;
- no lock on pool rows in `reserve`;
- no stranding guard on the pool upsert.

The first plan's "`PoolDefinitionConflict` when an admitted run would be stranded" is
**withdrawn**. As the review showed, it covered only `admitted` and could not serialise across
pools.

The settlement rides the existing lease machinery (renew, fence, reconcile). A crash in the middle
of a refusal therefore leaves an expired lease, which is reconciled like any other run. The
refusal is idempotent: failing an execution that is already FAILED is refused by the aggregate.

**What the guarantee now says, honestly:**

- A run that no defined pool satisfies **when it is accepted** is refused synchronously: 422, 409,
  or a `failed` dispatch.
- A run that becomes unplaceable **after** it is accepted is failed, with the same message, by the
  next executor to claim with a free slot.
- It never waits indefinitely while any executor is live.
- If every executor is full, the refusal waits for the next free slot.
- If no executor is live at all, nothing runs anywhere, which is D11's existing starved state.

### Cost, stated

The unplaceable branch puts a read-only `NOT EXISTS` over `executor_pools` into the claim scan. It
is evaluated only for rows the host's own pool cannot satisfy, and `executor_pools` is tens of rows
at the north-star scale. The placement report watches claim latency p95 (§11).

---

## 6. ADR-072 amendment text

**Where the text lives.** D13 exists only on #1931
(@#1931 `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:666-702`).

- The placement plan's §6 holds the proposed ADR text (@#1874 `docs/plans/20261014_pool-priority-placement.md:615-648`).
  That §6 is edited in place on #1874.
- #1931 adopts the same text (§7).

**What it replaces:**

- D13's "A run no executor may take stays `admitted`" (@#1931 `:685-686`);
- the plan's "stays `admitted`, counted as `unplaceable`" (@#1874 `:93`, `:416`).

> **D13 (amended 2026-10-14). Placement is capability matching on claim.** A workflow declares
> `requires:` in its YAML, at workflow or phase level. The loader combines them into one
> `RunRequirements`: minimum isolation, required capabilities, and allowed regions, pools and
> providers. The template event stores it. The start pins it, and a resume inherits its parent's
> pin, never the template's current value. `reserve` writes it to the run's row. An executor claims
> a run only if its own pool satisfies the run's requirements. The predicate is one SQL constant,
> shared by claim, overflow and the placement report. `RunRequirements.assess` mirrors it, and one
> scenario table holds the two to the same answers. Among the runs a host can satisfy, the order is
> still `admitted_at, execution_id`. A higher-priority executor holds a run back from overflow only
> if it satisfies that run and is live, claiming and has room. Isolation is a minimum
> (`CONTAINER < MICROVM`): a stronger pool may take weaker work, never the reverse. Placement is per
> execution. A phase's requirement raises its whole execution's requirement.
>
> **A run no defined pool can satisfy is refused, never queued.** "Defined" means an
> `executor_pools` row, whether or not it has a live member. At acceptance the refusal is
> synchronous: `POST /execute` answers 422, a resume answers 409 without spending the parent's
> resume, and a trigger dispatch is recorded `failed`. A run that becomes unplaceable after
> acceptance is claimed by any live executor as `unplaceable` and recorded FAILED through the
> ordinary failure path. Every refusal names the requirement and why each defined pool fails it. No
> refusal is made before the execution's stream exists, except at acceptance, where nothing has
> been written yet. A run whose satisfying pools have no live member waits, as D11 describes, and
> is reported as starved.
>
> **Old code.** An older `syn` refuses a workflow that declares `requires:` (`extra="forbid"`). An
> older API cannot load a template that carries requirements. Pinning requirements bumps
> `ORCHESTRATION_EVENT_EPOCH`, so no executor that predates matching claims a run admitted after the
> bump (D9). Upgrade executors first.
>
> **Mixed fleet.** The container VPS stays an executor beside microVM pools. Matching, not fleet
> homogeneity, keeps work off a host that cannot honour it.

**D3 prose.** D3 still says ``backend (`local` today)``
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:153`). #1931 replaces that
column with `pool_id`, so #1931 should update this sentence in the same PR. #1874 does not touch
the ADR.

---

## 7. Effect on the placement plan's PR table (§7, @#1874 `:679-689`)

| PR | Change |
|---|---|
| **PR0+1 = #1931 (in review)** | **Code: no change needed.** `Capability`, `IsolationLevel`, `ExecutorPool`, `executor_pools.isolation/capabilities`, the seeded `default` pool and the pool upsert are exactly the foundation. The first plan's upsert stranding guard is withdrawn (§5), so the upsert needs nothing new. **Docs: changes needed before merge.** (a) D13 adopts the §6 text in place of "stays `admitted`". (b) In `docs/architecture/orchestration-ubiquitous-language.md`: *Unplaceable* = "no defined pool satisfies the run's requirements; refused at acceptance, or failed by the first executor to claim it after acceptance"; *Run Requirements* = "declared in workflow YAML (`requires:`), combined per execution, pinned at start, inherited by a resume"; *Capability* = "a platform-understood enum; v1 `nested_docker`"; *Isolation level* = "an ordered minimum". (c) D3 line 153 per §6. (d) The duplicated plan file: #1931 and #1874 both add `docs/plans/20261014_pool-priority-placement.md` with different text. Recommendation: #1931 drops its copy, and #1874 is the plan's one home (§12, item 1). |
| PR2 (backend adapter reports provider/isolation) | Same scope, and now load-bearing. Isolation must come from the backend adapter, never from a setting. #1931 hardcodes `CONTAINER` in the runner's `_executor_pool` (@#1931 `apps/syn-api/src/syn_api/services/execution_host_runner.py`, function `_executor_pool`; the implementer adds the line number after reading that ref). That is safe for flywheel and must never become operator-settable: a host that claims MICROVM without being one is a security failure. PR2 also supplies the implicit local pool for inline mode (§5). |
| PR3 (matching) | Was "v1 needs none / empty producer" (@#1874 `:425-427`). It now ships: the run-row columns; `{SATISFIES}` in claim; the unplaceable branch with `ClaimedRun.unplaceable` and the `run_claimed` short-circuit; the overflow predicate revised per §4; `reserve` taking `requirements` and writing the columns; `RunRequirements` with `combine`/`assess`. There is still no producer, so every run carries the empty requirement, the seeded `default` pool satisfies it, and behaviour is unchanged. Exit test: the scenario table on both adapters (§10). |
| **New PR4 (producer)** | `requires:` in YAML; `run_requirements` through the whole §3 chain (template event, start command, start event, pins, `read_start_pins`, resume command, resume start event); `ORCHESTRATION_EVENT_EPOCH` 1→2; `PlacementCatalog` and `require_placeable` at the three acceptance points; the inline-mode check in `_drain`. It lands after PR3, because a producer that ships before matching writes requirements nobody honours. |
| Placement report PR | Adds `refused` counts (by first failing clause) and `starved` counts. Drops `unplaceable` as a waiting state. |

---

## 8. MicroVM plan (`docs/plans/20261013_selfhosted-microvm-pool.md`)

- **Decision 4** (@#1874 `:464-467`) is rewritten as decided:
  > **Decided 2026-10-14 (owner): (b) mixed fleet with capability matching on claim.** flywheel
  > stays an executor, as a `CONTAINER` pool. KVM hosts register `MICROVM` pools, and their
  > isolation is reported by the backend adapter. Work that needs microVM isolation or nested
  > Docker declares `requires:` in its workflow YAML, and only a pool that satisfies it claims it.
  > Work that no defined pool can satisfy is refused at start, or failed by the first executor to
  > see it. It never waits indefinitely. See ADR-072 D13 and the placement plan §3–§5.

  Option (a), the homogeneous fleet that retires flywheel, stays in the text as the rejected
  alternative, with its reason: it throws away the only node that exists today
  (`docs/north-star.md:11`) to avoid one SQL predicate.
- **SYN-3** (@#1874 `:299-301`): "No per-phase routing (decision #4)" becomes "Placement is per
  execution, by capability (decision #4). A phase's `requires:` raises its execution's requirement.
  Routing phases of one execution to different executors is out of scope."
- **SYN-2** (@#1874 `:276`): "registers with `backend` into `execution_budget.backend`" becomes
  "registers into an `executor_pools` row via `execution_budget.pool_id`, with
  `isolation=MICROVM` reported by the backend adapter". This follows #1931's column change.

---

## 9. Edit procedure for the implement phase

1. Check out `docs/runtime-research-20261012`.
2. Record the file list before editing (`git diff --name-only origin/main...HEAD`). The baseline is
   the PR's *existing* delta, not `main`, because the PR already carries other research documents
   (review I4).
3. Re-read every @#1874 and @#1931 line cited here. Edit the sections in §§2–8, in place.
4. Mark placement-plan decisions **D4** (workflow YAML) and **D8** (ordered minimum) as decided.
   The remaining open items are exactly §12.
5. Every citation written into the docs is a repository-root path with a line number, exactly as
   `git ls-files` prints it. The two abbreviations in the first plan, `workflow_definition.py:801`
   and `execution_host_runner.py@#1931`, are replaced with full paths and concrete lines.
6. Commit to the branch and push. Comment on #1931 with the D13 text, the ubiquitous-language
   entries, the D3 line and the plan-file recommendation. That comment is a request, because this
   workflow does not push to #1931.

---

## 10. Verification

### For this docs change

1. `git diff --name-only <pre-edit HEAD>..HEAD` lists exactly the two plan files. This compares
   before and after the revision, not the branch against `main`.
2. `grep -n "stays \`admitted\`" docs/plans/20261014_pool-priority-placement.md` returns nothing.
   Every remaining `unplaceable` describes a refusal or failure, never a wait.
3. `grep -n "PoolDefinitionConflict\|three-way\|unplaceable outcome" docs/plans/20261014_pool-priority-placement.md`
   finds no description of the withdrawn reserve refusal or upsert guard.
4. In the microVM plan, `retire flywheel` / `homogeneous` appear only inside decision 4's rejected
   alternative, and `execution_budget.backend` appears nowhere.
5. Every `main` citation resolves: `git show origin/main:<path> | sed -n '<line>p'` shows the cited
   construct. For example, `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:140`
   is the candidate CTE, and
   `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:13` is
   `ORCHESTRATION_EVENT_EPOCH: Final = 1`.
6. `just preflight-agent` passes.

### For the later code PRs

Each test below fails if its change is reverted.

**PR3**

- **Scenario table, run against both adapters.** Pools: flywheel (CONTAINER, no capabilities,
  priority 0) and kvm (MICROVM, `nested_docker`). Runs: {empty, MICROVM, `nested_docker`,
  `pools=[kvm]`, `regions=[x]`, GPU-free}. It asserts who claims each run, and that flywheel skips a
  MICROVM run at the head of the queue to take the next CONTAINER run.
- **Overflow.** A MICROVM run is claimed by lower-priority kvm without waiting `overflow_delay_s`
  when only flywheel is higher. A CONTAINER run is *not* held back by a dead or full flywheel.
- **Unplaceable claim.** A run requiring `regions=[nowhere]` is claimed by flywheel with
  `unplaceable=True`, recorded FAILED with a per-pool reason, and its row closed. No workspace is
  provisioned.

**PR4**

- **Producer end to end (review I3).** A workflow declaring `requires: {isolation: microvm}` stores
  `run_requirements` on the template event, pins it on the start event, and writes it to the run
  row with `writer_epoch=2`. Separately, an epoch-1 host claims no `writer_epoch=2` row. That second
  test is kept as a regression test only, since it already passes on `main`
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:142`).
- **Acceptance refusals.** The route returns 422, and no `ExecutionRequested` is written. The
  dispatcher records `failed`. Resume returns 409 and the parent's `resume_execution_id` stays
  unset.
- **Race settlement (review B1/B2).** Patch the catalogue so the precheck passes. Redefine the only
  satisfying pool:
  - between reserve and promote;
  - while the row is `opening`, then run the opening sweep;
  - concurrently with a second pool's redefinition.

  Each time, assert the persisted terminal state: the execution resolves to FAILED with the reason,
  never 404 and never indefinitely `queued`. A duplicate start of the same id still raises
  `StreamAlreadyExistsError`.
- **Inline mode.** With `run_queue_enabled=False`, a MICROVM run that slipped past the precheck is
  recorded FAILED by `_drain`.
- **Resume inheritance (B3).** Resume a constrained parent after its template's `requires:` changed.
  The child's pins carry the parent's original requirement.

---

## 11. Risks

| Risk | Signal and mitigation |
|---|---|
| **Nothing enforces the epoch bump** (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:4-6`). If PR4 forgets 1→2, an old executor claims a MICROVM run and runs it in a container. | PR4's end-to-end test asserts `writer_epoch=2` on a produced row. Recommend building the D9 fitness function (#1310) before or with PR4. |
| An operator who removes a capability from the only pool that had it **fails every queued run that needed it**, at the next claim. | This is the owner's "fail fast", applied honestly. The placement report's `refused` count by clause shows it. The operator docs say so beside the pool settings. |
| Operator-declared `capabilities` are trusted. A VPS that wrongly declares `nested_docker` takes nested-Docker work and fails it in workspace setup. | The run fails in setup. A startup probe needs a human decision (§12). |
| The unplaceable `NOT EXISTS` adds work to the claim scan. | Watch claim latency p95 in the placement report. `executor_pools` is tens of rows. |
| A refusal after acceptance waits for a free slot when every executor is full. | Bounded by the time to the next free slot. It is visible as `queued` until then. |
| `pools:` in shared workflow packages ties a package to one operator's pool names. | 422 naming the pool. The docs steer package authors to capabilities and isolation, and keep `pools` for site-local workflows. |
| #1931 and #1874 conflict on the plan file. | A `git` merge conflict. Resolved by §12 item 1. |
| The @#1874 and @#1931 line numbers here are unverified by this phase. | §9 step 3: the implementer re-reads each one. |

---

## 12. Out of scope, and what needs the owner

**Out of scope:**

- source changes (PR3/PR4);
- per-phase placement onto different executors;
- a start-time requirement override;
- GPU;
- capability probing;
- building the D9 fitness function (#1310's).

**Needs a human decision. None of these blocks the docs edit.**

1. **Plan-file home.** #1931 drops its copy of `docs/plans/20261014_pool-priority-placement.md` and
   adopts the D13 text, and #1874 owns the plan. *Recommended.*
2. **GPU in v1?** *Recommended: no*, until agentic-workspace passes devices through.
3. **Capability trust.** Isolation is always adapter-reported (decided by this plan). Capabilities
   are operator-declared in v1, with a probe as a follow-up issue. *Recommended.*
4. **`pools:` as a requirement.** Keep both `pools` and `regions`, and document `pools` as
   site-local. *Recommended.*
5. **flywheel's priority relative to the KVM pools.** The owner's decision does not settle it.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| **B1**: a reservation refusal has no stream to record FAILED in | **accepted** (verified: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/run_reservation.py:68-79`; `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:430-437`, `:574`) | `reserve` no longer refuses on placement; the three-way outcome is withdrawn. Refusals happen either synchronously at acceptance (422 before `record_execution_request`, `apps/syn-api/src/syn_api/routes/executions/commands.py:692` vs `:817`; 409 at resume; `failed` dispatch) or after the stream exists (the unplaceable claim in run-queue mode; the first step of `_drain` in inline mode). Both use the existing failure path. Duplicate-start handling is untouched. Each outcome is specified per path in §5. |
| **B2**: the reserve lock and upsert guard do not prevent stranding | **accepted** (verified: `_promote` accepts `opening`/`abandoned`, `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:323-331`; the sweep promotes, `:266`; `defer` returns rows to `admitted`, `:181-191`) | The upsert stranding guard and the `FOR SHARE` in reserve are withdrawn. Placement is settled at claim time against the current catalogue, so every interleaving the review listed, plus `defer` and resume, ends in a FAILED execution. No cross-pool lock is added, and claim only reads pool rows. The claim "stranding is impossible" is replaced with the honest guarantee in §5. |
| **B3**: resume needs explicit propagation and its own refusal boundary | **accepted** (verified: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_start.py:140-155`, `:184-199`; `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/start_pins.py:235-248`; `apps/syn-api/src/syn_api/routes/executions/resume.py:151-163`) | §3 names all nine handoffs. §5 adds the resume route as a third acceptance point, which checks the parent's pinned requirement before `executions.save(parent)`. The later race is settled by the unplaceable claim and has its own test. |
| **I1**: preserve the existing capability-aware overflow predicate | **accepted** (the cited @#1874 lines were not re-readable here; taken from the review, which read `f5ddc382`) | The abbreviated "EXISTS a higher pool that satisfies" is withdrawn. The existing predicate (satisfies + epoch + heartbeat + claiming with room + not recently full) is kept, with `{SATISFIES}` in it and `pool_id` projected into `higher`. A test pins that a dead or full flywheel suppresses nothing. |
| **I2**: the catalogue interface cannot supply the diagnostic | **accepted** | `PlacementCatalog.defined_pools() -> list[ExecutorPool]` and `RunRequirements.assess(pools) -> PlacementAssessment` (satisfying pools + first failing clause per pool). The message comes from the same model, with no second matcher. |
| **I3**: the epoch test alone proves nothing new | **accepted** (verified: `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:142` already filters) | An end-to-end producer test is added (YAML → template event → start pins → run row with `writer_epoch=2`). The epoch-1 test is kept and labelled a regression test only. |
| **I4**: citations and scope check | **accepted** | Every `main` citation here is a repository-root path with a line number. §9 step 5 requires the two abbreviated ones to be replaced in the docs. The scope check is now a before/after diff of the revision, not branch versus `main`. |
| *(new, found in this phase)*: inline mode | n/a: not raised by the review | `run_queue_enabled` defaults to `False` (`packages/syn-shared/src/syn_shared/settings/execution.py:95-103`), so on `main` there is no claim at all. §5 adds the `_drain` check and the implicit local pool, and §10 adds a test. Without this, a run that passed a stale precheck would run unchecked in the default mode. |

## Readiness

Ready to implement the docs edit (§9). The five owner items in §12 have recommended defaults and
block nothing. Item 1 (#1931 drops its copy of the plan file) must be agreed before #1931 merges,
or the two PRs conflict.


---

## Addendum: control plane vs workspace runtimes (owner, 2026-10-14)

This plan was written before the owner made the following point. It governs every section above.

- **The control plane is always hosted on our own infrastructure.** That covers the API, event store, dashboard and the executor processes that claim and drive runs. Today it is the VPS; later it is Kubernetes (#1909). A workspace provider is never where the system is hosted.
- **Workspace runtimes are where agent code runs.** These are local Docker on the VPS, self-hosted microVM boxes, and E2B. E2B is paid per workspace run and never for system hosting.
- **Capability matching on claim** decides which runtime a run's workspace lands on. The VPS keeps running work.
- **Cloud hosting of Syntropic137 for other users uses the same deployment approach as self-host**, with workspace providers plugged in behind it. Nothing here may assume a deployment shape that only the owner's install has.

Where the text above says "executor" it means the control-plane process, and "box" or "pool" means a workspace runtime. When this plan is implemented, keep the two vocabularies separate in code and in `docs/architecture/orchestration-ubiquitous-language.md`.
