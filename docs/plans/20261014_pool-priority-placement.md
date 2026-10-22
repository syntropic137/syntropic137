# Plan: Executor Pools in priority order, with overflow, then queue

**Status:** approved 2026-10-14 with the orchestrator's defaults, which the owner may revise:
D1 land PR 0-3 now; D2 the §6 ADR-072 amendment, applied in place; D3 the grace period is
saturation duration (`full_since`). PR 0 (this file, the amendment, the vocabulary) and PR 1
(the pool model) landed together in one PR. PR 2 (reap scope and reap-before-close, refs #1734) is in review; PR 3-6 are not started. The body below is the
plan as reviewed; its `file:line` citations are to `6b5b0abe6` and drift as the PRs land.

**Read on:** `main` as checked out in the workspace (`6b5b0abe6`, the merge of #1894). Every
`file:line` below was re-read in this phase unless it is marked *(research phase)*.

**Branch-only documents.** `docs/plans/20261013_provider-neutral-execution.md`,
`docs/plans/20261013_selfhosted-microvm-pool.md` and
`docs/research/2026-10-12-harbor-opensandbox-runtime-design.md` exist only on
`origin/docs/runtime-research-20261012`. `Glob docs/plans/202610*` finds nothing on this checkout.
The reviewer read them from the remote ref. This phase has no git tool, so it could not. Claims
about them below are the research phase's, marked *(research phase)*. Nothing in the design depends
on them, apart from the input "a pool = provider + account/region config", which the reviewer
confirmed independently.

---

## Summary

- An **Executor Pool** is one row in a new `executor_pools` table. Each executor's
  `execution_budget` row names its pool. Capacity stays per executor. Pool capacity is a derived
  sum.
- `claim(host_id)` keeps its signature and decides placement in its one transaction. An executor
  takes run *r* only when:
  - its pool satisfies *r*'s requirements; and
  - no higher-priority executor that could take *r* is either **claiming with room** or **full for
    less than the overflow delay**.
- "Claiming" is a new durable signal, `claim_checked_at`. The claim statement stamps it, so a
  heartbeat alone no longer advertises room. That closes the starvation case the review found.
- No slot is freed until the backend shows the run's resources gone. That holds on the normal
  `close` path as well as on reconciliation. Reconcilers can reap only inside their own
  **reap scope**.
- Run requirements are a typed contract covering provider, region, isolation and capabilities. It
  ships in v1 with an empty producer, so v1 places by priority only.
- The run stays `admitted` (D11 `queued`) while no executor may take it.
- Seven PRs, each with exit tests on real Postgres. ADR-072 is amended in place.

---

## The premise holds, with two caveats

The research findings this plan relies on, each re-checked:

| Finding | Evidence |
|---|---|
| `execution_budget.backend` is declared and never written or read | declared at `packages/syn-adapters/src/syn_adapters/execution_runs/schema.sql:14`; insert omits it at `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:307-313` |
| The claim locks only its own budget row, checks room, drain and heartbeat with `clock_timestamp()`, then takes the oldest admitted run | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:120-161` |
| The run's only eligibility filters are `retry_at` and `writer_epoch` | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:142` |
| ADR D3 step 1 still shows the older predicate-in-lock SQL | `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:166-169` |
| Release is token-guarded, `in_use-1`, with successor transfer | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:333-382` |
| `ExecutorHost` has no pool or backend field | `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:41-49` |
| One host runs inside the API process, sized by `max_concurrent` | `apps/syn-api/src/syn_api/services/execution_host_runner.py:83-97` |
| The run queue is off by default, and its description is stale ("nothing claims ... until the ExecutionHost lands") | `packages/syn-shared/src/syn_shared/settings/execution.py:95-105` |
| Default capacity is 4; the "10" is the operator's VPS override | `packages/syn-shared/src/syn_shared/settings/execution.py:24`, `docs/north-star.md:35` |

**Caveat 1: nothing exists to overflow to yet.** The only executor lives inside the API process,
and there is no `SYN_PROCESS_ROLE=executor` service (ADR-072 D1). At "Now = 20 on one node"
(`docs/north-star.md:11`), pools add no concurrency. "Next = 100" needs "executors split from the
API" (`docs/north-star.md:12`). Pools are the placement model that split needs, and it must be
right before the run queue carries live data.

**Caveat 2: a latent multi-host safety gap, found by the plan phase and kept by the review.**

- `DockerDeadHostReaper.reap` removes containers from the reconciler's **own** Docker daemon and
  returns `not failures` (`apps/syn-api/src/syn_api/services/dead_host_reaper.py:36-51`).
- Fencing and takeover accept any epoch-compatible reconciler
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:199-203`, `:216-220`).
- So a reconciler on another machine "reaps" nothing, reports success, and `close_interrupted`
  frees a slot whose workspace may still be running.

That breaks D3 ("a crash can hold a slot ... but can never free one early") as soon as a second
machine exists. PR 2 fixes it before any overflow.

---

## Problem

Today an admitted execution goes to whichever live, non-draining executor next finds room in its
own budget. There is no way to:

- prefer the local VPS and spill to another pool only when the VPS is full;
- restrict a run to pools that can satisfy it (nested Docker, provider, region, isolation);
- see per-pool capacity, queue depth, or where runs went and why.

The observable goal:

1. Runs fill pools in priority order.
2. A lower pool takes a run only when every higher pool that could take it is full for longer than
   the overflow delay, or is not claiming.
3. A run no pool can take stays `admitted` and is counted as such.
4. No slot is freed while its resource might still exist.
5. Each executor's capacity remains the only number anything claims against.

---

## 1. Model

**An Executor Pool is a named group of executors that share a priority, a provider, a region, an
isolation level and a set of capabilities.** Its capacity and health are **derived** from its
members' `execution_budget` rows and never stored. D3 already treats global capacity as "a derived
figure for reporting, never a number anyone claims against"
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:154-156`), and pool capacity is
the same sum over a smaller set.

### Storage

A new `executor_pools` table, referenced by `execution_budget.pool_id`. It goes in
`packages/syn-adapters/src/syn_adapters/execution_runs/schema.sql` after `:23`, and keeps that
file's "idempotent, runs at every startup" rule (`schema.sql:1`).

```sql
CREATE TABLE IF NOT EXISTS executor_pools (
    pool_id TEXT PRIMARY KEY,
    priority SMALLINT NOT NULL CHECK (priority >= 0),        -- 0 is tried first
    provider TEXT NOT NULL,                                  -- 'docker' today
    region TEXT,                                             -- NULL: no region stated
    isolation SMALLINT NOT NULL DEFAULT 10,                  -- IsolationLevel, section 3
    capabilities TEXT[] NOT NULL DEFAULT '{}',
    overflow_delay_s INTEGER NOT NULL DEFAULT 60 CHECK (overflow_delay_s >= 0),
    defined_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO executor_pools (pool_id, priority, provider)
    VALUES ('default', 0, 'docker') ON CONFLICT DO NOTHING;
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS pool_id TEXT NOT NULL
    DEFAULT 'default' REFERENCES executor_pools (pool_id);
ALTER TABLE execution_budget DROP COLUMN IF EXISTS backend;  -- replaced by executor_pools.provider
```

**Why drop `backend`.**

- Nothing reads or writes it (see the table above).
- Keeping it beside `executor_pools.provider` would leave two places that must agree, with nothing
  enforcing it.
- During a generation overlap, the older code re-runs its own `schema.sql`. Its
  `CREATE TABLE IF NOT EXISTS` does nothing on an existing table, and no older code names
  `backend`.

### Port values

In `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py`,
beside `ExecutorHost` (`:41`). Each is `frozen=True, extra="forbid"`.

- `ProviderId`, `RegionId`: constrained `str`, slug pattern `^[a-z][a-z0-9-]{0,62}$`. They are not
  enums: region and account values are operator data, so they must not grow enum members (review
  B3).
- `Capability(StrEnum)`: v1 has `NESTED_DOCKER = "nested_docker"`. A capability is a feature the
  platform code must understand, so an enum is correct here.
- `IsolationLevel(IntEnum)`: `CONTAINER = 10` (shared kernel, runc) and `MICROVM = 30` (own kernel:
  Kata, Firecracker, E2B). The values are spaced so a level such as gVisor can be inserted between
  them without renumbering. The ordering is a human decision (§D8).
- `ExecutorPool(pool_id, priority >= 0, provider: ProviderId, region: RegionId | None, isolation:
  IsolationLevel, capabilities: frozenset[Capability], overflow_delay: timedelta >= 0)`.
- `ExecutorHost` gains `pool: ExecutorPool`. `register(host, capacity)` keeps its signature
  (`ExecutionRunQueuePort.py:102`).
- `PoolDefinitionConflict(RuntimeError)`.

### How an executor joins a pool

`register` does this in the transaction it already has
(`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:52-68`):

1. `INSERT ... ON CONFLICT (pool_id) DO NOTHING` the declared definition.
2. Re-read the row `FOR UPDATE`.
3. If the row differs from the declaration:
   - If every **other** member is draining or gone, overwrite the row. This is how a
     single-member pool is redefined: change the setting and restart. Members are found by joining
     `executor_hosts` to `execution_budget.pool_id`, after the same-container delete at `:55-59`.
   - Otherwise raise `PoolDefinitionConflict` naming both definitions. The transaction rolls back
     and the executor refuses to start.
4. `_register_budget` (`postgres.py:307-313`) writes `pool_id`.

A restart in the same container that changes pool still moves the machine's free capacity to the
successor row (`postgres.py:301-320`). Capacity belongs to the machine; the pool belongs to the new
row.

### Where each field comes from

| Field | Source | Why |
|---|---|---|
| `provider` | the backend adapter (§4) | the declared provider cannot disagree with what runs workspaces |
| `isolation` | the backend adapter (§4) | same reason |
| `region` | setting | an operator fact nothing can derive |
| `capabilities` | setting | e.g. nested Docker depends on host configuration |

The settings are in a new `ExecutorPoolSettings` in
`packages/syn-shared/src/syn_shared/settings/execution.py`, prefix `SYN_EXECUTOR_POOL_`:

| Setting | Default |
|---|---|
| `id` | `default` |
| `priority` | `0` |
| `region` | unset |
| `capabilities` | empty |
| `overflow_delay_s` | `60` |

`.env.example` is regenerated per ADR-004. `apps/syn-api/src/syn_api/services/execution_host_runner.py:83-88`
builds the pool into the `ExecutorHost`.

**Remote pools fit this model whichever topology is chosen** (§D5). A provider-account pool (E2B)
is one executor process driving that account, with the account's concurrency as its capacity. A
Kata box is one executor per box. Both are "an executor registers into a pool".

---

## 2. Claim semantics: priority, overflow, queue

`claim(host_id)` keeps its signature (`ExecutionRunQueuePort.py:134`). All placement happens inside
it, so no caller learns that pools exist.

### Two new signals on each executor's own row

Both are written only on rows the writer already locks, so neither adds cross-executor contention.

**`execution_budget.claim_checked_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity'`**

- Stamped by the claim statement itself, in the same statement that checks the executor's own
  room, drain and heartbeat after the lock. It is stamped whether or not a run is then found, and
  whether or not the executor has room.
- It says "this executor's claim ran to the point of deciding, recently".
- A turn whose `sweep_opening`, reconciler or `claim` raises never stamps it, because
  `packages/syn-adapters/src/syn_adapters/execution_host/host.py:116-122` runs them in order and a
  raising `claim` rolls back its own stamp.
- This is the durable "willing and able to claim" signal review B1 asks for. It is distinct from
  the heartbeat, which keeps its D4 meaning ("the loop turned") and its role as the executor's own
  claim prerequisite (`postgres.py:132`).

**`execution_budget.full_since TIMESTAMPTZ`**

- NULL while `in_use < capacity`. Otherwise it is the moment the row became full.
- A `BEFORE INSERT OR UPDATE` trigger maintains it:
  `NEW.full_since := CASE WHEN NEW.in_use < NEW.capacity THEN NULL ELSE COALESCE(OLD.full_since, clock_timestamp()) END`.
- Why a trigger and not application code: an older generation's claim and release, which know
  nothing of the column, still keep it right during a rolling deploy. The capacity transfers in
  `_register_budget` and `_release` are covered by the same rule.
- Precedent: `packages/syn-adapters/src/syn_adapters/projection_stores/migrations/005_agent_event_day_rollup.sql:126-151`.
- It is created only when absent (a `DO` block checking `pg_trigger`), so startup takes no table
  lock when it already exists.

### Local drain is published

`ExecutionHost.drain()` sets only an in-process flag today
(`packages/syn-adapters/src/syn_adapters/execution_host/host.py:82-84`).

- PR 3 adds the port method `drain(host_id)`: `UPDATE executor_hosts SET draining=TRUE`. This is
  the write ADR-072's `PUT /executors/{host_id}/drain` needs anyway
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:577-578`).
- `_turn` calls it while `self._draining` is set, before the heartbeat.
- Even if it fails, a draining loop never calls `claim` (`host.py:120`). Its `claim_checked_at`
  therefore goes stale within the stale window, and it stops holding runs back regardless.

### The rule

Executor E, in pool P, may claim admitted run *r* only when all of these hold:

1. **E has room.** Unchanged: lock E's own row, then check `in_use < capacity`, `NOT draining` and
   a fresh heartbeat.
2. **P satisfies *r*.** `retry_at <= clock_timestamp()`, `writer_epoch <= E.epoch`, and
   `SATISFIES(P, r)` (§3).
3. **No higher executor holds *r* back.** A higher executor X holds *r* back when all of these are
   true:
   - X is in a pool with `priority < P.priority`;
   - X can take *r* (`X.epoch >= r.writer_epoch` and `SATISFIES(X.pool, r)`);
   - X is live (fresh heartbeat, not draining);
   - and **either**:
     - (a) X is **claiming with room**: `X.in_use < X.capacity` and a fresh `claim_checked_at`; or
     - (b) X is **recently full**: `X.full_since > clock_timestamp() - P.overflow_delay`.

Consequences of the rule:

- A higher pool that is full for **longer than** the claiming pool's overflow delay stops holding
  runs back.
- So does one that is stale, draining or not claiming. "Not claiming" means its claim has not run
  successfully within the stale window (90 s, `postgres.py:37`).
- **Order** is unchanged: `ORDER BY admitted_at, execution_id`, oldest first, in every pool.
- `overflowed` is recorded as `EXISTS` some live higher executor that could take *r*. That
  distinguishes "spilled past a higher pool" from "nothing higher could take it".

### Sketch

This replaces the room check and candidate CTE at `postgres.py:128-160`. The own-row lock at
`:125-127` stays.

```sql
-- after: SELECT 1 FROM execution_budget WHERE executor_id=$1 FOR UPDATE
UPDATE execution_budget b SET claim_checked_at=clock_timestamp()
FROM executor_hosts h
WHERE b.executor_id=$1 AND h.host_id=b.executor_id AND NOT h.draining
  AND b.heartbeat_at>clock_timestamp()-$stale
RETURNING h.epoch, b.in_use<b.capacity AS has_room;
-- no row, or has_room false: return None (the stamp commits)

WITH me AS (
  SELECT h.epoch, p.* FROM execution_budget b
  JOIN executor_hosts h ON h.host_id=b.executor_id
  JOIN executor_pools p ON p.pool_id=b.pool_id WHERE b.executor_id=$1
), higher AS (                                            -- read, never locked
  SELECT h.epoch, p.provider, p.region, p.isolation, p.capabilities,
    (b.in_use<b.capacity AND b.claim_checked_at>clock_timestamp()-$stale) AS claiming_with_room,
    COALESCE(b.full_since>clock_timestamp()-me.overflow_delay_s*interval '1 second', FALSE)
      AS recently_full
  FROM execution_budget b JOIN executor_hosts h ON h.host_id=b.executor_id
  JOIN executor_pools p ON p.pool_id=b.pool_id, me
  WHERE p.priority<me.priority AND NOT h.draining
    AND b.heartbeat_at>clock_timestamp()-$stale
), candidate AS (
  SELECT r.execution_id,
         EXISTS (SELECT 1 FROM higher x WHERE {CAN_TAKE x r}) AS overflowed
  FROM execution_runs r, me
  WHERE r.state='admitted' AND r.retry_at<=clock_timestamp() AND r.writer_epoch<=me.epoch
    AND {SATISFIES me r}
    AND NOT EXISTS (SELECT 1 FROM higher x WHERE {CAN_TAKE x r}
                    AND (x.claiming_with_room OR x.recently_full))
  ORDER BY r.admitted_at, r.execution_id FOR UPDATE OF r SKIP LOCKED LIMIT 1
) UPDATE execution_runs r SET state='claimed', ..., placed_pool=me.pool_id,
    overflowed=c.overflowed, claimed_at=clock_timestamp() ...
-- then, unchanged: UPDATE execution_budget SET in_use=in_use+1 WHERE executor_id=$1
```

`{SATISFIES p r}` and `{CAN_TAKE x r}` (= `x.epoch>=r.writer_epoch AND {SATISFIES x r}`) are
**single Python constants** in `postgres.py`. They are reused by the placement report (§5). The
memory double (`packages/syn-adapters/src/syn_adapters/execution_runs/memory.py:133-162`,
`_has_room` at `:264`) gets one function of the same meaning. One shared scenario table, run
against both adapters, keeps the two in agreement.

### Why other executors' rows are read without a lock

- Capacity safety comes only from E's own locked row, so it holds however stale the read of X is.
- Locking X's rows would bring back the cross-executor contention D3 rules out
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:177-179`) and need a global
  lock order.
- The cost is that **preference is decided on a snapshot**. While a release on a full higher
  executor is in flight, *several* lower executors can each see "full for longer than the delay"
  and each spill a distinct run. The bound is the lower executors' free capacity and the length of
  the race, **not one run** (review I1). A spill only happens after the higher pool has been full
  for the whole delay, so the window opens rarely.

### The brief's requirements, answered

- **Thundering herd.** Lower executors claim only when the predicate passes. `SKIP LOCKED` gives
  each a distinct run, and each stops at its own capacity.
- **Starvation.**
  - A run waits only while some higher executor that could take it is either (a) claiming with room
    or (b) recently full.
  - Under (a), that executor's claim ran within the stale window and takes the oldest eligible run
    every turn, so it reaches *r*.
  - Under (b), the hold ends after the delay.
  - An executor whose turn fails every time (`host.py:117-122`) stops stamping `claim_checked_at`.
    So does one that drains locally. Each stops holding runs back within the stale window.
  - No progress path depends on an alert.
- **Full or unhealthy for longer than a grace period.**
  - Full: `full_since` against the **claiming** pool's `overflow_delay`.
  - Unhealthy: the stale window on heartbeat or `claim_checked_at`, or draining.
  - This is the brief's literal semantics. The cheaper run-age alternative is offered as §D3.
- **Claim/defer loops.** None. An ineligible run never matches the candidate CTE, so it is never
  claimed or deferred, and its `lease_token` never moves. `defer` keeps its one D7 purpose.
- **Queue.** A run no executor may take stays `admitted`, which is D11's `queued`.

### New run columns (Lane 2)

`placed_pool TEXT`, `overflowed BOOLEAN`, `claimed_at TIMESTAMPTZ`.

- These are infrastructure facts kept on the row, never events, and never read by an aggregate.
- They are written at claim and kept after release. The `executor_id` CHECK at `schema.sql:40-41`
  does not cover them.
- A later re-claim overwrites them.

---

## 3. Requirements matching (the future router)

The review (B3) was right that capabilities-only containment does not model provider, region or
isolation. The contract is now typed for all four dimensions.

### Values (port module)

```python
class RunRequirements(BaseModel):          # frozen, extra="forbid"
    providers: frozenset[ProviderId] | None = None   # None: any provider
    regions: frozenset[RegionId] | None = None       # None: any region, including none
    min_isolation: IsolationLevel = IsolationLevel.CONTAINER
    capabilities: frozenset[Capability] = frozenset()

    @classmethod
    def combine(cls, per_phase: Iterable[RunRequirements]) -> RunRequirements: ...
    def satisfied_by(self, pool: ExecutorPool) -> bool: ...
class UnsatisfiableRequirements(ValueError): ...
```

### Matching

`satisfied_by` and SQL `{SATISFIES p r}` are true when all of these hold:

- the provider matches: `r.req_providers IS NULL OR p.provider = ANY(r.req_providers)`;
- the region matches: `r.req_regions IS NULL OR p.region = ANY(r.req_regions)`. A pool with no
  region never satisfies a stated region;
- isolation is strong enough: `p.isolation >= r.req_isolation`;
- capabilities are covered: `p.capabilities @> r.requires`.

### Conflicting phase requirements

Placement is per execution, because one execution runs every phase on the executor that claimed
it. `combine` therefore takes:

- the **intersection** of `providers` and of `regions` (`None` is the universe);
- the **maximum** isolation;
- the **union** of capabilities.

Three outcomes are kept apart:

| Outcome | Meaning | What happens |
|---|---|---|
| **Unsatisfiable** | an empty provider or region intersection: no pool can ever take it | `combine` raises `UnsatisfiableRequirements` at admission, before `reserve`. The start is refused with a typed error and never queued |
| **Unplaceable** | satisfiable, but no *registered* pool satisfies it now | stays `admitted`, counted as `unplaceable` (§5). A pool registered later can take it |
| **Waiting** | a compatible pool exists but is full or held back | stays `admitted`, counted as waiting |

### Storage and producer

- Storage is on `execution_runs`: `req_providers TEXT[]`, `req_regions TEXT[]` (NULL = any),
  `req_isolation SMALLINT NOT NULL DEFAULT 10` and `requires TEXT[] NOT NULL DEFAULT '{}'`.
- `reserve(..., requirements: RunRequirements = RunRequirements())` validates through the Pydantic
  model, so an unknown capability or a malformed region is rejected **at write** (review I4).
- **v1 is priority-only.** The one producer, `reserve_run`
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/run_reservation.py:28-45`),
  passes the default, which every pool satisfies.

### What a later router changes (corrected promise)

The earlier plan said the router is "a producer only" and changes only `run_reservation.py`. That
was wrong: `reserve_run` does not receive phases (`run_reservation.py:28-30`). The router PR will
change:

1. a requirements source on the phase or workflow definition (§D4). `PhaseYamlDefinition` is
   `extra="forbid"`, so this is a schema change;
2. `WorkflowExecutionProcessor`, which computes `RunRequirements.combine(...)` from the pinned
   phases before `open_start`
   (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:465-467`);
