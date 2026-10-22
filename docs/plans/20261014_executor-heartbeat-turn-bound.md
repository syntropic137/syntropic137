# Plan (final): syntropic137#1944, a live executor's heartbeat goes stale during long reconciliation turns

Planned against `main` = `376ea98a7` (the commit used by the research and the review). I re-read
every file cited below in this phase. Every `file:line` is a repo-root path at that commit.

**Inputs:** `artifacts/input/research/research.md`, `artifacts/input/plan/plan.md`,
`artifacts/input/cross-model-review/review.md` (directory form). The reviewer read issue #1944
and its comments (there are none). I had only Read/Grep/Glob/Write/Skill in this phase, so I did
not run `gh`.

---

## 1. Problem

The executor loop writes its heartbeat once per turn, as the first step
(`packages/syn-adapters/src/syn_adapters/execution_host/host.py:117`). It then awaits, in series:
`sweep_opening` (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:118`), the whole
reconciliation pass (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:119`, which runs
every owned row one after another at
`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:49-57`), and claims until the
budget is full (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:120-121`). Only then
does it sleep (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:96-97`).

A reap is the guard plus one `docker rm` per selector, one after another
(`apps/syn-api/src/syn_api/services/dead_host_reaper.py:43-48`). Each `docker rm` may run a bounded
`docker stop -t 5` (`apps/syn-api/src/syn_api/services/reconciliation.py:438-458`), and the helpers'
own caps are 10 s, 20 s and 30 s (`apps/syn-api/src/syn_api/services/reconciliation.py:430`,
`apps/syn-api/src/syn_api/services/reconciliation.py:458`,
`apps/syn-api/src/syn_api/services/reconciliation.py:508`,
`apps/syn-api/src/syn_api/services/reconciliation.py:530`). So a host that has inherited a dead
peer's runs can spend more than 90 s in one turn. The staleness window is 90 s
(`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:37`, measured against
`clock_timestamp()` at `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:98`).
That happens at about 9 runs with two SIGTERM-ignoring containers each, or 18 with one. Then:

1. **D6 harm.** A new executor that starts in that window sees `others_live` → False and
   `docker rm -f`s the live host's unlabelled containers
   (`apps/syn-api/src/syn_api/services/unlabelled_containers.py:32`,
   `apps/syn-api/src/syn_api/services/unlabelled_containers.py:43`, called from
   `apps/syn-api/src/syn_api/services/execution_host_runner.py:98`).
2. **The host stops claiming, and nothing reports it.** The claim runs after reconciliation and
   checks the heartbeat against `clock_timestamp()`
   (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:128-137`). After a turn
   longer than 90 s it returns `None`. A reap that keeps failing is retried on every turn
   (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:60-67`), so this can go
   on indefinitely. **The issue says claiming is unaffected. That is wrong.** The research found
   this and the review confirmed it.
3. **Delays grow with the number of rows a host reconciles.** A drain is noticed only at the next
   heartbeat (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:117`). The last of N
   reaps waits behind the N-1 before it. One host takes every expired row at once
   (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:196-209`). Takeover adopts
   every orphaned row at once too
   (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:215-222`).

The heartbeat is not the only thing in the turn that grows with row count:

- `sweep_opening` selects every old `opening` row **and every `abandoned` row, with no age
  limit**. It then awaits one stream probe and one more connection per row, in series
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:253-276`). It runs on every
  host, so its cost tracks fleet-wide history, not per-host load.
- Claims are capped by free capacity, but each one is a multi-statement transaction
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:120-161`) and nothing caps
  their total time.

The capacity report and the reap-window alert that D4 lists are not built yet: `in_use()` never
reads `heartbeat_at` (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:279-285`).
So today the stale heartbeat misleads the claim predicate and D6. It will mislead the other two as
soon as they exist.

**North-star framing.** The targets are fleet-wide: 20 concurrent executions on one node now, 100
on one large node or a few, and 1,000 across many nodes (`docs/north-star.md:9-13`). They are not
per-host targets. What scales with them is (i) runs per host, up to whatever capacity one node is
given (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:233-239`), (ii) the size
of a dead peer's backlog, and (iii) the fleet-wide count of `abandoned` rows that every host
sweeps. The fix must hold as all three grow. Its bound must not be linear in any of them.

### What D4 says today

`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:243-263`:

- TTL 90 s, renewed every 30 s, "as a setting" (`:243`). **No setting exists.**
  `packages/syn-shared/src/syn_shared/settings/execution.py:47-105` has no lease, heartbeat or
  staleness field. Production builds the queue with defaults
  (`apps/syn-api/src/syn_api/_wiring.py:531`) and the host without `timing=`
  (`apps/syn-api/src/syn_api/services/execution_host_runner.py:89-97`).
- The heartbeat is written "at the same 30 s cadence" (`:251`). **The code writes it once per loop
  interval, 5 s** (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:48`). The 30 s
  wording is repeated in `docs/architecture/orchestration-ubiquitous-language.md:719`.
- "It is never written by a side task or an independent timer" (`:252-255`).

---

## 2. Options compared

### (b) A heartbeat on its own task, with liveness tied to loop progress

