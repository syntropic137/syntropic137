# ADR-072: Execution Hosting, Executors, the Run Queue and Upgrade Without Drain

- **Status**: Accepted (decision recorded; implementation lands in #1310 Phase 1, items 1.2-1.7, and Phase 2)
- **Date**: 2026-10-05
- **Issue**: #1310 (umbrella; the full plan is the "Full plan" comment there), #1552, #1557, #1381, #1555, #1511
- **Related**: ADR-014 (section 7, resume; section 9, who runs an execution), ADR-025, ADR-055, ADR-057, ADR-060 (section 8, dispatch concurrency), ADR-070 (D4/D5, drain-aware rotation)
- **Vocabulary**: `docs/architecture/orchestration-ubiquitous-language.md` (Executor, Run Queue, Claim, Lease, Fencing, Drain (of an executor), Event Epoch, Queued)

No earlier ADR covers how the platform itself is deployed. ADR-052 is the docs
site's Vercel deployment and ADR-057 is service registration inside one
process; neither says where an execution runs or what a deploy may do to it.

## Context

### Executions run inside the API process

An execution's whole runtime lives in the process that also serves HTTP, runs
the projection coordinator and polls GitHub: the dispatcher task and its
semaphore, the `PhaseRuntime` maps, the `docker exec -i` child that carries the
agent's output, the stream processors, the credential keeper, cancel
consumption and artifact collection. The research behind #1310 catalogues
sixteen such couplings (C1-C16); C4-C11 are process memory by design.

So changing the API or the gateway has exactly two outcomes today:

1. **Drain.** `scripts/pit_stop.sh` closes admission, waits until no execution
   is non-terminal, then recreates `api` and `gateway` together. With two
   orchestrators running 1-3 h workflows, an idle window arrives only by luck:
   a beta waited hours, a hold cost a cancelled run, and dispatching was frozen
   for about an hour for one dashboard beta.
2. **Kill.** On a deploy, crash or OOM, `BackgroundWorkflowDispatcher.shutdown`
   cancels every task with no grace (`apps/syn-api/src/syn_api/_wiring_admission.py:427-431`).
   `CancelledError` is not an `Exception`, so the processor's fail path is
   skipped and only the `finally` teardown runs. The next boot reaps every
   `agentic-ws-*` container and fails every RUNNING execution as
   `OrphanedByRestart` (`apps/syn-api/src/syn_api/services/reconciliation.py`).
   The 2026-10-04 OOM (#1552) orphaned eight executions this way.

### Two facts that constrain every option

- **Agent output exists only in a pipe the process owns.** Nothing else reads
  the `docker exec -i` stream (production sets `COLLECTOR_URL: null`). A
  process that dies mid-phase loses that phase, whatever else is durable.
  Moving a running phase between processes is therefore not available without
  new capture machinery, which would belong in `lib/agentic-workspace` and pay
  its image-release cost.
- **Domain state is already durable and fenced.** `ExecutionJournal.open` uses
  `save_new` (NoStream) and `append` uses `save` with optimistic concurrency
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/execution_journal.py`).
  Two writers on one execution stream conflict; they cannot interleave.

## Decision

**Separate the thing that runs executions from the thing that serves the API,
and let executor generations overlap.** This is the Temporal worker-versioning
and Sidekiq quiet/stop model: a new executor generation claims new work at
once; the old one stops claiming, finishes what it holds, and exits. Nothing is
moved mid-phase, there is no reattach, the crash model in `CLAUDE.md` is
unchanged, and there is no new execution status for upgrades.

### D1. Two process roles, one image

`SYN_PROCESS_ROLE = api | executor | all` (default `all`, so dev and tests
keep one process).

| Role | Runs | Does not run |
|---|---|---|
| `api` | routes, admission, the read path, the projection coordinator and ProcessManagers, pollers | any execution; it has no Docker access |
| `executor` | `ExecutionHost`: the claim loop, `run_claimed`, PhaseRuntimes, the agent stream, the credential keeper, artifact collection, reconciliation of its own and dead hosts' containers | HTTP, projections, pollers |
| `all` | both, on the same run queue | |

The executor is built from the **same** `syn-api` image: one pin, one build
identity. A separate executor image was rejected because two pins have nothing
forcing them to agree.

### D2. The run queue is a dedicated Postgres table, never a projection

Discovery of work reads `execution_runs`, written at admission. It never reads
the `execution_todo` projection or any other read model:

- the to-do projection answers only `get_pending(execution_id)`, has no
  admission time, and is wiped by a VERSION bump;
- a run queue is infrastructure state, like the dedup, pending-SHA and
  capture-delivery tables. It is not a read model.

The template is the fenced queue this repository already has:
`PostgresCaptureDeliveryJobs` (`packages/syn-adapters/src/syn_adapters/session_inventory/capture_delivery_jobs.py`)
claims with `FOR UPDATE ... SKIP LOCKED LIMIT 1`, bumps `lease_token`, sets
`leased_until`, and its `renew` raises when the token was superseded. The run
queue copies that shape; it does not invent a second lease idiom.

The domain owns the port, `ExecutionRunQueue`, with operations named for what
callers do (`reserve`, `mark_admitted`, `claim`, `renew`, `defer`,
`close`, `fence_expired`, `mark_reaped`, `close_interrupted`, `sweep_opening`,
`heartbeat`, `is_draining`, `in_use`), not a generic lease API. Three tables:
`execution_runs`, `execution_budget`, `executor_hosts`. Production fails fast
without Postgres (ADR-060); the test double inherits `InMemoryAdapter`.

**Row states.**

```
opening ──▶ admitted ──claim──▶ claimed ──terminal──▶ done
   │            ▲ ▲                │
   │            │ └── retry_at ────┤ (resume claim deferred, see D7)
   ▼            │                  ▼ lease expired
abandoned ──────┘               fencing ──▶ reaped ──▶ interrupted
(start not recorded;            (slot held until the row is closed)
 promoted if the stream
 later appears)
```

**Admission writes the row before the stream.** Admission inserts
`execution_runs(state='opening')`, then `journal.open` (NoStream), then calls
`mark_admitted`. Executors claim only `admitted`. The row and the stream are
two stores with no shared transaction, so the age of an `opening` row says
nothing about whether its admission is dead: a slow `inherited_outputs` read or
a slow event-store write (plan item 1.3 brackets both between `reserve` and
`journal.open`) can still be in progress when any fixed threshold passes.
The sweep is therefore built so that it can be wrong about liveness without
stranding a start:

- **Every transition is a guarded compare-and-set.** `sweep_opening` updates
  `WHERE state='opening'`; `mark_admitted` updates
  `WHERE state IN ('opening','abandoned')`. Whichever writes second sees the
  other's state and does nothing.
- **Unknown is never absent.** The sweep reads the stream for `opening` rows
  older than two minutes. Stream present → `admitted` (a crash between
  the two writes). Stream **confirmed** absent → `abandoned`, reason
  `start not recorded`. A failed or timed-out read changes nothing; the row stays
  `opening` and is read again next turn.
- **`abandoned` is provisional, not terminal.** A late `journal.open` that
  succeeds after the sweep abandoned the row is followed by `mark_admitted`,
  which promotes `abandoned → admitted`. Admission calls `mark_admitted` only
  after its own open succeeded, so a promoted row always has a stream. If the
  admitter crashes between that late open and `mark_admitted`, the sweep
  also re-reads the stream of every `abandoned` row on each turn and
  promotes any whose stream now exists. An `abandoned` row holds no slot, and
  `reserve` still refuses a second row for its execution id.

So every durable start has a row, and every row with a stream reaches the queue,
however long admission took. A row that stays `abandoned` is one whose stream
has never been seen. Item 1.3 carries a test where admission outlasts the sweep
threshold and the start ends `admitted`, not stranded.

### D3. Capacity and claim are one transaction

The budget lives **in a row** (`execution_budget`), not in each host's
settings, so two generations can never enforce different numbers. One
transaction locks that row, counts slots in use (`claimed`, `fencing`,
`reaped`), and if there is room claims the oldest claimable `admitted` row with
`FOR UPDATE SKIP LOCKED`, bumping `lease_token` and setting `leased_until`. A
count taken outside the claim transaction is racy across hosts and is not
acceptable.

**N is a measured setting, not a constant.** The row is seeded from a setting
and changed by an operator. Its value is sized from measured memory per running
execution against the executor's memory limit. The owner's target is 5 or more
concurrent executions; nothing in this design caps it below that. The budget
bounds every start path, including the direct `POST /workflows/{id}/execute`
route.

### D4. Lease timing

Lease TTL **90 s**, renewed every **30 s** (TTL/3), as a setting. The TTL
bounds **detection**, not effect: provided the database clock and at least one
executor's reconciliation loop are working, a host that stops renewing is seen
as expired within the TTL. It does not bound the expiry-to-reap window in D5,
which ends only when a reap succeeds.

### D5. At most one run per execution, and the limits of that guarantee

**An expired lease is never claimed to run.** The only way out of an expired
`claimed` row is reconciliation, performed by any live executor on every loop
turn as a state machine on the row:

| Step | Action | Guard |
|---|---|---|
| `claimed` → `fencing` | `lease_token + 1`, `reconciler = <host>`, one UPDATE | `leased_until < now()` |
| `fencing` → `reaped` | remove containers labelled `syn.host_id=<dead host>`, `syn.execution_id=<id>` | the reap reports complete (the existing `fully_reaped` rule in `reconciliation.py`); otherwise stay `fencing` and retry |
| `reaped` → `interrupted` | two ordered steps, below | |

The last step crosses two stores, the event store and `execution_runs`, and
they share no transaction. It is two ordered, retryable steps, never one
atomic one:

1. **Append first.** Load the aggregate and append `WorkflowInterruptedEvent`
   through `ExecutionJournal.append`. If the stream already ends in a terminal
   event, the aggregate rejects the command and nothing is appended. A
   `ConcurrencyError` means another writer advanced the stream: reload and
   decide again.
2. **Then close the row** with `close_interrupted`, guarded on the row's
   current `lease_token`. Only this releases the slot.

A crash between the steps leaves the row `reaped` with the stream already
terminal. The next reconciliation turn reloads, sees the terminal stream, appends
nothing, and closes the row. Until the row is closed it is counted in use (D3),
so a crash can hold a slot for a turn but can never free one early.

**The lease token fences the queue, not the stream.** Bumping `lease_token`
changes `execution_runs` only. `ExecutionJournal.append` saves through the
event repository, whose only check is the stream's expected version. So the old
host is stopped by two separate mechanisms:

- **Self-fencing, through the queue.** Its next `renew` fails on the token
  (`RunLeaseLost`), within one renewal interval of its process running again.
  It then cancels its own runs, which take the bounded interruption path of
  #1381, and its `close` is refused on the token.
- **Optimistic concurrency, through the stream.** Its appends raise
  `ConcurrencyError` only **after** some other writer has advanced the stream,
  in practice the reconciler's interruption in step 1. Before that, from the
  moment of fencing until step 1 lands, an append by the old host **succeeds**.

The race is resolved by stream order, not by the token. If the old host appends
first (a phase completion, say), the reconciler's load or append sees it:
either a `ConcurrencyError` and reload, or a reload that already contains the
event. It then interrupts after that event, or appends nothing if the event was
terminal, and closes the row either way. If the reconciler appends first, every
later append by the old host fails on the version. Either way the stream is one
consistent history of one run, and the row is closed only after the stream is
terminal.

**What is guaranteed:**

- **At most one run per execution id.** A second workspace is never
  provisioned for an execution, and no execution is automatically re-run.
  Auto-resume after a host dies is deliberately **not** done: the run is
  interrupted and stays interrupted until a person resumes it.
- **Exactly-once across a human resume is unchanged.** A resume is a
  deliberate new execution (ADR-014 section 7); duplicate-PR protection is the
  existing continued-branches logic (#1513).

**What is NOT guaranteed:** that effects stop at the instant a lease expires. A
stalled host's agent keeps running in its container until the reaper removes
it, so a push can land in the expiry-to-reap window. That effect belongs to the
one run; no second run duplicates it. The processor's rescue pushes also run in
the workspace, so removing the container removes that path too.

The window is **not** time-bounded by this design. It runs from the lease
expiring to the first **successful** reap. Detection is bounded by the TTL
(D4), but after that the row waits for a live executor's reconciliation turn,
and a reap that fails (Docker unreachable, a container that will not stop)
leaves the row in `fencing` to retry, exactly as `reconciliation.py` treats an
incomplete cleanup today. Because the window has no bound, it is watched
instead: a row in `fencing` for longer than one TTL, or with no executor
heartbeat able to reap it, raises an operator alert naming the execution and
the dead host. Removing that host's containers by hand ends the window.

Visibility-timeout redelivery (Sidekiq, Celery, SQS) is deliberately not
adopted: redelivering an hour-long agent phase is exactly the duplicate-effects
risk this decision exists to remove.

### D6. Containers carry their host

Workspace containers already carry `syn.execution_id` and `syn.workspace_id`,
and the isolation provider passes labels through to `docker run` unchanged, so
this needs no submodule change and no image release. Both workspace and legacy
sidecar containers gain `syn.host_id` and `syn.host_generation`; sidecars gain
`syn.execution_id`. Reaping selects by `syn.host_id`. An unlabelled container
(created before the labels shipped) is reaped only when no executor other than
the reaping one has a live heartbeat; otherwise it is logged and left.

### D7. What a running execution still reads from shared read models

This is the narrowed replay claim. Every read-model call reachable after a
claim was traced:

| Call | Shared read model | Treatment |
|---|---|---|
| `get_pending(execution_id)` in the processor's drain loop | `execution_todo` | **Replaced** by a run-scoped fold (D8). An empty list is read as "done", so this one is critical. |
| `inherited_outputs(...)` at the start of a resume | `artifact_list` | **Resumes only.** If it fails at claim, the row returns to `admitted` with `retry_at` backoff; after K attempts it fails with a reason naming the read model. Fresh starts do not call it. |
| `ArtifactCollector` fallback for completed phases missing from the run's cache | `artifact_list` | Not reached within one executor run, since every completed phase is in that run's cache. Recorded as a dependency to revisit if mid-run reattach is ever built. |
| Cancel and inject signals | none (Redis signal queue) | unchanged |

**The claim, in exactly these words:** a projection replay does not stall or
corrupt a **running fresh** execution. It can delay the **claim of a resume**
until `artifact_list` is readable. It never delays the claim of a fresh start,
because discovery reads `execution_runs`.

How long a replay delays a resume claim is measured, not assumed:
v0.33.2-beta.6 replayed `WorkflowDetailProjection` on production from a lag of
57,758 events to 0 in about 4 minutes (about 240 events/s, platform idle),
2026-10-05. That is one measurement, not a bound (`docs/release-process.md`
says the same of its earlier 8m46s figure); an earlier "~1 h" figure had no
source and was wrong by about 15x.

### D8. The run-scoped to-do fold

In `run_claimed`, the processor gets a fresh `ExecutionTodoProjection` over a
new `RunTodoStore` (a minimal `ProjectionStore` holding one execution's
record), seeded by replaying that execution's own events, and its own
`ExecutionJournal`. The shared `execution_todo` projection stays in the
coordinator for dashboards only; nothing in the executor reads it.

`RunTodoStore` is named here so the in-memory fitness check can exempt it **by
name**: it is the "in-process synchronous projection" `CLAUDE.md` prescribes, a
cache derived wholly from durable events and rebuilt at every claim, so losing
it loses nothing. It must not be `InMemoryProjectionStore`, which refuses
production (ADR-060).

### D9. Event epoch

Event models forbid extra fields, and with overlapping generations a newer API
routinely writes events an older executor must load. So
`ORCHESTRATION_EVENT_EPOCH: int` lives in `syn_domain.contexts.orchestration`.
Admission writes it to `execution_runs.writer_epoch`; an executor claims only
rows with `writer_epoch <=` its own epoch. Work from a newer API waits, visibly,
for a new enough executor; it is never mis-read. A fitness function snapshots
every orchestration event schema and fails when one changes without an epoch
bump (a whole-codebase static property, so `ci/fitness/`), and
`just check-event-compat` parses payloads across the previous release's
`syn-domain` in both directions. Deploy order is then latency, not correctness:
upgrade executors first.

### D10. Upgrade without drain

| Change | Procedure | Waits for executions? |
|---|---|---|
| gateway | `pit_stop --service gateway`: swap the gateway alone | no |
| api | `pit_stop --service api`: recreate `api` alone; admission stays open | no |
| executor (Phase 1) | drain the one executor on `in_use().claimed == 0`; **admission stays open**, admitted work waits durably | yes, for that executor's runs only |
| executor (Phase 2) | start generation N+1 in its own compose project, wait for its heartbeat, **drain** generation N | no |

**Drain (of an executor)** is: `executor_hosts.draining` is set
(`PUT /executors/{host_id}/drain`), the host checks it every loop turn between
claims, stops claiming, finishes what it holds and exits 0. The processor
receives no new signal; this is a property of the host, not of an execution,
which avoids repeating the Pause mistake (an event nothing in the execution
path observed). It is not the pit-stop drain, which closes admission and waits
for the whole platform to be idle.

Out of scope: upgrading the event store, Postgres, Redis, envoy-proxy, the
token injector or the collector without a drain, and multi-host deployment
(not precluded).

### D11. Status of an admitted but unclaimed execution

The aggregate is RUNNING from the start event, and that stays the status. The
read path adds `queued: bool`, derived from `execution_runs` (`admitted` and
not yet `claimed`). Queueing is infrastructure state, not a domain decision, so
there is no domain `queued` status and the aggregate, the event stream and the
execution statuses are unchanged. (#1310 plan section 8, decision 2, Option A,
decided 2026-10-05.)

### D12. Relationship to PR #1574 (#1557)

PR #1574, open at the time of writing, ships one execution concurrency budget
and a durable start intent inside the current single-process topology:

- an in-process FIFO `ExecutionBudget` sized by `SYN_EXECUTION_MAX_CONCURRENT`
  (retiring `SYN_POLLING_MAX_CONCURRENT_DISPATCHES`) that bounds all three start
  paths, with a memory-derived default and a cgroup warning;
- `queued` / `starting` reported as the `status` of a start with no stream yet,
  with a `start_queue` position object;
- an `ExecutionRequest` aggregate (`ExecutionRequested`) and
  `ExecutionRequestStartProcessManager`, so an accepted direct start is never
  lost while it waits for a slot.

Item 1.2 **builds on its rule and replaces its mechanism**:

| #1574 | After 1.2 / 1.3 |
|---|---|
| One budget bounds every start path | **Kept.** The rule is unchanged; it moves from a per-process semaphore to the `execution_budget` row (D3), so it holds across hosts and generations. `SYN_EXECUTION_MAX_CONCURRENT` is the seed for that row rather than a second setting, and its memory-per-execution sizing is the measurement N is taken from. |
| `ExecutionBudget` in-process FIFO hand-off | **Replaced** by the claim transaction. FIFO order is `ORDER BY admitted_at, execution_id`. |
| `queued` / `starting` as a value of `status`, for a start with no stream | **Replaced** by D11. Once admission opens the stream synchronously (1.3), there is no admitted start without a stream, so `status` carries only execution statuses and `queued` is a boolean. A `start_queue`-style position may stay as detail on the read path, computed from `execution_runs`. Changing the API field is a CLI type change through `just codegen`. |
| `ExecutionRequest` stream as the durable start record | **Not a discovery source.** Executors discover work only from `execution_runs`. Whether `ExecutionRequested` survives as the domain record of what a caller asked for, or is folded into start-only admission, is decided in 1.3; either way the `opening` sweep (D2), not a ProcessManager re-offer, is what guarantees an admitted start is never lost. |
| `holds_start` in-process duplicate-start checks | **Replaced** by `reserve` refusing a second row for one execution id, plus the stream's NoStream open. |

If #1574 merges first, 1.2 migrates its budget and status as above. If it does
not, 1.2 carries the one-budget rule itself and #1557 closes with 2.3.

## Consequences

### Positive

- API and gateway deploys (after Phase 1) and executor deploys (after Phase 2)
  no longer need a fully idle platform.
- An API OOM no longer takes executions with it; an executor OOM interrupts
  only that host's runs, honestly and resumably.
- One budget, enforced in one transaction, for every start path and every host.
- A projection replay can no longer make a running execution "complete" with
  phases unrun, and can no longer hide admitted work from executors.

### Negative

- A new table set, a new process role and a new compose service to operate.
- Admission becomes synchronous, so the dispatch and resume ProcessManagers'
  live `process_pending` gets slower (live-only, so replay is unaffected).
- Effects in the expiry-to-reap window are accepted, not prevented, and the
  window has no time bound: it ends at the first successful reap, so it is
  alerted on rather than promised (D5).
- Introducing the executor service is a compose change pit_stop cannot stage
  until #1511 ships; until then Phase 1 rolls out with one final full-drain
  install.
- Mid-phase crash survival is not provided. A host that dies mid-phase still
  loses that phase.

### Neutral

- **Adopt / Reattach** (a new process taking over a running phase) is reserved
  for Phase 3, which is deferred and evidence-gated: no implementation issue
  until an experiment write-up under `docs/experiments/` is read.
- The ADR-014 execution model and its resume semantics are unchanged.
- ADR-070 D4/D5, revised in place, keep rotation restart-free and give each
  affected service one procedure; D10's executor drain is used only when a
  client that has not yet adopted ADR-070 D1 must restart.