3. `open_start` / `reserve_run`, which gain a `requirements` parameter;
4. the start routes, which map `UnsatisfiableRequirements` to a typed 422.

For these four dimensions the claim does not change. A **new kind** of dimension (a cost ceiling, a
data-residency tier) would be a schema and predicate change, and the plan does not claim otherwise.

The harness `agent.provider` (`claude`/`codex`) and `sandbox`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:259`,
`:271`) are **not** placement requirements. They name the harness and its authority, not where the
run executes (the harness-vs-domain boundary in CLAUDE.md).

---

## 4. Capacity truth

### Reservations stay per executor

There is no pool counter. A pool's `in_use` and `capacity` are sums computed at read time. The
three releases (`defer`, `close`, `close_interrupted`, `postgres.py:181-194`, `:246-247`,
`:333-382`) are unchanged, so the existing tests still prove "released exactly once".

### One backend port, two uses: reach and release

`DeadHostReaper` (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:25-34`) becomes
`RunReaper`:

```python
class RunReaper(Protocol):
    def scope(self) -> str: ...            # what this backend can reach; derived, never configured
    def provider(self) -> ProviderId: ...
    def isolation(self) -> IsolationLevel: ...
    async def reap(self, executor_id: str, execution_id: str) -> bool:
        """Remove every resource labelled with this owner and execution; True only when a
        listing shows none left."""
```