**Why D4 forbade it** (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:252-255`):
the heartbeat's first reader is the claim predicate. That predicate asks "can this loop claim
now?". A timer beside the loop would keep advertising a host that can no longer claim, reconcile
or drain.

**Does the reason still hold? Yes.** To tie the timer to progress, the loop must publish progress
marks, and the timer must decide how long a gap between marks it tolerates. That gap has to exceed
the longest single step the loop waits on. Today that step is one reap, which can take more than
90 s under the docker caps cited above, and the unpushed-work guard has no bound I could find.
So either the gap exceeds the 90 s window that every reader uses, or a slow but healthy reap makes
the host look dead again. The gap is also a number that would have to track constants in
`apps/syn-api/src/syn_api/services/reconciliation.py`, and nothing would enforce that.

More importantly, (b) fixes only what readers see. The host still claims nothing while it
reconciles (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:119-120`), still notices
a drain one long turn late, and the last of N reaps still waits behind the others. All three grow
with the north-star axes.

### (c) Both

Once the turn is bounded, a turn-progress timer protects against nothing the loop-written
heartbeat would miss. It adds (b)'s gap constant and a second writer of `heartbeat_at`. Rejected.

### (a) Bound each turn: **chosen**

The turn is bounded by structure and by a budget:

- **Docker work leaves the turn.** Reconciliation runs in tasks the loop starts and tracks, at
  most `reconcile_concurrency` at a time. This is the same way the loop already holds claimed runs
  (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:129-132`). Stop calls therefore
  run concurrently, with a bound.
- **The sweep leaves the turn.** `sweep_opening` runs as one tracked task, at most one in flight.
  Each turn checks it and starts the next pass once the previous one has finished.
- **Acquisition is spread over turns and hosts.** A host acquires new rows to reconcile (by
  fencing or by takeover) only up to its free slots. The rest wait for the next turn, or for
  another live host.
- **The claims that stay in the turn are budgeted.** Claiming stops once `turn_budget` has been
  spent, measured on an injected monotonic clock. Unclaimed admitted runs wait for the next turn.
  The budget never cancels anything, because nothing that would need cancelling is still inside
  the turn.

What the turn still awaits is: one heartbeat, at most three reconciliation store calls, and claims
until the budget is spent. **The time between two heartbeats is therefore at most
`loop_interval + turn_budget + (the slowest of those single store calls)`**, whatever N is. The
only way it exceeds the window is one store call that stalls. That is a loop that cannot claim,
and D4 says it must look dead. This is intended, not a gap. The heartbeat stays exactly where D4
put it, and D4's prohibition on side-task heartbeats is unchanged.

---

## 3. PRs, in order

### PR 1: amend ADR-072 in place (docs only)

The owner's rule is to revise ADRs in place, never supersede them. The convention is ADR-070's
status-line note (`docs/adrs/ADR-070-credential-rotation.md:5`).

`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md`:

- **Line 3 (Status):** append ` D2, D4, D5 and D10 revised in place 2026-10-14 for #1944.`
- **Line 5 (Issue):** append `, #1944`.
- **D4: replace lines 243-263 with exactly:**

> Lease TTL **90 s**, renewed every **30 s** (TTL/3). The TTL, the heartbeat staleness window
> (**90 s**), the loop interval (**5 s**), the turn budget (**15 s**) and the reconciliation
> concurrency (**4**) are one group of executor settings. The Run Queue and the claim loop are
> both built from that one group, never from separate defaults. The settings refuse a loop
> interval plus turn budget longer than a third of the staleness window. The TTL bounds
> **detection**, not effect: provided the database clock and at least one executor's loop are
> working, a host that stops renewing is seen as expired within the TTL. It does not bound the
> expiry-to-reap window in D5, which ends only when a reap succeeds.
>
> **Heartbeat** is separate from the lease. **The claim loop itself writes it**, as the first
> step of every loop turn, setting `heartbeat_at` on the executor's own `execution_budget` row
> (D3) once per loop turn, including while the executor is idle and holds no claim. Its cadence
> is the loop's, not the lease's: the loop interval is also how long an admitted run waits to be
> claimed, so it is kept short, and one write per host per interval is cheap. It is never written
> by a side task or an independent timer: a claim loop that is wedged must stop looking alive,
> and a timer beside it would keep advertising a host that can no longer claim, reconcile or
> drain.
>
> **A loop turn is bounded, so a stale heartbeat means only that the loop stopped.** A turn
> awaits the heartbeat, a fixed number of reconciliation store calls, and claims until the turn
> budget is spent; it never awaits a reap or the opening sweep. Reconciliation (D5) runs in tasks
> the loop starts and tracks, at most the reconciliation concurrency at once, as it holds claimed
> runs; the opening sweep (D2) runs as one such task. A turn checks on them and starts more; it
> does not wait for them. So the time between two heartbeats is at most the loop interval plus
> the turn budget plus one store call, however many rows exist and however slowly Docker
> answers. Only a store call that does not return can push it past the staleness window, and a
> loop stuck in one cannot claim, so it is right that it reads stale. A reap or sweep that hangs
> leaves its rows unfinished and is logged once it has run longer than the TTL; the reap-window
> alert (D5) reports the rows. It does not make a loop that can still claim look dead.
>
> Per-run lease renewal is a different write with a different meaning: a lease says that one
> run's claim is still held, while a heartbeat says only that the executor's claim loop turned
> recently. Its uses: the claim predicate (D3: an executor whose own heartbeat is stale does not
> claim), the global capacity report (live rows only), the reap-window alert (D5), and deciding
> whether an unlabelled container may be reaped (D6). It never authorises fencing or takeover.
> Fencing is decided by an expired lease. Takeover is decided by the reconciler having left
> (D5), and a stopped heartbeat is not leaving.

- **D5, lines 267-270:** replace "Any live executor may **fence** an expired row on any loop
  turn; from then on" with "Any live executor may **fence** an expired row on any loop turn,
  though no more rows per turn than it has free reconciliation slots (D4). The same limit applies
  to takeover, so a dead or departed host's rows are shared among live executors, not taken by
  whichever turns first. Each owned row gets a new attempt in least-recently-attempted order, so a
  row whose reap keeps failing never holds up the others. From then on".
- **D5, lines 386-387 (the alert):** replace "a row in `fencing` for longer than one TTL" with "a
  row whose lease expired more than one TTL ago and that is not yet `interrupted`". With bounded
  acquisition, an expired row can wait in `claimed` before anyone fences it, and the alert must
  still see it.
- **D2, lines 132-133 and 138-140:** replace "is read again next turn" with "is read again by the
  next sweep", and "re-reads the stream of every `abandoned` row on each turn" with "re-reads the
  stream of every `abandoned` row on each sweep; the loop starts a sweep whenever the previous one
  has finished (D4)".
- **D10, lines 580-581:** replace "finishes what it holds (runs and reconciliation turns)" with
  "finishes what it holds (its runs, and the reconciliation and sweep tasks it has already
  started), acquires no new rows to reconcile and starts no new attempts, leaving rows it still
  owns to be taken over once it has left (D5)".

