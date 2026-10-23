# ADR-072: Execution Hosting, Executors, the Run Queue and Upgrade Without Drain

- **Status**: Accepted (decision recorded; implementation lands in #1310 Phase 1, items 1.2-1.7, and Phase 2). D2, D4 and D10 revised in place 2026-10-15 for #1944.
- **Date**: 2026-10-05 (first drafted in parked PR #1597; resumed 2026-10-08 against #1574 and #1651 as merged)
- **Issue**: #1310 (umbrella; the full plan is the "Full plan" comment there), #1552, #1557, #1381, #1555, #1511, #1734 (implementation of multi-host placement, heartbeat and fencing, moved out of #1310 on 2026-10-07). #1734 also carries pools, priority and overflow (D13, amended 2026-10-14), #1944
- **Related**: ADR-014 (section 7, resume; section 9, who runs an execution), ADR-025, ADR-055, ADR-057, ADR-060 (section 8, dispatch concurrency), ADR-070 (D4/D5, drain-aware rotation)
- **Vocabulary**: `docs/architecture/orchestration-ubiquitous-language.md` (Executor, Run Queue, Claim, Lease, Heartbeat, Fencing, Drain (of an executor), Event Epoch, Queued, Execution Budget, Executor Pool, Pool Priority, Overflow, Overflow Delay, Claim Check, Capability, Isolation Level, Run Requirements, Unplaceable, Placement, Reap Scope; reserved: Adopt / Reattach, Router)

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

Implemented (#1310 1.6) as `SYN_EXECUTION_PROCESS_ROLE`: the `SYN_EXECUTION_`
prefix is kept because `.env.example` and the compose forwarding are generated
from prefix + field name. The compose files pin it per service.

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
`heartbeat`, `is_draining`, `in_use`), not a generic lease API. Four tables:
`execution_runs` (one row per admitted start), `execution_budget` (one row per
executor: its pool, capacity, slots in use, heartbeat, last claim check,
full-since and reap scope; D3, D13), `executor_pools` (one row per Executor
Pool: priority, provider, region, isolation, capabilities and overflow delay;
D13) and `executor_hosts` (one row per registered host: its container,
generation, epoch and drain flag, D5, D9, D10). The last claim check and
full-since columns land with D13's later steps (see D13, Status). Production fails fast
without Postgres (ADR-060); the test double inherits `InMemoryAdapter`.

**Row states.**

```
opening ──▶ admitted ──claim──▶ claimed ──terminal──▶ done
   │            ▲ ▲                │
   │            │ └── retry_at ────┤ (resume deferred, slot released, D3/D7)
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
  `opening` and is read again by the next sweep.
- **`abandoned` is provisional, not terminal.** A late `journal.open` that
  succeeds after the sweep abandoned the row is followed by `mark_admitted`,
  which promotes `abandoned → admitted`. Admission calls `mark_admitted` only
  after its own open succeeded, so a promoted row always has a stream. If the
  admitter crashes between that late open and `mark_admitted`, the sweep
  also re-reads the stream of every `abandoned` row on each sweep (the loop
  starts a sweep whenever the previous one has finished, D4) and promotes any whose stream now exists. An `abandoned` row holds no slot, and
  `reserve` still refuses a second row for its execution id.

So every durable start has a row, and every row with a stream reaches the queue,
however long admission took. A row that stays `abandoned` is one whose stream
has never been seen. Item 1.3 carries a test where admission outlasts the sweep
threshold and the start ends `admitted`, not stranded.

### D3. Capacity and claim are one transaction

**One budget row per executor, from day one.** This is epic #1612 Step 2,
adopted here in place of the single global row the #1310 plan first proposed.
`execution_budget` holds one row per executor: `executor_id` (its `host_id`),
`pool_id` (D13), `capacity`, `in_use` and `heartbeat_at`, with
`CHECK (in_use >= 0 AND in_use <= capacity)`. A row's provider is its pool's.
The per-row `backend` column this section first named was never written and is
dropped. **Global capacity is the sum of
the rows' capacities**; it is a derived figure for reporting, never a number
anyone claims against. With one host there is exactly one row, so Phase 1 is
no larger than with a global row. A second host, or a remote backend, adds a
row, not a schema change. A single global number cannot express hosts of
different sizes: with a global budget of 5 and one host sized for 2, a global
count lets that host claim all 5, and sizing the global number to the smallest
host wastes every larger host's capacity.

**The claim**, one transaction, in the shape of
`PostgresCaptureDeliveryJobs.claim`:

1. Lock the executor's **own** row unconditionally. Then, in one statement
   that sees whatever the lock wait let commit, stamp `claim_checked_at` and
   read `in_use < capacity`, `NOT draining` and
   `heartbeat_at > clock_timestamp() - <stale>`. `now()` is the transaction's
   start and would judge liveness before the wait. No row (full, stale,
   draining or absent) means no claim this turn. (The `claim_checked_at`
   stamp lands with D13's claim signals; the rest is the code today.)
2. Take the oldest `admitted` row this executor's pool may take now (D13):
   `ORDER BY admitted_at, execution_id FOR UPDATE SKIP LOCKED LIMIT 1`. None
   means no claim. (Until D13's placement step lands, every admitted row
   whose `retry_at` has passed and whose `writer_epoch` this host can read
   qualifies.)
3. Set the run's `executor_id = <self>`, `lease_token = lease_token + 1`,
   `leased_until`, and `state = 'claimed'`.
4. `in_use = in_use + 1` on the locked budget row.

The capacity predicate is per executor, so no host ever holds more runs than
its own row allows, and two executors never contend on one budget lock. A count
taken outside the claim transaction is racy and is not acceptable.

Placement (D13) reads other executors' rows without locking them. Preference
is therefore decided on a snapshot: while a higher executor's release is in
flight, several lower executors may each spill a run. Capacity is never
exceeded, because only an executor's own locked row decides it.

**Release is the reverse, fenced.** A run row carries a **charge** exactly
while it is `claimed`, `fencing` or `reaped`, and the charge is held by the
budget row its `executor_id` names. `in_use` is the number of runs charged to
that executor. A charged run stays charged until it leaves those three states,
never at lease expiry. Three transitions leave them, and each is a
**release**:

| Release | Transition | Guard |
|---|---|---|
| `defer` | `claimed -> admitted`, with `retry_at` (D7) | `state = 'claimed'` and the caller's token is the current `lease_token` |
| `close` | `claimed -> done` | `state = 'claimed'` and the current `lease_token` |
| `close_interrupted` | `reaped -> interrupted` (D5 step 2) | `state = 'reaped'` and the reconciler's current `lease_token` |

A release, in one transaction: the guarded state change, `in_use = in_use - 1`
on the row named by `executor_id`, and `executor_id = NULL` on the run. The
guard is a compare-and-set, as `renew` is guarded today, so a release whose
token was superseded, or a second release of the same claim, matches no row,
raises `RunLeaseLost` and changes nothing. The slot is freed exactly once, and
the `CHECK` turns any remaining accounting bug into a failed write rather than
a leaked or double-freed slot. A deferred row is unowned: its next claim
charges whichever executor takes it, from step 3 above.

A claimer closes a run only once its backend shows the run's resources gone
(D13). Otherwise it leaves the run charged for reconciliation: its Lease
expires and a reconciler in the same reap scope fences it, and releases it only
once its own reap succeeds (D5). A reap that raises counts as not shown gone. This holds
however the drain ended, so an error the processor turned into a failed workflow
cannot free a slot over resources that may still exist.

**Closing a row that holds no charge changes no counter.** A row that is
`opening`, `abandoned` or `admitted` has `executor_id = NULL`, whether it has
never been claimed or was deferred. Cancelling it (D12) closes it with a
transition guarded on that unclaimed state and `executor_id IS NULL`, and
touches no `execution_budget` row: there is no charge to release, and no
retained owner to debit wrongly. If a claim locks the row first, the guard
matches nothing and the cancel reaches the claimed run as an ordinary cancel
of a running Execution.

Fencing and takeover (D5) move the reconciler, not the charge: the slot stays
on the claimer's row until `close_interrupted`. Nothing is ever redelivered
(D5); a deferred resume is not a redelivery, because it never ran.

**Capacity across generations and restarts.** Each executor's row carries its
own capacity, so two generations can never enforce different numbers for one
host, and a host's memory is never counted twice while two of its processes
overlap. An executor that replaces another on the same machine (generation
N+1 in D10 Phase 2, or a process restarting in the same container, D5)
registers its row with `capacity = 0` and is that row's **successor**. One
transaction, at drain or at restart, sets the predecessor's `capacity` to its
current `in_use` and adds the difference to the successor. After that, every
release on the predecessor's row, `defer` included, also moves that unit of
capacity to the successor, in the same transaction: the predecessor's
`capacity` and `in_use` each fall by one and the successor's `capacity` rises
by one. The machine's total stays exactly what it
was throughout the overlap; the old generation's slots drain into the new one
as its runs finish. A predecessor row is deleted when both its `capacity` and
`in_use` are zero and its `executor_hosts` row is gone. A dead host retired
with no successor keeps its row, and its slots, until its fenced runs close.

**Capacity is a measured setting, not a constant.** Each row's capacity is
seeded from a setting of the executor that registers it and changed by an
operator. Its value is sized from measured memory per running execution
against that executor's memory limit. The owner's target is 5 or more
concurrent executions; nothing in this design caps it below that. The budget
bounds every start path, including the direct `POST /workflows/{id}/execute`
route, because every start reaches an executor only through a claim.

### D4. Lease timing

Lease TTL **90 s**, renewed every **30 s** (TTL/3). The TTL, the heartbeat
staleness window (**90 s**), the loop interval (**5 s**), the turn budget
(**15 s**) and the reconciliation concurrency (**4**) are one group of executor
timings. The turn budget and the concurrency are provisional, not measured
(#1944). Today they are `HostTiming`'s fields, which refuse a loop interval plus
turn budget longer than a third of the TTL; making them one settings group that
both the Run Queue and the claim loop are built from is required before
`SYN_EXECUTION_RUN_QUEUE_ENABLED` is turned on anywhere. The TTL bounds
**detection**, not effect: provided the database clock and at least one
executor's reconciliation loop are working, a host that stops renewing is seen
as expired within the TTL. It does not bound the expiry-to-reap window in D5,
which ends only when a reap succeeds.

**Heartbeat** is separate from the lease. **The claim loop itself writes it**,
as the first step of every loop turn, setting `heartbeat_at` on the executor's
own `execution_budget` row (D3) once per loop turn, including while the
executor is idle and holds no claim. Its cadence is the loop's (5 s), not the
lease's: the loop interval is also how long an admitted run waits to be
claimed, so it is kept short, and one write per host per interval is cheap.
It is never written by a side task or an independent timer: a claim loop that
is wedged must stop looking alive, and a timer beside it would keep advertising
a host that can no longer claim, reconcile or drain.

**A loop turn is bounded, so a stale heartbeat means only that the loop
stopped.** A turn awaits the heartbeat, then reconciliation store calls and
claims, and starts none of them once the turn budget is spent; it never awaits
a reap or the opening sweep. A budget counts elapsed time, not calls: several
calls that each return can still add up past the staleness window, so the
budget is checked before every one. Reconciliation (D5) runs in tasks the loop starts and tracks, at
most the reconciliation concurrency at once and least recently attempted first,
as it holds claimed runs; the opening sweep (D2) runs as one such task. A turn
checks on them and starts more; it does not wait for them. So the time between
two heartbeats is at most the loop interval plus the turn budget plus one store
call, however many rows exist and however slowly Docker answers. Only a store
call that does not return can push it past the staleness window, and a loop
stuck in one cannot claim, so it is right that it reads stale. A reap or sweep
that hangs leaves its rows unfinished and is logged once, when it has run
longer than the TTL; it is neither cancelled nor started again beside itself.
The reap-window alert (D5) reports the rows. It does not make a loop that
can still claim look dead.

Per-run lease renewal is a different write with a
different meaning: a lease says that one run's claim is still held, while a
heartbeat says only that the executor's claim loop turned recently. Its uses:
the claim predicate (D3: an executor whose own heartbeat is stale does not
claim), the global capacity report (live rows only), the reap-window alert
(D5), deciding whether an unlabelled container may be reaped (D6), and
whether an executor counts as live for placement (D13). It never authorises
fencing or takeover. Fencing is decided by an expired
lease. Takeover is decided by the reconciler having left (D5), and a stopped
heartbeat is not leaving.

**Claim check.** The claim statement stamps `claim_checked_at` on the
executor's own row each time it decides. A heartbeat says the loop turned; a
claim check says the claim ran. Placement trusts only the second to advertise
room, so a loop whose claim keeps failing stops holding work back. (Lands with
D13's claim signals.)

### D5. At most one run per execution, and the limits of that guarantee

**An expired lease is never claimed to run.** The only way out of an expired
`claimed` row is reconciliation. Any live executor may **fence** an expired
row on any loop turn, though no more rows per turn than it has free
reconciliation slots (D4). The same limit applies to takeover, so a dead or
departed host's rows are shared among live executors, not taken by whichever
turns first. Each owned row gets a new attempt in least-recently-attempted
order, so a row whose reap keeps failing never holds up the others. From then on the row has exactly one **reconciler**, and
only that host takes turns on it:

| Step | Action | Guard |
|---|---|---|
| `claimed` → `fencing` | `lease_token + 1`, `reconciler = <host>`, `reader_epoch = LEAST(reader_epoch, <its epoch>)`, one UPDATE | `leased_until < now()` and `writer_epoch <= <its epoch>` (D9), and the claimer's `reap_scope` equals the reconciler's (D13) |
| takeover, in `fencing` or `reaped` | `lease_token + 1`, `reconciler = <host>`, `reader_epoch` recomputed (D9), one UPDATE | the current `reconciler` has **left**: it has no `executor_hosts` row (below), and `writer_epoch <= <its epoch>`, and the claimer's `reap_scope` equals the reconciler's (D13) |
| `fencing` → `reaped` | remove containers labelled `syn.host_id=<dead host>`, `syn.execution_id=<id>` | the reap reports complete (the existing `fully_reaped` rule in `reconciliation.py`); otherwise stay `fencing` and retry |
| `reaped` → `interrupted` | two ordered steps, below | |

The last step crosses two stores, the event store and `execution_runs`, and
they share no transaction. It is two ordered, retryable steps, never one
atomic one:

1. **Append first.** Load the aggregate and append `WorkflowInterruptedEvent`
   through `ExecutionJournal.append`. If the stream already ends in a terminal
   event, the aggregate rejects the command and nothing is appended.
   `append` reports every save it did not see acknowledged the same way: it
   raises `EventsNotRecordedError`, with the repository's exception as its
   `__cause__`. Only one cause says what the store did. A
   `ConcurrencyConflictError` means another writer advanced the stream, so
   this append lost the version race and wrote nothing: reload and decide
   again whether to append or only close. Any other cause, such as an
   `EventStoreError` from an RPC that failed after `Append` was sent, reports
   a lost acknowledgment, not an absent write: the store may have committed
   the event before the response was lost, so the reconciler assumes neither.
   It leaves the row `reaped`, and the next reconciliation turn reloads the
   stream before deciding anything. A stream that is already terminal gets no
   second interruption, only the row closure in step 2.
   The `EventsNotRecordedError` docstring on `main` still says a wrapped
   failure means the events are "NOT durable". That is true only for a
   `ConcurrencyConflictError` cause. Item 1.2 corrects the docstring and pins
   it with a test before any reconciler relies on it. The parked #1597 branch
   already holds that change, but this ADR's PR is docs only and does not
   carry it.
2. **Then close the row** with `close_interrupted`, guarded on the row's
   current `lease_token`. For a fenced run only this releases the slot: it
   decrements `in_use` on the claimer's `execution_budget` row in the same
   transaction (D3).

**Reconciliation turns are exclusive.** Every turn on a `fencing` or `reaped`
row is taken by the row's `reconciler` and no other host, so two turns on one
row never overlap. Another executor replaces it only by takeover, and only once
the reconciler has **left**: its `executor_hosts` row is gone. A heartbeat that
stopped is not leaving, for the same reason an expired lease is not proof that
a run stopped: a stalled process can resume and load the stream. A host's
`executor_hosts` row disappears in exactly three ways, and each comes after
the host's last stream load:

- **Clean exit.** A draining executor (D10) finishes its turns, and deleting
  its own `executor_hosts` row is the last thing it does before exiting 0.
- **Restart.** `executor_hosts` records the container a host runs in. A
  process starting in a container that already has a host row deletes that row
  before it registers its own: the restart is the proof that the previous
  process in that container has stopped.
- **Retirement.** An operator retires a host that died or stalled
  (`DELETE /executors/{host_id}`), after stopping its process. That is the same
  manual act the reap-window alert below already asks for.

A `host_id` is never reused: a restarted process registers a new one. So a
deleted row cannot come back, and a host that has left cannot load the stream
again. A row whose reconciler stalled without leaving waits, in `fencing` or
`reaped`, and raises the same alert as a stuck reap, naming the host to retire.

A crash between the steps leaves the row `reaped` with the stream already
terminal. The next reconciliation turn (by the same reconciler, or after a
crash by the host that takes over) reloads, sees the terminal stream, appends
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
- **Optimistic concurrency, through the stream.** Its appends are refused
  only **after** some other writer has advanced the stream, in practice the
  reconciler's interruption in step 1, and the refusal reaches it as the same
  `EventsNotRecordedError` wrapping a `ConcurrencyConflictError`. Before that,
  from the moment of fencing until step 1 lands, an append by the old host
  **succeeds**.

The race is resolved by stream order, not by the token. If the old host appends
first (a phase completion, say), the reconciler's load or append sees it:
either an `EventsNotRecordedError` caused by a `ConcurrencyConflictError` and
a reload, or a load that already contains the event. It then interrupts after that event, or appends nothing if the event was
terminal, and closes the row either way. If the reconciler appends first, every
later append by the old host is refused on the version and writes nothing. Either way the stream is one
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
instead: a row whose lease expired more than one TTL ago and that is not yet
`interrupted` (with bounded acquisition it may still be waiting in `claimed`),
or with no executor
heartbeat able to reap it, raises an operator alert naming the execution and
the dead host. Removing that host's containers by hand ends the window.

A reconciler can reap only what its backend reaches: a Docker reaper one
daemon, a provider reaper one account. `execution_budget.reap_scope` records
that reach. It is derived from the backend and never configured. A run whose
scope has no live executor stays charged and raises this alert. Rows from
before the column are given a scope only by a successor in the same container:
one container runs on one daemon, so it proves the same scope. A NULL scope
equals nothing, so until then no reconciler fences the row; it stays charged and
raises this alert, and the runbook step is an operator-verified manual
`UPDATE`. On Docker the scope is the `docker info` engine ID, read once at
startup; an executor that cannot read one does not start.

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
| `inherited_outputs(...)` at the start of a resume | `artifact_list` | **Resumes only.** If it fails at claim, `defer` returns the row to `admitted` with `retry_at` backoff and releases its slot (D3); after K attempts it fails with a reason naming the read model. Fresh starts do not call it. |
| `ArtifactCollector` fallback for completed phases missing from the run's cache | `artifact_list` | **Conditional, and not reached by today's fresh producer.** `_resolve_phase_outputs` queries the projection only for a completed phase absent from the run's file cache (`ArtifactCollector.py:352-359`), and `PhaseOutputCache.record` leaves a phase absent only when its result is empty (`processor_types.py:60-67`). The fresh producer never records an empty result: `_deliverables` returns at least one deliverable or raises (`ArtifactCollector.py:668-714`), each becomes one `PhaseOutputFile` (`:604-635`), and `collect` records them (`phase_workspace.py:412-416`) before `COMPLETE_PHASE` adds the phase to `completed_phase_ids` (`WorkflowExecutionProcessor.py:511-522,899-913`). Not replaced. See the claim below. |
| Cancel and inject signals | none (Redis signal queue) | unchanged |

**The claim, in exactly these words:** a projection replay does not stall a
**running fresh** execution's to-do list, which no longer reads a shared read
model (D8). Nor does it reach the `ArtifactCollector` fallback in a fresh run
today: that fallback is conditional on a completed phase being absent from the
run's `PhaseOutputCache`, and the producer invariant above means every phase a
fresh run completes is in that cache. The guarantee rests on that invariant,
not on the cache. If a future producer lets a phase complete with an empty
result, the fallback becomes reachable, and its cost is latency or failure,
not lost files: the phase produced nothing, so even a lagging `artifact_list`
answers correctly with nothing, but a slow query delays the next phase's
provision by its duration, and a query that raises propagates out of
`inject_artifacts` uncaught (`ArtifactCollector.py:319-321,354-359`) and fails
that provision. That producer change must decide this, by recording the empty
result as authoritative (a change to `processor_types.py:61-63`) or by
accepting the failure, and is not a hosting change. A replay can also delay the **claim of a resume** until
`artifact_list` is readable. It never delays the claim of a fresh start,
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

*As built (#1310 item 1.4).* `RunTodoStore` matches neither of the in-memory
fitness check's patterns, so the check names it by exact key in
`_NAMED_CANDIDATES` (`test_in_memory_adapters_are_guarded.py`), and
`fitness_exceptions.toml` exempts that same key citing this decision. A guard
added to the class would make it guarded, the exemption would go stale, and the
gate would fail; `test_the_fold_constructs_and_folds_in_production` also builds
and seeds a fold with `APP_ENVIRONMENT=production`. The record it holds is a
frozen typed value; dicts exist only at the `ProjectionStore` boundary. The
entry point is `RunScopedTodoFold.for_execution(execution_id, repository,
events, projection_type)`: the projection class is passed in by the composition
root, as the processor's projection already is, because a slice may not import
the `execution_todo` slice (VSA031). `ExecutionRepository` cannot read a
stream, so seeding reads through a port, `ExecutionEventStream`, satisfied in
`syn-adapters` by `EventStoreExecutionEventStream`, which pages through the
whole stream (one gRPC read returns at most 1,000 events). Seeding and live
saves share one dispatch, `execution_journal.project_events`.

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

Both are built (#1310 item 1.7). The snapshot is
`ci/fitness/event_sourcing/snapshots/orchestration_events.epoch-<N>.json`,
recording each event's `event_type`, `schema_version` and schema, written once
per epoch and never rewritten, checked by
`ci/fitness/event_sourcing/test_orchestration_event_schema_snapshot.py`. The
compat gate is `scripts/check_event_compat.py`; it resolves the previous
release from tags, because `release` is not an ancestor of `main`, and decodes
by `(event_type, schema_version)` as the event store does. A payload the
previous release cannot read passes only when this epoch is above that
release's. A release with **no** epoch has no claim predicate, so for it no
bump excuses an unreadable payload: every payload must be readable.

**Admission is not the last write.** The API appends to executions it did not
admit: eval attach and detach (`apps/syn-api/src/syn_api/routes/evals.py:130`,
`:153`), tag add and remove (`apps/syn-api/src/syn_api/routes/tags.py:126`,
`:145`), resume (`apps/syn-api/src/syn_api/routes/executions/resume.py:112`)
and reconciliation (`apps/syn-api/src/syn_api/services/reconciliation.py:217`).
Checking the epoch only at admission would let a newer API add an event to an
older `admitted` row that an older executor then claims and cannot load. So the
rule is on every append, not on admission:

> **The row's `writer_epoch` is the newest epoch of any event in the stream.**
> A writer whose epoch is higher raises it, with one guarded UPDATE, **before**
> it appends.

**`reader_epoch` is the least epoch of any host that may still load the
stream.** While a row is `claimed`, `fencing` or `reaped`, those hosts are the
claimer and, once it is fenced, the row's one reconciler (D5); a previous
reconciler is not among them, because takeover requires it to have left.
`executor_hosts` records each host's epoch. Three single-row UPDATEs write
`reader_epoch`, and nothing else does:

| UPDATE | `reader_epoch` becomes |
|---|---|
| claim | the claimer's epoch |
| `claimed` → `fencing` | `LEAST(reader_epoch, <reconciler's epoch>)`. The fenced claimer has not left: a stalled host that resumes loads the stream on the interruption path of #1381. |
| every reconciliation turn, takeover included, begins with a recompute | `LEAST(<reconciler's epoch>, <claimer's epoch, if the claimer still has an executor_hosts row>)` |

So `reader_epoch` rises only in a recompute that read the host holding it down
as gone, and a host that has gone never loads the stream again (D5). No turn
rewrites it upward on the strength of its own epoch alone.

The raise is `SET writer_epoch = GREATEST(writer_epoch, :mine)`, and its guard
decides by row state:

| Row state | Append from a newer epoch |
|---|---|
| `opening`, `admitted`, `abandoned` | Raise, then append. An older executor no longer claims the row; it waits, visibly, as at admission. |
| `claimed`, `fencing`, `reaped` | Allowed only if `:mine <= reader_epoch`. Otherwise the raise matches no row and the append is refused with 409, naming both epochs: a host that may still load the stream could not read the event. The route returns that 409 to its caller unchanged, so `syn` shows it and no write is half-applied. Retry after the run ends, or once the row is `interrupted`, which takes one reconciliation turn when the reap succeeds and the fenced claimer has left. |
| `done`, `interrupted`, or no row | No executor loads the stream again; no constraint. |

The reconciler's own `WorkflowInterruptedEvent` passes the same gate. If the
fenced claimer is older than the reconciler and has not left, that append is
refused and the row waits in `reaped`, under the alert in D5, until the claimer
is retired: the claimer could not read the event, so refusing it is correct.

**Why no host ever loads an event it cannot read.** Two invariants, each held
by single-row UPDATEs that serialise on the row lock:

- **Becoming a reader.** Claim, fencing and takeover are each guarded on
  `writer_epoch <= <the host's epoch>`, and raise-then-append keeps every event
  in the stream at or below `writer_epoch`. So a host can read every event
  already in the stream at the moment it becomes a reader.
- **Staying a reader.** Until a host has left, `reader_epoch <=` its epoch, and
  every raise is held to `reader_epoch`. So it can read every event appended
  while it may still load.

Raise-then-append crosses the same two stores as D5 and is ordered the same
way: a crash between them leaves a raised epoch and no event, which can only
delay a claim, never let an old executor mis-read. Each race is therefore one
choice of order between two UPDATEs on one row:

| Race | Raise first | Other UPDATE first |
|---|---|---|
| claim and raise | the claim sees the new `writer_epoch` and matches no row for an older executor, which leaves it to a newer one | the raise sees `claimed` and is held to the claimer's epoch |
| fencing and raise | `claimed` → `fencing` matches no row for a reconciler older than the new `writer_epoch`; the row waits for a new enough executor | the raise sees `fencing` and is held to `LEAST(claimer, reconciler)` |
| reconciler A (epoch 1) in flight, B (epoch 2) takes over, epoch-2 append | while A still has an `executor_hosts` row, B's takeover matches no row and the raise is held to `reader_epoch <= 1`: refused with 409 | B's takeover can match only after A's row is gone, which happens after A's last stream load (D5: clean exit, restart or retirement). The raise is then held to the recomputed `reader_epoch`, which is 2 only if the claimer has left too. An epoch-2 event can land only when no epoch-1 host can load |
| fenced claimer X resumes while A reconciles | the raise was held to `reader_epoch <= X`'s epoch, so X's load reads it | X's load sees only events at or below `writer_epoch`, which was `<=` X's epoch when it claimed and has been held to `reader_epoch <=` X's epoch since |

If A stalls without leaving, B never takes over and no newer append lands: the
row waits, and the D5 alert names A. That is the price of the guarantee, and
it is paid in latency on one row, never in a mis-read. The implementation
carries a transition test for each cell of that table, plus one that a
recompute does not raise `reader_epoch` while the host holding it down still
has an `executor_hosts` row.

**Enforced in one place:** the repository every one of those routes gets from
`get_workflow_execution_repository()`
(`packages/syn-adapters/src/syn_adapters/storage/repositories.py:182`) is
wrapped so its `save` performs the raise first. A route cannot append to an
execution without passing the gate, and no route has to know the gate exists.
A running executor's own appends pass it, since it writes at its own epoch and
while it is the only reader that is the row's `reader_epoch`.

### D10. Upgrade without drain

| Change | Procedure | Waits for executions? |
|---|---|---|
| gateway | `pit_stop --service gateway`: swap the gateway alone | no |
| api | `pit_stop --service api`: recreate `api` alone; admission stays open | no |
| executor (Phase 1) | drain the one executor on `in_use().claimed == 0`; **admission stays open**, admitted work waits durably | yes, for that executor's runs only |
| executor (Phase 2) | start generation N+1 in its own compose project with `capacity = 0`, wait for its heartbeat, **drain** generation N naming N+1 as its successor, so N's capacity moves to N+1 as N's runs finish (D3) | no |

**Drain (of an executor)** is: `executor_hosts.draining` is set
(`PUT /executors/{host_id}/drain`, optionally naming a successor executor that
then receives its capacity, D3), the host checks it every loop turn between
claims, stops claiming, finishes what it holds (its runs, and the reconciliation and
sweep tasks it has already started), fences and adopts no new rows and starts
no new reconciliation attempt, leaving rows it still owns to be taken over once
it has left (D5), deletes its own `executor_hosts` row as its last act (D5) and exits 0. The processor
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

PR #1574 (merged 2026-10-05, after this ADR was first drafted) shipped one
execution concurrency budget and a durable start intent inside the current
single-process topology:

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
| One budget bounds every start path | **Kept.** The rule is unchanged; it moves from a per-process semaphore to the executor's own `execution_budget` row (D3, one row per executor per #1612 Step 2), checked in the claim transaction, so it holds across hosts and generations. `SYN_EXECUTION_MAX_CONCURRENT` becomes the seed for that executor's `capacity` rather than a second setting, and its memory-per-execution sizing is the measurement that capacity is taken from. With one host it is the same single number as today. |
| `ExecutionBudget` in-process FIFO hand-off | **Replaced** by the claim transaction. FIFO order is `ORDER BY admitted_at, execution_id`. |
| `queued` / `starting` as a value of `status`, for a start with no stream | **Replaced** by D11. Once admission opens the stream synchronously (1.3), there is no admitted start without a stream, so `status` carries only execution statuses and `queued` is a boolean. A `start_queue`-style position may stay as detail on the read path, computed from `execution_runs`. Changing the API field is a CLI type change through `just codegen`. |
| `ExecutionRequest` stream as the durable start record | **Not a discovery source.** Executors discover work only from `execution_runs`. Whether `ExecutionRequested` survives as the domain record of what a caller asked for, or is folded into start-only admission, is decided in 1.3; either way the `opening` sweep (D2), not a ProcessManager re-offer, is what guarantees an admitted start is never lost. |
| `holds_start` in-process duplicate-start checks | **Replaced** by `reserve` refusing a second row for one execution id, plus the stream's NoStream open. |
| Withdraw (#1650, PR #1651): `cancel` on a Queued Start withdraws its `ExecutionRequest`, and each start path re-reads the request after it holds a slot | **Becomes an ordinary cancel.** Once admission opens the stream (1.3), an admitted run already has an Execution, so `cancel` is the Execution's own. A run that is `admitted` and not yet `claimed` is cancelled by the aggregate and its row closed without being claimed; it holds no charge, so closing it changes no `in_use` (D3). The rule that a cancel landing after the start still cancels a running Execution is unchanged. If `ExecutionRequest` survives 1.3, the "re-read after taking a slot" check moves into the claim. |

#1574 merged first, so 1.2 migrates its budget and status as described above.

### D13. Executor pools, priority and overflow

*Amended 2026-10-14. The plan, the ordered steps and their exit tests are in
`docs/plans/20261014_pool-priority-placement.md`.*

An **Executor Pool** is a named group of executors sharing a priority (0
first), a provider, a region, an isolation level and capabilities, held in one
`executor_pools` row. Every `execution_budget` row names its pool. Pool
capacity and usage are sums over members: reported, never claimed against
(D3). A member's declaration that differs from the row is refused while any
other member is live and not draining.

An executor claims run *r* only when its pool satisfies *r*'s **Run
Requirements** (allowed providers, allowed regions, minimum isolation, required
capabilities), the epoch rule (D9) and `retry_at` hold, and no live executor in
a higher-priority pool that could take *r* is either claiming with room or full
for less than the claiming pool's **Overflow Delay**. "Full for" is saturation
duration: how long that executor's row has been full (`full_since`), not the
run's age. Order is oldest first everywhere. An ineligible run is never
claimed, so placement never claims and defers. A run no executor may take
stays `admitted` (D11 `queued`). Requirements whose phases conflict (an empty
provider or region intersection) are refused at admission and never queued.

Placement is recorded on the run row (`placed_pool`, `overflowed`,
`claimed_at`) as infrastructure telemetry, never as an event. In this revision
every run's requirements are empty, so placement is by priority alone.

Rejected: a pool-level counter (a second accounting surface and a hot row);
locking higher executors' rows (cross-executor contention, which D3 rules out);
a central router process (a singleton beside a claim transaction that already
decides placement); and claim-then-defer (churns tokens and penalises the run).

**Status.** The pool model has landed: the `executor_pools` table,
`execution_budget.pool_id` (existing rows join the seeded `default` pool), the
dropped `backend` column, the port values, the registration conflict rule and
`SYN_EXECUTOR_POOL_*`. The reach-and-release step has landed too (#1734): the
`RunReaper` port (scope, provider, isolation, reap by owner and execution),
`execution_budget.reap_scope` with the same-container backfill, scope-guarded
fencing and takeover (D5), and the claimer's reap-before-close gate (D3). A
pool's provider and isolation are now read from the reaper, never from
settings. Placement is not yet in the claim: every executor still takes the
oldest admitted run. The claim signals `claim_checked_at` and `full_since` (D3,
D4), priority and overflow in the claim, run requirements, and the placement
read follow in that order, as the plan sets out.

**Applying the schema (#1965).** The api and every executor apply the Run Queue
schema as they start, so they apply it concurrently. `ensure_ready` therefore
holds one session advisory lock (`RUN_QUEUE_SCHEMA_LOCK_KEY` in
`syn_adapters.advisory_locks`, beside every other startup key) for the whole
apply, taken by retrying `pg_try_advisory_lock` so a waiter holds no snapshot
(the #1906 deadlock). `schema.sql` is divided into named `-- step:` sections;
each runs in its own transaction with its row in
`execution_run_queue_schema_steps`, which records when this database first
applied it. Every step stays idempotent and runs at every start: the ledger is
a record, not a gate, so a database whose ledger is missing or behind is still
brought up to date.

**Downgrade.** Dropping `backend` does not make the Run Queue forward-only: no
code before #1931 read or wrote it. An image from before pools runs against an
upgraded database: its `CREATE TABLE IF NOT EXISTS` does nothing, its budget
insert names no pool and joins the seeded `default` one. Nothing refuses an
older image, because nothing needs to; the downgrade test in
`test_1965_run_queue_schema_postgres.py` pins this. A later step that does break
older images must say so here and refuse them explicitly.

## Consequences

### Positive

- API and gateway deploys (after Phase 1) and executor deploys (after Phase 2)
  no longer need a fully idle platform.
- An API OOM no longer takes executions with it; an executor OOM interrupts
  only that host's runs, honestly and resumably.
- One budget rule, enforced in the claim transaction against each executor's
  own capacity row, for every start path and every host; hosts of different
  sizes each get their own capacity, and global capacity is their sum.
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
- Overflow preference is approximate under concurrent release. Capacity is
  exact (D13).

### Neutral

- **Adopt / Reattach** (a new process taking over a running phase) is reserved
  for Phase 3, which is deferred and evidence-gated: no implementation issue
  until an experiment write-up under `docs/experiments/` is read.
- The ADR-014 execution model and its resume semantics are unchanged.
- ADR-070 D4/D5, revised in place, keep rotation restart-free and give each
  affected service one procedure; D10's executor drain is used only when a
  client that has not yet adopted ADR-070 D1 must restart.