**Contract for every implementation.** Every resource a backend creates carries
`syn.host_id`/`syn.execution_id` (or the provider's tag equivalent) *at creation*. `reap` finds
resources by those labels, never by a handle returned from a create call. So a create whose
response was lost is still found.

`DockerDeadHostReaper` (`apps/syn-api/src/syn_api/services/dead_host_reaper.py:33-51`) already
satisfies `reap`. It gains:

- `scope()` = the `docker info` engine `ID`, read at startup; it raises if the ID is empty;
- `provider()` = `docker`;
- `isolation()` = `CONTAINER`.

### Reach: reconciliation stays inside the reaper's scope

- `execution_budget.reap_scope TEXT` is written at register from `reaper.scope()`. The budget row
  outlives the dead claimer's `executor_hosts` row
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:229-231`), so a reconciler can
  read it.
- The fence UPDATE (`postgres.py:199-203`) and the takeover UPDATE (`postgres.py:216-220`) gain
  `claimer.reap_scope = reconciler.reap_scope`, joined through `execution_budget`.
- A run whose scope has no live executor stays `claimed` (expired) or `fencing`, **charged**. That
  is the existing D5 alert case
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:385-388`).

**Upgrade rule for rows that predate the scope column (review I3).**

- Existing rows get `reap_scope = NULL`. SQL equality with NULL is never true, so a NULL-scope run
  is never fenced by anyone. That is safe but stranding.