**What changed, for the PR description:**

1. "As a setting" becomes one settings group that both consumers are built from, checked by a
   validator.
2. The heartbeat's "same 30 s cadence" becomes once per loop turn. This matches the code (5 s),
   and the reason is stated. **This resolves the 30 s vs 5 s discrepancy: the code is right and
   the ADR is wrong.** 30 s is the lease renewal cadence (TTL/3,
   `packages/syn-adapters/src/syn_adapters/execution_host/host.py:52-54`). A 30 s loop would make
   every admitted run wait up to 30 s to be claimed, and would leave only three heartbeats per
   90 s window.
3. A new paragraph bounds the turn, which is what keeps the side-task prohibition workable.
4. The prohibition itself is unchanged, word for word.

**Vocabulary, in the same commit:** replace
`docs/architecture/orchestration-ubiquitous-language.md:718-721` ("made by the claim loop itself
as the first step of every turn, on the Lease's 30 s cadence and including while idle with no
Claim. Never a side task or separate timer:") with "made by the claim loop itself as the first step
of every turn, once per loop interval (5 s), and including while idle with no Claim. A turn is
bounded: it never waits for a reap or the opening sweep, and it stops claiming once its turn budget
is spent, so the heartbeat stops only when the loop does. Never a side task or separate timer:".
Nothing checks that the ADR and this file agree, so the PR checklist has to say both changed.

### PR 2: bounded, fair reconciliation and a bounded turn (fixes #1944)

All of it is in `packages/syn-domain` (port) and `packages/syn-adapters`. No submodule change. By
the CLAUDE.md boundary test this is domain meaning, not harness knowledge. The port change, the
adapters, the host rewrite and the deterministic tests land together: the fairness rule and the
acquisition limit are one design, and splitting them leaves a release where one is in place
without the other (review B2/B3).

**2a. Port**
(`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:150-161`).
Acquisition and reading are separated, and every acquisition is bounded:

- `fence_expired(reconciler, *, limit: int) -> list[FencedRun]`: at most `limit` expired `claimed`
  rows → `fencing`, oldest `leased_until` first.
- New `take_over(reconciler, *, limit: int) -> list[FencedRun]`: at most `limit` `fencing`/`reaped`
  rows whose reconciler has left, under a new token. Same predicate as today
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:216-220`). Order is
  `leased_until, execution_id`.
- `reconciling(reconciler) -> list[FencedRun]`: becomes **read-only**. It returns the rows this host
  owns and adopts nothing. Its docstring loses "First takes over" (`:157-160`), and that text moves
  to `take_over`.

Only `Reconciler` calls these, so the policy (how many rows, and when) lives in one place. Every
caller passes `limit`, so no unbounded call remains. "Takeover" and "Fencing" are already terms in
`docs/architecture/orchestration-ubiquitous-language.md`, so the port adds no new term.

**2b. Adapters**

- Postgres (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:196-231`):
  - `fence_expired` becomes `UPDATE … FROM executor_hosts h WHERE r.execution_id IN (SELECT
    execution_id FROM execution_runs WHERE state='claimed' AND leased_until<now() AND
    writer_epoch<=h.epoch ORDER BY leased_until, execution_id FOR UPDATE SKIP LOCKED LIMIT $2)`.
  - `take_over` is the current adoption UPDATE, with the same `IN (… FOR UPDATE SKIP LOCKED
    LIMIT $2)` shape.
  - `reconciling` keeps only its SELECT (`:223-230`).
  - `SKIP LOCKED` keeps two adopters from blocking on each other. The outer predicate is
    re-checked after the lock, which preserves the "second adopter finds a live owner" property
    in the comment at `:213-214`.
- Memory (`packages/syn-adapters/src/syn_adapters/execution_runs/memory.py:179-227`): the same
  order and limit. `reconciling` stops calling `_adoptable`/`_put`, and `take_over` gets that code.

**2c. `Reconciler`**
(`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:23-72`) owns its in-flight
work behind a small interface:

- `__init__(…, *, concurrency: int, clock: Callable[[], float], lease_ttl: float)`.
- `async def turn(self, *, acquire: bool) -> None`. **It never awaits a reap.** In order:
  1. Collect finished tasks. Each task already logged its own outcome.
  2. `owned = await queue.reconciling(host)`.
  3. If `acquire`: `free = concurrency − busy`, where `busy` = tasks in flight + owned rows this
     Reconciler has never attempted. If `free > 0`, call `take_over(limit=free)`, then call
     `fence_expired(limit=free − taken)` if any slots are left. The fence WARNING
     (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:45-48`) is kept. **A row
     that has been attempted and is waiting to retry does not count against `free`.** So rows
     whose reaps keep failing never stop a host acquiring and attempting the healthy ones
     (review B3).
  4. If `acquire`: start tasks up to `concurrency − in_flight`, on owned rows not in flight,
     **least recently attempted first**. A never-attempted row counts as attempted at the turn it
     was acquired, and ties break by `execution_id`. Each owned row is therefore attempted again
     within `⌈owned / concurrency⌉` turns. A draining host (`acquire=False`) starts nothing new.
- `idle: bool` is true when nothing is in flight.
- `aclose()` cancels the in-flight tasks and awaits them. It is used only on shutdown.
- `_advance_logged(run)` wraps today's `try/except RunLeaseLost / Exception`
  (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:50-57`), so a failed task
  logs exactly what the serial loop logged. Nothing is lost the way a background task can lose it
  (CLAUDE.md, "Background Task Error Handling"). `_advance`
  (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:59-72`) does not change,
  so the row's transition sequence stays hidden inside the Reconciler.
- At each turn, any task running longer than `lease_ttl` gets one WARNING: `Reconciling %s has run
  %ds; its reap may be hung`. Until the D5 alert exists, this is the only signal for a hung guard.
- **What the in-memory state is.** The in-flight dict is keyed by `execution_id`, which gives
  per-row exclusion inside the process. `_last_attempt: dict[str, int]` is a scheduling hint. It
  is never state: a restart is a new `host_id`
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:328-329`), so nothing is
  lost. Between processes, the reconciler column and token already guard rows
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:233-244`), so D5's "two turns
  on one row never overlap" (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:309-311`)
  holds. Entries for rows no longer in `owned` are dropped each turn.
- The class docstring's "Holds nothing between turns" (`:26`) becomes "Holds only the tasks it
  started and when each row was last attempted; what a row has reached is always read from the
  row".

**2d. `ExecutionHost`** (`packages/syn-adapters/src/syn_adapters/execution_host/host.py`):

- `HostTiming` (`:44-54`) gains `turn_budget: timedelta = 15 s` (`gt=0`) and
  `reconcile_concurrency: int = 4` (`ge=1`). It also gains a `model_validator`:
  `loop_interval + turn_budget <= lease_ttl / 3`. The window is the TTL here because the two
  default to the same value; PR 3 moves the check onto the staleness setting. Both new fields go
  to the `Reconciler` built at `:78`.
- New keyword-only constructor parameters `sleep: Callable[[float], Awaitable[None]] =
  asyncio.sleep` and `clock: Callable[[], float] = time.monotonic`. They are the only test seams,
  and no other branching is added. `sleep` replaces `asyncio.sleep` at `:97` and is passed to
  every `LeaseKeeper`.
- **`LeaseKeeper`** (`packages/syn-adapters/src/syn_adapters/execution_host/lease.py:26`) becomes
  `__init__(self, queue, run, every, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep)`,
  used at `packages/syn-adapters/src/syn_adapters/execution_host/lease.py:34`. Each keeper task is
  named `lease:<execution_id>` (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:137`),
  which makes the logs clearer and lets the test scheduler tell sleepers apart.
- `_turn` (`:113-127`):
  ```
  started = clock()
  draining = await heartbeat(...) or draining
  self._tend_sweep(start=not draining)       # collect/log finished pass; start next; warn if > TTL
  await self._reconciler.turn(acquire=not draining)
  while not draining and clock() - started < turn_budget and (claimed := await claim(...)):
      self._spawn(claimed)
  ```
  The sweep task is named `sweep-opening`. An exception from it is logged at ERROR with the same
  text as the turn handler.
- Drain exit (`:96`): `while not (await self._turn() and not self._runs and self._reconciler.idle
  and self._sweep is None)`.
- Cancel path (`:98-103`): also `await self._reconciler.aclose()` and cancel and await the sweep
  task. Rows stay `fencing`/`reaped`, and once this host deregisters (`:104-105`) another host
  takes them over.
- Module docstring (`:3-10`): step 2 becomes "start the opening sweep if none is running (D2)".
  Step 3 becomes "acquire up to the free reconciliation slots, and start reconciliation tasks
  without waiting for them (D5)". Step 4 gains "until the turn budget is spent".

**2e. Unchanged, on purpose.** The reaper and the docker helpers
(`apps/syn-api/src/syn_api/services/dead_host_reaper.py`,
`apps/syn-api/src/syn_api/services/reconciliation.py`) do not change. They are shared with the
flag-off startup reap (`apps/syn-api/src/syn_api/services/execution_host_runner.py:64`). Once the
turn no longer waits for them, their speed only affects the D5 window.

**2f.** Correct the V7 docstring
(`apps/syn-api/tests/integration/test_1310_v7_a_killed_executor_is_reaped_by_a_live_one.py:15-19`):
a busy turn no longer reads as stale. Keep `_turned_since_now` (`:81-90`).

### PR 3: one settings group, so the timings cannot drift

Before `SYN_EXECUTION_RUN_QUEUE_ENABLED` is turned on anywhere, this PR must merge. The flag is off
by default and documented as unsafe
(`packages/syn-shared/src/syn_shared/settings/execution.py:95-105`), so until then the `HostTiming`
defaults reach no production path.

- `packages/syn-shared/src/syn_shared/settings/execution.py`: add `lease_ttl_s=90`,
  `heartbeat_stale_s=90`, `loop_interval_s=5`, `turn_budget_s=15` and `reconcile_concurrency=4`.
  Each is `gt=0` or `ge=1`, has a description, and has its env name as a constant per ADR-004. Add
  a `model_validator` that raises unless `loop_interval_s + turn_budget_s <= heartbeat_stale_s / 3`
  and `heartbeat_stale_s <= lease_ttl_s`.
- `apps/syn-api/src/syn_api/_wiring.py:531` builds `PostgresExecutionRunQueue(pool, lease_ttl=…,
  heartbeat_stale=…)`. `apps/syn-api/src/syn_api/services/execution_host_runner.py:89-97` passes
  `timing=HostTiming(…)`. Both read the same `get_settings().execution`, so `HostTiming`'s "must
  be the TTL the queue was built with"
  (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:45`) becomes true by construction.