- **Backfill rule.** In `register`, a new executor sets `reap_scope` on NULL-scope rows **with its
  own `container_id`** (the D5 Restart predecessors `_register_budget` already locks,
  `postgres.py:295-300`). One container runs on one Docker daemon, so the same container proves the
  same scope.
- Rows with no same-container successor stay NULL and charged. They raise the D5 alert, and the
  runbook step is an operator-verified manual `UPDATE`.
- The scope is never inferred from the pool name.
- With `run_queue_enabled` off by default (`execution.py:95-96`), most installs have no rows at
  all.

### Release: no slot is freed until the backend shows the resources gone (review B2)

The earlier plan said uncertain remote outcomes needed "no new mechanism". That was wrong on the
normal completion path:

1. `run_claimed` → `_drain`
   (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:503`).
2. `_drain` catches `Exception` and returns `_fail_execution(...)` (`WorkflowExecutionProcessor.py:574-594`).
3. Any normal return reaches `queue.close`, which frees the slot (`host.py:139`, `:153-154`).
4. Only an escaping exception takes the leave-charged branch (`host.py:144-148`).

So a provider error turned into a workflow failure would free a slot over a sandbox that may
still exist.

**Fix: the host gates `close` on `reap`.** `ExecutionHost._drive`, after the drain returns and
before `close`:

```python
if not await self._released(claimed):   # reap(self.host_id, execution_id); an exception counts as False
    logger.warning("Run %s: resources not shown gone; leaving it charged for reconciliation", ...)
    return                              # lease keeper is already cancelled, so the lease expires
```

What happens next is the existing D5 path, unchanged:

1. The lease expires.
2. A same-scope reconciler fences the run.
3. `reap` must succeed before `mark_reaped`.
4. The interrupter is a no-op on the already-terminal aggregate
   (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:37-42`).
5. `close_interrupted` frees the slot.

The row ends `interrupted` with `reason` "resources not shown released". The aggregate's own
terminal outcome is untouched.

Properties of the fix:

- It does not depend on which processor exceptions escape. Provider adapters need to know nothing
  about the processor.
- On Docker today, the processor already tears down its workspaces (`_drain`'s `finally`,
  `WorkflowExecutionProcessor.py:611-618`). So `reap` normally finds nothing and returns True. The
  cost is the label-filtered `docker rm` calls per run end.
- **Acceptance gate for any remote provider PR:** pass the lost-create and uncertain-delete exit
  tests in PR 2 against that provider's `RunReaper`.

---

## 5. Observability and API

### Port

Replace `in_use() -> RunCounts` (`ExecutionRunQueuePort.py:177`; no production consumer) with
`placement(overflow_window: timedelta) -> PlacementSnapshot`. It is one read transaction, and every
figure is a sum over existing rows. It keeps `RunCounts` and adds:

- `pools: tuple[PoolPlacement, ...]`, each with:
  - `pool_id, priority, provider, region, isolation, capabilities`;
  - `capacity, in_use, live_capacity` (live, non-draining, claiming members only);
  - `live_executors, draining_executors, not_claiming_executors` (fresh heartbeat but stale
    `claim_checked_at`; this makes B1 visible);
  - `full_since` (minimum over members, when all are full).
- `queue: QueueDepth`, with:
  - `admitted`;
  - `unplaceable`, the admitted runs no registered pool satisfies, computed with `{SATISFIES}`;
  - `waiting = admitted - unplaceable`;
  - `oldest_admitted_at`.
- `overflow: tuple[OverflowCount, ...]`: per `placed_pool`, the count of `overflowed` claims in the
  window.

### Lane 2 signal

`ClaimedRun` gains `pool_id` and `overflowed`. It already round-trips through `jsonb_build_object`
(`postgres.py:148-150`) and is `extra="forbid"` (`ExecutionRunQueuePort.py:52-59`), so both sides
change together.

`ExecutionHost._spawn` (`host.py:129`) logs a line when `overflowed`. The durable record is the
run-row columns. The repo has no metrics library, and adding one is out of scope.

### API

`GET /api/v1/executors/placement` → `ExecutorPlacementResponse`.

- Models go in `apps/syn-api/src/syn_api/types.py`; the route in a new
  `apps/syn-api/src/syn_api/routes/executors.py`.
- With the run queue off it returns a typed 503.
- Then `just codegen`, and `syn executor pools` in `apps/syn-cli-node` through the typed client.

### Dashboard budget

When `run_queue_enabled`, `ExecutionBudgetInfo`
(`apps/syn-api/src/syn_api/routes/executions/models.py:551`, built at
`apps/syn-api/src/syn_api/routes/executions/queries.py:827`) is filled from `placement()`:

- `running` = claimed;
- `queued` = admitted;
- `limit` = live capacity.

With the queue off it is unchanged.

---

## 6. ADR-072 amendment, in place

The target is `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md`. It is not
`docs/adrs/ADR-072-workspace-platform-access.md`, which is a different ADR. Draft text:

> **Header, `:5`**: append "#1734 also carries pools, priority and overflow (D13, amended 2026-10-14)".
>
> **D2, the table list**: "Four tables: `execution_runs`, `execution_budget` (one row per executor: its pool, capacity, slots in use, heartbeat, last claim check, full-since and reap scope; D3, D13), `executor_pools` (one row per Executor Pool: priority, provider, region, isolation, capabilities and overflow delay; D13) and `executor_hosts`."
>
> **D3, first paragraph (`:152-153`)**: replace "`backend` (`local` today)" with "`pool_id` (D13)". Add: "A row's provider is its pool's. The per-row `backend` column this section first named was never written and is dropped."
>
> **D3, claim step 1 (`:166-169`)**, matching the code: "Lock the executor's **own** row unconditionally. Then, in one statement that sees whatever the lock wait let commit, stamp `claim_checked_at` and read `in_use < capacity`, `NOT draining` and `heartbeat_at > clock_timestamp() - <stale>`. `now()` is the transaction's start and would judge liveness before the wait."
>
> **D3, claim step 2 (`:170-172`)**: "Take the oldest `admitted` row this executor's pool may take now (D13): `ORDER BY admitted_at, execution_id FOR UPDATE SKIP LOCKED LIMIT 1`."
>
> **D3, after "never contend on one budget lock" (`:178`)**: "Placement (D13) reads other executors' rows without locking them. Preference is therefore decided on a snapshot: while a higher executor's release is in flight, several lower executors may each spill a run. Capacity is never exceeded, because only an executor's own locked row decides it."
>
> **D3, release**: add "A claimer closes a run only once its backend shows the run's resources gone (D13). Otherwise it leaves the run charged for reconciliation."
>
> **D4, heartbeat uses (`:257-260`)**: add "whether an executor counts as live for placement (D13)". Add a paragraph: "**Claim check.** The claim statement stamps `claim_checked_at` on the executor's own row each time it decides. A heartbeat says the loop turned; a claim check says the claim ran. Placement trusts only the second to advertise room, so a loop whose claim keeps failing stops holding work back."
>
> **D5, fencing table (`:274-275`)**: add to both guards "and the claimer's `reap_scope` equals the reconciler's". After `:388`: "A reconciler can reap only what its backend reaches: a Docker reaper one daemon, a provider reaper one account. `execution_budget.reap_scope` records that reach. It is derived from the backend and never configured. A run whose scope has no live executor stays charged and raises this alert. Rows from before the column are given a scope only by a successor in the same container."
>
> **New D13. Executor pools, priority and overflow**
>
> An **Executor Pool** is a named group of executors sharing a priority (0 first), a provider, a region, an isolation level and capabilities, held in one `executor_pools` row. Every `execution_budget` row names its pool. Pool capacity and usage are sums over members: reported, never claimed against (D3). A member's declaration that differs from the row is refused while any other member is live and not draining.
>
> An executor claims run *r* only when its pool satisfies *r*'s **Run Requirements** (allowed providers, allowed regions, minimum isolation, required capabilities), the epoch rule (D9) and `retry_at` hold, and no live executor in a higher-priority pool that could take *r* is either claiming with room or full for less than the claiming pool's **Overflow Delay**. Order is oldest first everywhere. An ineligible run is never claimed, so placement never claims and defers. A run no executor may take stays `admitted` (D11 `queued`). Requirements whose phases conflict (an empty provider or region intersection) are refused at admission and never queued.
>
> Placement is recorded on the run row (`placed_pool`, `overflowed`, `claimed_at`) as infrastructure telemetry, never as an event. In this revision every run's requirements are empty, so placement is by priority alone.
>
> Rejected: a pool-level counter (a second accounting surface and a hot row); locking higher executors' rows (cross-executor contention, which D3 rules out); a central router process (a singleton beside a claim transaction that already decides placement); and claim-then-defer (churns tokens and penalises the run).
>
> **Consequences, Negative**: add "Overflow preference is approximate under concurrent release. Capacity is exact."

### Vocabulary

In `docs/architecture/orchestration-ubiquitous-language.md`, after **Executor** (`:642`):

- **New entries:** Executor Pool, Pool Priority, Overflow, Overflow Delay, Claim Check, Capability,
  Isolation Level, Run Requirements, Unplaceable, Placement, Reap Scope.
- **Amended:** Execution Budget (`:558`), which still says "one API process"; add the pool sum.
  Drain (of an executor) (`:751`): local drain is now published.
- **Under "Words we do not use" (`:1111`):**
  - **Tier**: we say priority.
  - **Router**: reserved for requirement derivation, not a process.
- Bare "pool" is **not** banned (review I5). The entry for Executor Pool says it is always written
  in full, because asyncpg connection pools share the short word in infrastructure code, e.g. the
  `pools` fixture (`packages/syn-adapters/tests/test_execution_run_queue_postgres.py:33`), which
  stays as it is.