- Regenerate `.env.example` through the usual ADR-004 path.

**Order:** PR 1, then PR 2, then PR 3. PR 1 goes first so the owner revises the decision before
code follows it. PR 2 fixes #1944 completely. PR 3 needs PR 2's new fields and is a hard gate on
enabling the flag.

**Maintenance cost:**

- About 70 more lines in `Reconciler`: the task dict, last-attempt order, `idle`, `aclose`, and
  the long-task warning.
- One sweep task in the host.
- Two timing fields and two injected seams.
- One new port method and two `limit` parameters, each in two adapters.
- One settings group with a validator.
- One idea for readers: reconciliation and the sweep run beside the loop, not inside it. `_runs`
  already works that way. There is no new liveness rule and no new heartbeat writer.

---

## 4. Other alternatives rejected

- **A wall-clock budget that cancels reaps in flight.** `_docker_rm` kills its subprocess only on
  its own timeout (`apps/syn-api/src/syn_api/services/reconciliation.py:506-512`,
  `apps/syn-api/src/syn_api/services/reconciliation.py:529-533`). An outside cancel leaves the
  `docker` CLI running and can interrupt the guard's quarantine push. The chosen budget stops only
  new claims, so it never needs to cancel anything.
- **A heartbeat between rows inside the serial reconciler.** One row can still take more than 90 s.
  It would also make the reconciler a second heartbeat writer, which is the coupling D4 exists to
  prevent.
- **Raising `heartbeat_stale` to around 300 s.** That moves the threshold from about 9 rows to
  about 30, and a node's capacity passes it again. It would also delay D6 and the D5 alert on
  every host.