---

## 7. Ordered PRs with exit tests

### Where the tests run

- Every claim-semantics test runs on **real Postgres** in
  `packages/syn-adapters/tests/test_execution_run_queue_postgres.py`, with the existing `pools`
  fixture (`:32-55`).
- Host-loop tests use real Postgres with `ExecutionHost` and doubles for the drainer and reaper.
- A new `packages/syn-adapters/tests/execution_run_queue_scenarios.py` holds the placement scenario
  table. The Postgres and memory adapter test files both import it.

### PR table

| PR | Content | Depends on |
|---|---|---|
| **0** | This plan as `docs/plans/20261014_pool-priority-placement.md`, the ADR-072 amendment and the vocabulary. Docs only | owner approval (§D1-D3) |
| **1** | Pool model: `executor_pools`, `execution_budget.pool_id`, drop `backend`, port values, `register` conflict rule, `ExecutorPoolSettings`, runner wiring, double, conformance (`packages/syn-adapters/src/syn_adapters/port_conformance.py:467-472`). Fix the stale `run_queue_enabled` description (`execution.py:99-101`). Claim unchanged | 0 |
| **2** | Reach and release: `RunReaper` (scope, provider, isolation, `reap(executor_id, execution_id)`), `reap_scope` plus the same-container backfill, scope-guarded fence and takeover, and the host's reap-before-close gate | 1 |
| **3** | Claim signals: `claim_checked_at` stamped in claim, the `full_since` trigger, port `drain(host_id)` published from `ExecutionHost.drain()`. Placement unchanged | 1 |
| **4** | Priority and overflow in `claim` (both adapters), `placed_pool/overflowed/claimed_at`, `ClaimedRun.pool_id/overflowed`, the overflow log | 2, 3 |
| **5** | `RunRequirements` columns, `{SATISFIES}` in the claim, `reserve(requirements=)` with write-time validation, `combine` and `UnsatisfiableRequirements`. Producer stays default | 4 |
| **6** | `placement()`, `GET /api/v1/executors/placement`, `just codegen`, `syn executor pools`, `ExecutionBudgetInfo` from placement when the queue is on | 4 (5 for `unplaceable`) |

### Exit tests

Each test is named for what it asserts. "Reverted" names what the test sees if the change is
undone.

**PR 1**

- `test_a_second_member_declaring_a_different_pool_definition_is_refused_and_writes_nothing`
  - Asserts: `PoolDefinitionConflict`; no host or budget row for B; the pool row is unchanged.
- `test_a_sole_member_restarting_in_its_container_may_redefine_its_pool`
- `test_a_member_may_redefine_its_pool_once_every_other_member_is_draining`
- `test_upgrading_a_pre_pool_schema_keeps_rows_assigns_default_and_drops_backend`
  - Setup: apply a frozen copy of today's `schema.sql`, insert a claimed run, then apply the new
    file twice.
  - Asserts: `pool_id='default'`; no `backend` column; `close` frees exactly one slot.
- `test_a_restart_that_changes_pool_moves_the_machines_free_capacity_to_the_new_row`
- All existing tests pass unmodified.

**PR 2**

- `test_an_executor_in_another_reap_scope_never_fences_an_expired_run`
  - Setup: A (scope `s1`) claims and expires; B (`s2`) runs `fence_expired`, then C (`s1`).
  - Asserts: B gets `[]` and the row is still `claimed`; C fences it.
  - Reverted: B fences.
- `test_takeover_requires_the_same_reap_scope`
- `test_a_run_with_no_live_executor_in_its_scope_stays_charged`
  - Asserts: `in_use` is unchanged after a full reconciliation turn by an other-scope host.
- `test_a_pre_scope_expired_claim_is_scoped_only_by_a_successor_in_its_own_container` (review I3)
  - Setup: old schema, a claimed run on a row with NULL scope, expired. Executor D, in another
    container, registers and reconciles.
  - Asserts: the row stays charged. Then E, in the dead row's container, registers.
  - Asserts: the row has E's scope, and E fences and reaps it.
- `test_a_drain_that_returns_normally_over_unreleased_resources_leaves_the_slot_charged` (review
  B2; host loop, real Postgres)
  - Setup: a drainer double returns a failure result, simulating `_fail_execution` after a provider
    create whose response was lost. The reaper double returns False.
  - Asserts: the row is `claimed`, `in_use=1`, and no `close`. After lease expiry a same-scope
    reconciler fences it; while `reap` is False it stays `fencing`, charged. When `reap` flips True
    the run goes to `interrupted` and `in_use=0`.
  - Reverted (host closes without the gate): `in_use=0` immediately.
- `test_uncertain_delete_keeps_the_slot_until_reap_confirms`: the same shape, with `reap` raising
  on the first two calls.
- `test_a_completed_docker_run_is_shown_released_and_closes` (real Docker, beside
  `apps/syn-api/tests/integration/test_1310_v7_dead_host_reap_on_real_docker.py`)
  - Asserts: a normal run closes with no fencing. This proves the gate does not reroute healthy
    Docker runs.
- Unit: `DockerDeadHostReaper.scope()` returns the engine ID from a stubbed `docker info` and raises
  when it is empty.

**PR 3**

- `test_claim_stamps_claim_checked_at_with_and_without_a_run_and_when_full`
- `test_a_raising_claim_leaves_claim_checked_at_unstamped`
- `test_full_since_tracks_claim_release_and_capacity_transfer_including_old_code_writes`
  - Setup: raw `UPDATE in_use` statements in the old code's shape.
- `test_local_drain_is_published_to_executor_hosts` (host loop)

**PR 4** (both adapters, from the scenario table; ages are set by direct UPDATE, as the existing
staleness tests do)

- `test_a_lower_pool_never_claims_while_a_higher_executor_is_claiming_with_room`
  - Setup: P0 with room and a fresh `claim_checked_at`. Two P1 executors issue 40 concurrent claims.
  - Asserts: zero claims.
  - Reverted (no priority filter): P1 claims. This is deterministic, because P0's room cannot
    change while P0 does not claim.
- `test_a_lower_pool_overflows_only_after_the_higher_pool_has_been_full_for_its_delay`
  - Asserts: `full_since` = now gives None; aged past the delay, P1 claims with `overflowed=true`
    and `placed_pool='p1'`.
- `test_a_stale_draining_or_not_claiming_higher_executor_is_overflowed_past_at_once`
  - Three cases: a stale heartbeat; draining; a fresh heartbeat with a stale `claim_checked_at`.
- `test_a_higher_executor_whose_turn_fails_every_time_does_not_starve_the_queue` (review B1; host
  loop, real Postgres, short stale window)
  - Setup: P0's queue wrapper makes `claim` raise (a second case makes `sweep_opening` raise) while
    its heartbeat succeeds every turn.
  - Asserts: P1's host claims the run within stale + one loop interval.
  - Reverted (room advertised by heartbeat): P1 never claims.
- `test_a_locally_drained_higher_executor_holding_a_run_lets_the_lower_pool_claim` (review B1; host
  loop)
  - Setup: P0 has capacity 2 and holds one long-lived run. `drain()` is called.
  - Asserts: P1 claims new work while P0's run is still held.