- **Capping a host's ownership at `reconcile_concurrency`.** This would spread rows well, but four
  rows that never reap would stop a lone Phase 1 executor
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:574`) from ever reconciling a
  fifth. That is review B3's starvation moved from scheduling to acquisition. The rule in 2c
  counts only rows that have not yet been attempted.

---

## 5. Risks

| Risk | What would break | Signal / mitigation |
|---|---|---|
| Four concurrent reaps load the Docker daemon, and the guard runs up to four quarantine pushes at once | `docker stop`/`rm` time out more often, so more reaps report incomplete and retry | The existing WARNINGs get more frequent: `docker stop timed out` (`apps/syn-api/src/syn_api/services/reconciliation.py:459-467`) and "not shown complete" (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:62-66`). The default 4 is a guess and becomes a setting in PR 3 |
| The guard hangs (no bound found), holding a slot while the host looks live | Reconciliation loses one slot per hung task. Claiming is unaffected | PR 2's WARNING once a task has run longer than the TTL. The D5 alert would catch it but **is not built** (decision 3) |
| A host whose Docker is broken fails every reap, so it keeps acquiring up to `concurrency` rows per turn | That host gathers a growing share of a dead peer's rows, and they stay `fencing` | Repeated "not shown complete" WARNINGs. **No worse than `main`**, where one turn fences every expired row (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:196-209`). A follow-up could stop acquisition after K consecutive failures |
| An exception in a task is swallowed | A row stops advancing and nothing is logged | `_advance_logged`, and the sweep's ERROR log. Pinned by tests T13 and T4 |
| A draining host no longer fences, takes over, or starts attempts | Expired rows wait for a host that is not draining. With one executor draining, they wait for the next generation | A behaviour change, stated in PR 1. Owner decision 4 |
| Shutdown cancels the task but not its child process. Cancelling a reconcile task leaves an in-flight `docker` CLI child running, because the helpers clean up only on their own `TimeoutError` (`apps/syn-api/src/syn_api/services/reconciliation.py:459`, `apps/syn-api/src/syn_api/services/reconciliation.py:506`, `apps/syn-api/src/syn_api/services/reconciliation.py:529`) | An orphaned `docker stop`/`rm` finishes on its own after the host has deregistered (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:104-105`), while the taking-over host may already be reaping the same containers | **Already true on `main`**: cancelling `run_until_drained` mid-turn cancels the same awaited reap. The docker commands are idempotent removals, so a double `rm` fails harmlessly and the row's token decides the outcome. Tracked as a follow-up issue (below). T12 asserts task shutdown only and does **not** claim subprocess cleanup |
| PR 2 SQL: `SKIP LOCKED` with `LIMIT` inside `UPDATE … IN (subquery)` | Two hosts double-fence or double-adopt a row, or a row starves | Postgres contract tests run two acquirers concurrently. Ordering by oldest expiry prevents starvation |
| PR 3 validator rejects an existing deployment's env | The API fails at startup | None of these variables exist today, so no deployment sets them |

---

## 6. Verification (deterministic, no sleeps)

### Harness

The new unit module is `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py`,
next to `packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py`, with
`pytestmark = pytest.mark.unit`. It uses the real `InMemoryExecutionRunQueue` with its injected
`clock` (`packages/syn-adapters/src/syn_adapters/execution_runs/memory.py:66-74`), so the heartbeat
is written and read by the same code the queue contract tests pin.

**`_FakeTime`: a deadline-aware scheduler**, replacing the shared stepped clock that review B4
rejected:

- It holds `mono: float` and `now: datetime`, moved together. `now()` is the queue's clock and
  `monotonic()` is the host's clock.
- `async sleep(seconds)` registers a waiter `(deadline = mono + seconds, tag =
  asyncio.current_task().get_name(), future)` and awaits the future. Each sleeper has its own
  waiter and its own deadline: the host loop's 5 s and each keeper's 30 s stay distinct.
- `async advance(seconds)` repeatedly pops the earliest waiter whose deadline is at or before the
  target. It moves time to `max(mono, deadline)`, resolves that waiter only, and then awaits **that
  tag's acknowledgment**: the same tag registering its next waiter, or its task finishing. Last,
  it moves time to the target. Since the host loop's task is named `execution-host` (as in
  production, `apps/syn-api/src/syn_api/services/execution_host_runner.py:99`), each host wake is
  acknowledged by the host re-entering `sleep`. **One host wake is exactly one host turn**, and
  keepers renew only at their own deadlines. The acknowledgment wait has a 1 s `asyncio.timeout`.
  That is a hang guard that turns a deadlock into a named failure, not a sleep.
- `spend(seconds)` moves time forward synchronously and wakes nobody. It models one store call
  taking that long inside the task that awaits it.
- `host_turns: int` counts host acknowledgments.

**Doubles:**

- `_GatedReaper.reap()` records the call, tracks in-flight counts per row and in total, and awaits
  a per-row `asyncio.Event` that the test controls. This is the injected slow stop: it never
  returns until released. The `complete` result is scriptable per row.
- `_GatedDrainer.run_claimed()` waits on an Event, so a claimed run stays claimed and observable
  while its keeper runs. This replaces the unblocked double at
  `packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py:107-115` for these
  tests.
- `_SlowClaimQueue(InMemoryExecutionRunQueue)`: `claim` calls `time.spend(3)` and then `super()`.
  `heartbeat` records `time.mono`.
- `_GatedStreams.presence()` awaits a gate.
- `_WedgedQueue`: `reconciling` awaits a gate that is never released.

**Setup** for the reconciliation tests: register host `dead` with capacity 20; `reserve`,
`mark_admitted` and `claim` 20 runs as `dead`; `spend(91)` so the leases expire; register host
`live`; start `live.run_until_drained()` in a task named `execution-host`, with `sleep=time.sleep`
and `clock=time.monotonic`.

### Tests

| # | Test | Asserts | Fails with the fix reverted? |
|---|---|---|---|
| T1 | `test_a_live_host_reconciling_20_blocked_reaps_never_reads_stale` | 40 × `advance(5)` (200 s fake, more than twice the window). After each: the acknowledgment arrived, `others_live("observer")` is True, and total in-flight reaps ≤ 4. Then release all gates and advance until `in_use().interrupted == 20` | **Yes.** On `main` the first turn blocks in `reap`, so `advance` hits the hang guard: "host did not finish a turn". The mutation that makes `turn()` await its tasks fails the same way |
| T2 | `test_a_reconciling_host_still_claims_new_work` | With reaps saturated, admit one run. After one `advance(5)`, `in_use().claimed` has gone up, the run is held by `live` (gated drainer), and after `advance(30)` the keeper has renewed it once | **Yes**: on `main` the claim is never reached. This pins claim starvation |
| T3 | `test_a_turn_of_slow_claims_stays_within_its_budget` (review B1) | `live` with capacity 100 and 100 admitted runs; every claim takes 3 s. Each turn's length (the recorded heartbeat's `mono` to the next sleep entry) is ≤ `turn_budget + 3 s`. After every `advance(5)`, `others_live` is True. Eventually all 100 are claimed, over several turns | **Yes, with the budget removed**: one turn runs about 90 s, until the in-memory claim predicate finds the host stale (`packages/syn-adapters/src/syn_adapters/execution_runs/memory.py:264-271`), and the turn-length assertion fails |
| T4 | `test_a_blocked_opening_sweep_does_not_stop_the_loop` (B1) | 50 `abandoned` rows, probes gated. 40 × `advance(5)`: the host keeps turning and claiming, `others_live` stays True, and there is never more than one `sweep_opening` call in flight. After a sweep that raises, `caplog` has the ERROR and the next turn starts a new pass | **Yes**: on `main` the sweep is awaited in the turn |
| T5 | `test_a_wedged_loop_goes_stale` | `_WedgedQueue`; `spend(91)`: `others_live("observer")` is False, and a direct `queue.claim("live")` returns `None` | **No, and intentionally**: preservation coverage, the "a genuinely dead host still does" half. It kills the mutation that adds an unconditional heartbeat timer |
| T6 | `test_a_host_that_stopped_turning_reads_stale_after_the_window` | The host is parked in `sleep` and `spend` is called without `advance`. At 89 s it is still live; at 91 s it is stale | No. It pins the window boundary on the in-memory twin. Related, but not equivalent, to `packages/syn-adapters/tests/test_execution_run_queue_postgres.py:242-248`, which checks `claim` against a 0.2 s threshold with a real sleep |
| T7 | `test_one_row_is_never_reaped_by_two_tasks_at_once` | Across 40 advances with gates closed, no `execution_id` ever has more than one concurrent `reap` | Yes, if `turn()` re-dispatches rows already in flight (D5 exclusivity) |
| T8 | `test_rows_that_keep_failing_do_not_starve_later_rows` (B3) | `live` owns 6 rows with concurrency 4; the first four by `execution_id` always return `complete=False` straight away. Within 3 turns, rows 5 and 6 are `interrupted`, and every one of the 6 has been attempted at least twice within 4 turns | **Yes, with the mutation "start in `execution_id` order"**: rows 5 and 6 never run. The all-gates-open T1 would not catch this |
| T9 | `test_a_departed_reconcilers_backlog_is_shared` (B2) | Host `a` owns 10 `fencing` rows and deregisters. Live `b` and `c` (concurrency 4) take alternate turns. After one turn each, each owns ≤ 4 and their rows don't overlap. All 10 end `interrupted` | **Yes, with `take_over` unbounded**: `b` takes all 10 |
| T10 | `test_a_draining_host_acquires_nothing` (B2) | A draining host that owns nothing, with expired rows and orphaned rows present: no `fence_expired`/`take_over` call, no `reap`, and `run_until_drained` returns at the first idle turn | Yes, if acquisition ignores `acquire=False` |
| T11 | `test_draining_finishes_started_reconciliation_and_leaves_the_rest` | Saturate, `drain()`, then release the gates: `run_until_drained` returns only after the 4 started tasks have finished. Rows it owned but had not started are still `fencing`, and after deregistration another host's `take_over` gets them | Pins the D10 amendment |
| T12 | `test_shutdown_cancels_reconciliation_and_sweep_tasks` | Cancel the host task while saturated: each gated `reap` and the gated probe saw `CancelledError`, the rows are `fencing`, and the host deregistered. It claims **task** shutdown only, not subprocess cleanup (risk table) | Yes, if `aclose()` or the sweep cancel is missing: tasks leak |
| T13 | `test_a_failed_reconciliation_task_is_logged` | The reaper raises `RuntimeError`; `caplog` has "Reconciling … failed" at ERROR, the row is still `fencing`, and it is retried on a later turn | Yes, if the try/except is lost in the move into a task |
| T14 | `test_a_reap_running_longer_than_the_ttl_is_warned` | Gated reap, then `advance` past 90 s: exactly one WARNING naming the row | Yes, if the warning is missing |

**Existing tests.** The tests in
`packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py:213-259` call
`Reconciler.turn()` and expect the work to be done when it returns. Their assertions stay. They
change to `await reconciler.turn(acquire=True)` followed by `await _settle(reconciler)`, a
test-file helper that awaits `asyncio.sleep(0)` until the production `idle` property is True,
giving up after 100 iterations. It uses no wall clock and adds no test-only method to production
(review I2). Because the doubles never block, settling is deterministic. The retry-across-turns
semantics at `:231-245` are kept as they are: one `turn` and `_settle` per turn. The `_Queue`
double gains `take_over` and the `limit` parameter (`:75-81`).

The loop tests share `_FAST` (`:30-34`: 5 ms loop, 30 ms TTL). With the new validator and the
default 15 s budget they would **fail** at construction, because 5 ms + 15 s is more than 30 ms / 3.
PR 2 therefore sets `turn_budget=timedelta(milliseconds=4)` in `_FAST`, which passes
(5 + 4 = 9 ms ≤ 10 ms).

**Queue contract tests**, for both
`packages/syn-adapters/tests/test_execution_run_queue_memory.py` and
`packages/syn-adapters/tests/test_execution_run_queue_postgres.py`:

- `fence_expired(h, limit=2)` over 5 expired rows fences exactly the 2 oldest by `leased_until`.
  A second host's `fence_expired(h2, limit=10)` fences the other 3.
- `take_over(h, limit=2)` over 5 orphaned rows adopts 2. While the reconciler is still registered,
  `take_over` adopts nothing.
- `reconciling(h)` adopts nothing. It returns only rows already owned.
- Postgres only: two concurrent fencers, and two concurrent adopters (`asyncio.gather`), never
  return the same row twice.

On `main` these fail because the parameters and `take_over` don't exist and `reconciling` adopts.

**PR 3:** `ExecutionSettings(loop_interval_s=10, turn_budget_s=25, heartbeat_stale_s=90)` raises
`ValidationError`. A wiring test asserts that the queue's `_stale_seconds` and `HostTiming` come
from one `ExecutionSettings` instance with overridden values.

**Commands** (repo root):

```
uv run pytest -m unit packages/syn-adapters/src/syn_adapters/execution_host/ -q
uv run pytest -m unit packages/syn-adapters/tests/test_execution_run_queue_memory.py -q
uv run pytest -m integration packages/syn-adapters/tests/test_execution_run_queue_postgres.py -q
uv run pytest -m integration apps/syn-api/tests/integration/test_1310_v7_a_killed_executor_is_reaped_by_a_live_one.py apps/syn-api/tests/integration/test_1310_v12_a_stalled_executor_is_fenced_by_a_live_one.py apps/syn-api/tests/integration/test_1310_execution_host_claims_fences_and_reconciles_on_real_stores.py
just preflight-agent
uv run pytest -m unit -q
```

**Mutation evidence** is committed under `.mutations/`. It needs Docker, so the orchestrator runs
`just mutation-evidence`.

| Patch | Must be killed by |
|---|---|
| `1944-await-reconciliation.patch` (`turn()` awaits its tasks) | T1, T2 |
| `1944-unbounded-claims.patch` (budget check removed) | T3 |
| `1944-sweep-in-turn.patch` (sweep awaited) | T4 |
| `1944-unconditional-heartbeat-task.patch` | T5 |
| `1944-execution-id-order.patch` (no least-recently-attempted order) | T8 |
| `1944-unbounded-take-over.patch` | T9 and the contract tests |

---

## 7. Out of scope, to file as issues

- **Make the `abandoned` re-probe incremental.** It still grows with fleet history
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:254-257`). After PR 2 it no
  longer affects liveness, only how quickly a late `abandoned` row is promoted.