- `test_a_higher_pool_that_cannot_read_the_runs_epoch_does_not_hold_it_back` (`overflowed=false`)
- `test_oldest_first_holds_across_pools`
- `test_an_ineligible_run_is_never_claimed_so_its_token_never_moves`
- `test_concurrent_claims_across_two_priorities_never_exceed_any_capacity` (safety only)
  - Asserts: every `in_use <= capacity`, and claimed runs are distinct. No exact total.
- `test_repeated_claim_rounds_eventually_fill_every_executor` (progress, separate from safety)
  - Asserts: after rounds until no claim succeeds, the total equals the summed capacity.
- `test_a_release_in_flight_lets_lower_executors_spill_and_never_exceed_capacity` (review I1)
  - Setup: a blocker transaction holds P0's budget row mid-release (the `_blocked_until_waiting`
    helper, `packages/syn-adapters/tests/test_execution_run_queue_postgres.py:322-333`). Two P1
    executors claim.
  - Asserts: both may spill (the documented snapshot behaviour), and capacity holds.
- `test_equal_priority_pools_both_claim_without_delay`
- Real-process test: `apps/syn-api/tests/integration/test_1734_overflow_between_two_executor_processes.py`,
  extending `apps/syn-api/tests/integration/_1310_executor_process.py` with pool settings.
  - Setup: P0 has capacity 1; P1 has a 2 s delay.
  - Asserts: run 2 goes to P1 at least 2 s after P0 filled, with `overflowed`.

**PR 5**

- `test_incompatible_provider_region_or_isolation_stays_admitted_despite_spare_capacity`
- `test_an_incompatible_higher_pool_does_not_hold_back_a_compatible_lower_pool`
- `test_combine_intersects_providers_and_regions_takes_max_isolation_unions_capabilities`
  (unit)
- `test_conflicting_phase_requirements_are_refused_at_admission_and_never_reserved` (unit plus
  route)
- `test_reserve_rejects_an_unknown_capability_at_write_and_writes_no_row` (review I4)
- `test_a_hand_written_unknown_requirement_is_never_claimed_charges_nothing_and_counts_unplaceable`
  (review I4)
  - Asserts: every claim returns None and `in_use` is unchanged. After PR 6, `unplaceable=1`.
- Unit: `run_reservation` passes the default requirements. This pins v1 as priority-only.

**PR 6**

- `test_placement_sums_members_reports_live_capacity_and_keeps_stale_charges`
- `test_placement_counts_unplaceable_with_the_claims_own_predicate`
- `test_placement_reports_not_claiming_executors`
- API test: `ExecutorPlacementResponse` appears in `/openapi.json`. `check:api-drift` is green after
  `just codegen`.

---

## Rejected alternatives

| | Alternative | Why rejected |
|---|---|---|
| A | Put priority and capabilities on each `execution_budget` row | Members could disagree with nothing enforcing agreement, and there is no single place to change a pool |
| B | A per-pool counter locked in the claim | A second accounting surface and a hot shared lock, which contradicts D3 |
| C | Lock higher executors' rows so "full" is exact | Cross-executor contention and lock ordering, to buy only preference |
| D | Claim any run, then defer it if ineligible | Token churn and a `retry_at` penalty: the loop the branch research warns about |
| E | A central router process | A singleton with failover, re-solving what the claim already decides atomically |
| F | Measure the grace period on run age (`admitted_at`) only | The cheaper policy, but not what the brief asked. A run that waited an hour behind work spills the instant P0 fills (review I2). Offered as §D3 |
| G | Reuse `backend` as the pool key | The column is per row, so A's drift applies, and it means provider, not pool |
| H | Room advertised by the heartbeat | Starves the queue behind an executor whose claim fails every turn (review B1) |
| I | Move the heartbeat to after a clean turn | A single clean-turn failure would then make the executor's own claim refuse (`postgres.py:132`), coupling liveness and placement |
| J | A run-age starvation backstop | Not needed once room requires a claim check. It would spill to paid pools while a healthy local pool is merely busy |
| K | Free the slot on a normal drain return and rely on the provider to raise | Processor failure handling converts exceptions into returns (review B2) |

---

## Maintenance cost

- One table; on `execution_budget`: `pool_id`, `claim_checked_at`, `full_since`, `reap_scope`; on
  `execution_runs`: four requirement columns and three placement columns.
- One trigger.
- One settings class.
- The claim statement grows from one predicate to the `higher`/`candidate` CTEs, built from two
  shared predicate constants.
- One write per claim call that finds no run (the stamp). At 1,000 executors on a 5 s loop that is
  about 200 small single-row UPDATEs per second, the same order as today's heartbeat.
- One port method replaced (`in_use` → `placement`) and one added (`drain`). The reaper port is
  renamed and widened.
- One route and one CLI command.

**Where change is expected to come from, and where it lands:**

| Change | What it touches |
|---|---|
| New provider (E2B, Kata) | Its `RunReaper` adapter and a pool row. Must pass the PR 2 release tests. No claim change |
| New capability | A `Capability` member and its producer |
| Requirement derivation | The definition schema, the processor, `reserve_run`, and the start routes (§3) |
| Run priority, if decided | The `ORDER BY` in one statement, plus the double |

---

## Risks

| # | Risk | Signal / mitigation |
|---|---|---|
| R1 | Claim cost grows with queue depth and executor count. The `higher` CTE reads every budget row; when everything is held back, `LIMIT 1` scans the whole admitted range | Debug-log claim duration over 100 ms, and have the #1717 load test report it. Ready mitigations: an index on `execution_budget(pool_id)`, and bounding the `admitted_at` range when `higher` is non-empty |
| R2 | A "black hole" higher executor claims successfully but every run fails at once. It keeps winning placement | Failure rate per `placed_pool` in `placement()`. A per-pool circuit breaker (branch research, *research phase*) is a follow-up |
| R3 | The reap scope is derived wrongly (the daemon ID changes on reinstall) | Runs stuck `fencing` and charged: the D5 alert. This fails safe |
| R4 | `PoolDefinitionConflict` blocks a deploy that changes a multi-member pool | Exit message with both definitions. Drain the others first (runbook in PR 1) |
| R5 | A rolling deploy runs an old executor beside a new one | It is in `default`. It never stamps `claim_checked_at`, so it holds nothing back. `full_since` stays right through the trigger. It disappears when its generation drains |
| R6 | Snapshot preference spills several runs during a release race | Documented in D3. `overflowed` counts against expectation in the load test |
| R7 | Reap-before-close adds Docker calls per run end, and a slow daemon delays the close | PR 2 real-Docker test. A failed reap goes to reconciliation, never to an early free |
| R8 | The semantics go unexercised in production until a second executor exists | The PR 4 real-process test runs two processes on every CI run |

---

## Verification

Run on each PR from the repo root (CLAUDE.md "Verification gates"):

```
just preflight-agent
uv run pytest -m unit -q
uv run pytest packages/syn-adapters/tests/test_execution_run_queue_postgres.py packages/syn-adapters/tests/test_execution_run_queue_memory.py -q
uv run pytest apps/syn-api/tests/integration/test_1734_overflow_between_two_executor_processes.py -q   # PR 4+
just check-untyped-dicts
just codegen && git diff --exit-code apps/syn-cli-node/src/generated/api-types.ts                     # PR 6
```

- The Postgres tests need the test stack or testcontainers. Inside an agent workspace they show as
  `NOT RUN`, and CI settles them on the same head SHA.
- New modules that need no infrastructure carry the `unit` marker.
- Mutation check before review: revert the predicate line each test names, and confirm the test
  goes red.

---

## Out of scope

- Any remote provider and its `RunReaper` (agentic-workspace work, an image release, #1735). Each
  must pass the PR 2 release tests.
- The `SYN_PROCESS_ROLE=executor` service and multi-host compose (ADR-072 D1, D10 Phase 2).
- The requirements source and the router producer (§3, §D4).
- Per-run priority.
- The `PUT /executors/{host_id}/drain` and `DELETE /executors/{host_id}` routes. PR 3 adds only the
  port method they will use.
- Turning `run_queue_enabled` on by default.
- A metrics library.
- A per-pool circuit breaker (R2).

---

## Needs a human decision

- **D1. Sequencing against the north star.** Recommendation:
  - land PR 0-3 now. They are schema and safety work, done before live data exists. PR 2 closes the
    multi-host reap gap and the B2 release gap;
  - land PR 4-6 with #1734's second executor.
- **D2. Approve the ADR-072 amendment text in §6**, revised in place.
- **D3. Grace-period semantics.**
  - Recommended: **saturation duration** (`full_since`), the brief's literal "full for longer than
    a grace period".
  - Alternative: **run age** (Rejected F), which is cheaper (no trigger) but spills on the first
    millisecond of fullness for an old run.
  - The ADR text in §6 assumes saturation.
- **D4. Source of run requirements**: workflow YAML (`extra="forbid"`, so older installs reject
  it), workflow metadata, or trigger config. v1 needs none.
- **D5. Topology for the first remote pool**: a local process per provider account, or a process
  on the remote box.
- **D6. Defaults**: `overflow_delay` 60 s; claim-check staleness equal to the heartbeat's 90 s;
  priority 0 tried first; pool `default`. Is 60 s right for "spill to paid remote"?
- **D7. Run priority**: should a human-started run ever outrank an older trigger-started one?
- **D8. Isolation ordering**: `CONTAINER < MICROVM` as a minimum-level comparison, rather than
  matching against a set of profiles.
- **D9. Reap-before-close on Docker today** (PR 2). Recommended yes: one code path for every
  backend, at the cost of label-filtered `docker rm` calls per run end.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1: heartbeat-with-room starvation; local drain not published | **Accepted** | Verified at `packages/syn-adapters/src/syn_adapters/execution_host/host.py:115-127` and `:82-84`; `drain()` has no production caller (only `run_until_drained` at `apps/syn-api/src/syn_api/services/execution_host_runner.py:99`), so the drain half is latent. Added `claim_checked_at`, stamped by the claim itself, as the room signal. The heartbeat keeps its D4 meaning and its role as the executor's own claim prerequisite, as the reviewer required. Added port `drain(host_id)`, published from `ExecutionHost.drain()`. R2's "defer the fix" is removed. Two host-loop exit tests on real Postgres (failing turn; local drain holding a long run) |
| B2: uncertain provider outcome freed through the normal close | **Accepted** | Verified the chain: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:503`, `:574-594`; `packages/syn-adapters/src/syn_adapters/execution_host/host.py:139`, `:144-154`; `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:365-372`. Replaced "no new mechanism" with a host gate: `close` only after `RunReaper.reap(self, execution_id)` shows the resources gone; otherwise the run is left charged for D5 reconciliation. Providers must label resources at creation, so a lost create response is still found. The gate is independent of which processor exceptions escape. Lost-create and uncertain-delete exit tests are the acceptance gate for any provider |
| B3: requirements contract lacks provider, region and isolation; false "final shape" and "producer only" promises | **Accepted** | Typed `RunRequirements` (allowed providers, allowed regions, minimum isolation, capabilities) matched against pool `provider/region/isolation/capabilities` in the claim. Region and provider are validated slugs, not enums. `combine` defines how conflicting phases combine, and separates unsatisfiable (refused at admission), unplaceable and waiting. Withdrew "producer only": named the four later changes, since `reserve_run` takes no phases (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/run_reservation.py:28-30`) |
| I1: "off by one" bound unsupported; concurrent test not priority-sensitive and schedule-dependent | **Accepted** | ADR and plan now say snapshot-based preference, with possible concurrent spills bounded by lower executors' free capacity. Split into a safety test, a progress test, a deterministic priority test that fails with the filter removed, and a release-race test built on `packages/syn-adapters/tests/test_execution_run_queue_postgres.py:322-333` |
| I2: run age is not "full for longer than a grace period" | **Accepted, and the policy changed** | Folding the column into an existing write was not enough: an old-generation executor would not maintain it. A trigger-maintained `full_since` gives the brief's semantics, generation-safe, with precedent at `packages/syn-adapters/src/syn_adapters/projection_stores/migrations/005_agent_event_day_rollup.sql:126-151`. Run age is kept as a described alternative and the choice is human decision D3, as the reviewer asked |
| I3: no rollout rule for pre-scope rows | **Accepted** | NULL scope never matches, so it fails safe. Only a successor in the same `container_id` backfills it, because one container is on one daemon. Otherwise the row stays charged with the D5 alert and a manual runbook. Never inferred from the pool name. Old-schema migration exit test added |
| I4: the `bogus` capability test expected the wrong behaviour | **Accepted** | Unknown requirements are rejected at write by `reserve`'s Pydantic validation. A hand-written row is never claimed, charges nothing and counts as `unplaceable`. Both are tested. The claim at `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:161` validates only the returned run, as the reviewer said |
| I5a: abbreviated citations | **Accepted** | Every citation now uses a repo-root path (a bare `:line` refers to the last full path cited in the same paragraph) |
| I5b: branch documents left unverified | **Accepted in part** | The reviewer read them from the remote ref. This phase has no git or shell tool and the files are absent from the working tree, so they are marked *(research phase)*. No design decision depends on them alone |
| I5c: fixture rename and the bare-"Pool" ban are unnecessary churn | **Accepted** | The fixture rename is dropped (`packages/syn-adapters/tests/test_execution_run_queue_postgres.py:33` correctly means connection pools). "Pool" is removed from "Words we do not use"; the term is always written "Executor Pool" |
| "What should remain" (per-executor accounting, compatibility in the claim, cross-scope reap fix first) | **Agreed** | Kept unchanged. The cross-scope fix stays in PR 2, before any placement change |

No finding was rejected. Each was checked against the cited code and held.

## Readiness

Blocked on one human decision: the owner's approval of the ADR-072 amendment in §6, which includes
choosing saturation-duration over run-age as the grace-period policy (§D3). Once approved, PR 0-3
are ready to implement.