- **Clean up docker child processes on outside cancellation** in
  `apps/syn-api/src/syn_api/services/reconciliation.py:438-533` (review I3). Pre-existing, and
  shared with the flag-off path.
- **Bound `save_unpushed_work`** (research open question 2).
- **Build the capacity report and the D5 reap-window alert** (#1310/#1734).
- **Optional: stop acquisition after K consecutive failed reaps** (risk table, broken-Docker host).

## 8. Needs a human decision

1. **Cadence: 5 s, not 30 s.** I changed the ADR to match the code, because the loop interval is
   also the claim latency. The owner should confirm 30 s was never meant to be that.
2. **Defaults: 4 concurrent reconciliations and a 15 s turn budget.** These are provisional, not
   measured. The north star wants limits sized from measurement (`docs/north-star.md:227-228`), and
   nothing yet measures concurrent `docker stop` or concurrent guard-push cost on flywheel. PR 3
   makes both settings.
3. **Should the D5 reap-window alert block enabling the flag?** After this fix, a hung reap hides
   behind a live host, and only PR 2's WARNING reports it. I recommend making the alert a P1
   blocker for `SYN_EXECUTION_RUN_QUEUE_ENABLED`. That is a prioritisation call, so it is not mine
   to make.
4. **A draining host stops acquiring and starts no new attempts (D10 amendment).** This is a
   behaviour change that the owner should accept explicitly in PR 1's review.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1: the structural bound does not cover the sweep or the claims | **Accepted** | Checked: the sweep is serial over every abandoned row (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:253-276`), and the claims are uncapped in time (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:120`). The sweep becomes a tracked task, at most one in flight. Claims stop at a `turn_budget` on an injected monotonic clock. The D4 text now states the real bound, `loop_interval + turn_budget + one store call`, and why a single stalled call correctly reads stale. The validator now covers the budget as well as the interval. Added T3 (cumulative slow claims) and T4 (blocked sweep). T5's wedge moved from `sweep_opening`, which is no longer in the turn, to `reconciling` |
| B2: takeover is unbounded and a draining host adopts | **Accepted** | Checked: `reconciling` adopts every orphaned row (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:215-222`; port docstring `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:157-160`). The port is split: `reconciling` becomes read-only and the new `take_over(limit)` sits beside `fence_expired(limit)`. Both are bounded by one free-slot count, with "busy" defined as in flight + never attempted. A draining host acquires nothing. The fencing and takeover PRs merge into PR 2, so acquisition and scheduling ship together. Added T9, T10, T11 and contract tests |
| B3: bounded concurrency starves healthy rows behind failing ones | **Accepted** | Checked: rows are ordered by `execution_id` (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:228`), and an incomplete reap returns without advancing (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:60-67`). Least-recently-attempted scheduling, with rows already attempted excluded from the acquisition cap, gives each row a retry within `⌈owned/concurrency⌉` turns. I rejected capping ownership at concurrency (section 4) because it moves the same starvation into acquisition. Added T8 with an `execution_id`-order mutation |
| B4: the shared stepped sleeper is not deterministic | **Accepted** | Checked: the host sleeps 5 s (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:97`) and each keeper sleeps TTL/3 (`packages/syn-adapters/src/syn_adapters/execution_host/lease.py:34`) in its own task (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:137`). Replaced with `_FakeTime`: a waiter and deadline per sleeper, tagged by task name, woken one at a time in deadline order, each acknowledged by that tag's next sleep. The `LeaseKeeper` signature change is now explicit, and keeper tasks are named. T2 uses a gated drainer. The await-reconciliation mutation is kept |
| I1: citations and evidence claims | **Accepted** | Every citation is now a repo-root path. The north star is described as fleet-wide (`docs/north-star.md:9-13`), with per-host N treated as a scenario to withstand. The Postgres test at `packages/syn-adapters/tests/test_execution_run_queue_postgres.py:242-248` is called related, not equivalent. T5 and T6 are labelled preservation coverage |
| I2: a test-only `drained()` on the production reconciler | **Accepted** | Removed. Existing tests settle through a test-file helper that yields with `asyncio.sleep(0)` until the production `idle` property is True. The retry-across-turns structure at `packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py:231-245` is kept, and `_advance` stays hidden. I also found that `_FAST` (`packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py:30-34`) would fail the new validator, so PR 2 sets its `turn_budget` |
| I3: subprocess cleanup on cancellation is untested | **Accepted as tracked work, not fixed here** | The risk table now separates task shutdown from subprocess shutdown, and notes the leak already exists on `main` (cancelling `run_until_drained` mid-turn cancels the same awaited reap). T12 is explicitly limited to task shutdown. Filed as a follow-up in section 7 |
| Review's "settings must not sit behind an indefinite hard-coded interval" | **Accepted** | PR 3 is now a hard gate before `SYN_EXECUTION_RUN_QUEUE_ENABLED` is enabled (off by default, `packages/syn-shared/src/syn_shared/settings/execution.py:95-105`). The defaults are labelled provisional (decision 2) |

No finding was rejected. Each one held up when I checked it against the code at `376ea98a7`.

## Readiness

Ready to implement PR 1 and PR 2 once the owner accepts decisions 1 (5 s cadence) and 4 (draining
hosts stop acquiring) in PR 1's review. Decision 3 (the D5 alert as a flag blocker) gates enabling
the flag, not this work.

