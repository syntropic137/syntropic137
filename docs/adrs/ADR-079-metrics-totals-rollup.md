# ADR-079: Metrics Totals Rollup

- **Status**: Proposed
- **Date**: 2026-11-27
- **Issue**: #2383 (slice 1 of N: this ADR, no code)
- **Related**: ADR-026 (TimescaleDB observability storage), ADR-055 (projection
  checkpoints), ADR-060 (no in-memory adapters in production), ADR-075 (request
  latency telemetry), #897, #932, #983, #1318, #1558, #1843, #1934, #2341,
  #2361, #2382, docs/north-star.md

All file and line references are to `origin/main` at `0d17d073f`.

## Context

### What `/metrics` reads today

`GET /metrics` (`apps/syn-api/src/syn_api/routes/metrics.py:419`) runs four
global reads concurrently (`metrics.py:454-465`, #2341/#2361). One of them,
`_canonical_totals` (`metrics.py:398-416`), calls
`CanonicalUsageQueryService.totals()`
(`packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/canonical_totals/query_service.py:255-306`).
That response field set is tokens, `cost_usd`, `unpriced_observation_count`
and the cost's display string (`metrics.py:481-488`).

The issue says the totals are "computed per request instead of from a
maintained rollup". That is half right, and the half that is wrong decides the
design. **There is already a maintained Lane 2 rollup.** Since #1558 (E1) the
reader never parses `agent_events` for tokens. It reads two ordinary tables
that a trigger on `agent_events` keeps current in the same transaction as the
insert (`packages/syn-adapters/src/syn_adapters/events/schema.py:241-386`):

| Table | Grain | Defined |
|---|---|---|
| `agent_summary_usage` | one row per `session_summary` observation | `schema.py:288-304` |
| `agent_turn_usage_rollup` | `token_usage` summed per (session, execution, model columns, provenance) | `schema.py:313-340` |
| `agent_usage_rollup_state` | one row once the backfill finished with the trigger live | `schema.py:341-348` |
| `agent_event_day_rollup` | one row per (UTC day, session, execution) | `schema.py:37-104` |

What is still done per request is everything ABOVE that session grain:

1. **The canonical decision, over every session.**
   `CANONICAL_USAGE_DECISION_CTE`
   (`packages/syn-domain/src/syn_domain/contexts/agent_sessions/canonical_usage.py:108-153`)
   ranks every summary per session (`ROW_NUMBER() OVER (PARTITION BY
   session_id ...)`, `:109-135`), keeps the winner only if it carries usage
   (`:136-144`), and unions it with the turns of every session that has no
   winner (`:145-152`). The totals statement (`query_service.py:102-138`)
   groups that by (model columns, `vendor_cost_usd IS NULL`). The reader's own
   comment says this "grows with sessions, not with telemetry"
   (`query_service.py:52-53`). It does grow, though.
2. **The unpriced-turn count, from the hypertable.** When a turn model has no
   rate, the reader lists that model's summary-less sessions per UTC day
   (`query_service.py:130-137`) and then counts their non-zero turns in
   `agent_events`, one `UNION ALL` branch per day
   (`query_service.py:140-170`, `:351-403`). It has to, because "the rollup
   cannot tell a zero-token turn from any other" (`query_service.py:141`). A
   zero-token turn is a priced zero at any rate (#890), so it must not count
   (`recorded_model_rows.py:67-81`). The scale gate's seed has 2,000 unrated
   summary-less sessions spread over 90 days
   (`apps/syn-api/tests/integration/test_metrics_summary_less_sessions_at_scale.py:31-33,55,69-85`),
   so this path runs in the gate. Its cost grows with the number of days that
   have unpriced work.
3. **A session count that `/metrics` throws away.** `totals()` also runs
   `COUNT(DISTINCT session_id) FROM agent_event_day_rollup`
   (`query_service.py:198-202`, `:287`). That count grows with session-days.
   The route does not use it: `total_sessions` comes from the session list
   since #1843 (`metrics.py:333-352`). `totals()` has exactly one caller,
   `metrics.py:410-411`.

Pricing is applied at read time, per (model columns, cost-nullness) group,
through the injected `PricingResolver` (`query_service.py:235-243`,
`:319-349`; `canonical_usage.py:299-328`). Nothing stores money except the
harness's own `vendor_cost_usd`.

### The evidence

At 6,000 summary-less sessions, the median round p95 for global `/metrics` was
88.1 ms (CI run 45929953446), 103.9 ms (a failed main attempt) and 63.5 ms (a
rerun). That is the same code each time; CI runner speed varies by about 1.6x.
The budget is 100 ms global and 300 ms scoped
(`apps/syn-api/tests/integration/test_dashboard_latency_budget.py:42-43`). The
gate takes the median of 3 interleaved rounds' p95s
(`apps/syn-api/tests/integration/latency_gate.py:1-25,49-55`, #2382).

The target is a CI p95 of 50 ms or less at 6,000 sessions, **independent of
history size**. The north star is 20, then 100, then 1,000 concurrent
executions. A read that grows with history fails that eventually, however
fast it is today.

**Assumption A1.** I have no per-statement breakdown of the 88 ms. The design
removes all three history-sized reads above, so it does not depend on which of
them dominates. Slice 4 must print the breakdown before and after.

### Constraints this design must keep

- **Two lanes.** Usage is an observation (Lane 2). It is not domain truth, and
  the card moved from Lane 1 to Lane 2 so it agrees with the heatmap (#932,
  `query_service.py:1-9`).
- **One canonical decision.** Summary-supersedes-turns is decided in ONE place
  (`canonical_usage.py:105-107`). A second implementation of it would drift.
- **Pricing changes take effect at once.** Today a rate-card change reprices
  all of history on the next read, because money is computed at read time.
- **One snapshot for the totals** (#983): `totals()` runs inside
  `agent_event_span.custom_plans`, a `REPEATABLE READ READ ONLY` transaction
  (`packages/syn-domain/src/syn_domain/agent_event_span.py:159-170`,
  `query_service.py:268-271`).
- **No in-memory state** (ADR-060), and nothing that replays the event store
  (#1318).
- **The ingest path is hot.** `insert_batch` writes each batch with one COPY,
  in one transaction per batch, from many concurrent writers
  (`packages/syn-adapters/src/syn_adapters/events/store_write.py:103-150`).
  A trigger runs inside that transaction. If it errors, the whole batch fails.
  If it waits on a lock, the writer waits too.

## Decision

### D1. Lane 2. A third rollup tier above the session grain, kept by triggers on the existing rollup tables

The totals become one more Lane 2 table tier. It is maintained in the same
transaction as the rollup rows it derives from, and read in O(pricing groups).
It adds four tables, one column and two functions (the recompute, and the
session pre-lock of D1.1a):

| Object | Grain | Written by |
|---|---|---|
| `agent_turn_usage_rollup.reported_observations` (new column) | per existing turn key | the existing `agent_usage_rollup_apply` trigger and backfill: `+1` when the turn's tokens are non-zero, by the predicate `zero_usage_group_by` already uses |
| `agent_session_canonical_usage` | one row per (session, model columns, cost-nullness): **exactly that session's `canonical_usage` rows** | row triggers on `agent_summary_usage` and `agent_turn_usage_rollup` (INSERT, UPDATE, DELETE) |
| `agent_usage_totals_delta` | append-only: one row per change to a session's canonical rows, carrying the signed difference per pricing group | the same triggers |
| `agent_usage_totals` | one row per pricing group (model columns, cost-nullness) | the fold (D1.3) only |
| `agent_usage_totals_state` | singleton: backfill complete with triggers live | the backfill, like `agent_usage_rollup_state` |

**D1.1 Per-session recompute, using the one decision.** When any row of
session S changes in either rollup table, the trigger recomputes S's canonical
rows. It runs `rollup_usage_sources("session_id = S")` plus
`CANONICAL_USAGE_DECISION_CTE` (`canonical_usage.py:228-255`): the same SQL
text the reader runs today, narrowed to one session through the existing
`session_id` indexes (`schema.py:305-308,337-340`). It diffs the result
against S's stored rows in `agent_session_canonical_usage`, replaces them, and
appends the non-zero differences to `agent_usage_totals_delta`.

Each canonical row also carries two counts. A summary row carries
`summary_observations = 1`. A turn row carries the sum of
`reported_observations` over S's turn rows for that model. That gives the
unpriced-observation count without touching `agent_events` (D2).

Recomputes of one session are serialized by a per-session advisory lock. That
lock is per session, so writers of different sessions never wait on each other
through it. Where the lock is taken is what makes it safe, and D1.1a decides
that.

**D1.1a Lock order: every session lock before any rollup row lock.** Taking the
session lock inside the row trigger is NOT safe. `insert_batch` writes a whole
batch in one transaction (`store_write.py:131-139`), with no ordering by
session, day or model. The day trigger upserts one row per (day, session,
execution) (`schema.py:148-162`). The turn trigger upserts one row per model
key (`schema.py:355-381`). Both hold their row locks until the batch commits.
That admits this schedule:

1. Transaction A writes a turn for session S on day D1, model M1, and takes
   S's session lock in the trigger.
2. Transaction B writes a turn for S on day D2, model M2, takes the D2 day row
   and the M2 turn row, and then waits for S's session lock.
3. A's next turn for S is on D2, model M2. A waits for B's D2 row, and B waits
   for A. PostgreSQL aborts one of them, and that batch's telemetry is lost
   (there is no retry, `store_write.py:103-150`).

The backfill transaction is multi-session too (`schema.py:882-891`), so it can
form the same cycle with live ingest.

The rule that removes the cycle: **a transaction that will write any rollup row
of a session takes that session's lock first, and takes all of its session
locks before its first write, in ascending lock-key order.**

- **The lock key.** It is the two-argument form,
  `pg_advisory_xact_lock(USAGE_TOTALS_SESSION_LOCK_CLASS, hashtext(session_id))`.
  The class constant goes beside the other keys in
  `syn_adapters.advisory_locks`, so it cannot collide with a single-key lock.
  Two sessions with the same `hashtext` share a lock. That is coarser, but
  still one total order.
- **One SQL function takes them all.** A new plpgsql function,
  `agent_usage_lock_sessions(text[])`, computes
  `array_agg(DISTINCT hashtext(s) ORDER BY hashtext(s))` (the ORDER BY inside
  an aggregate is guaranteed, an ORDER BY on a subquery is not). It locks each
  key in that order, then records the keys in a transaction-local setting
  (`set_config('syn.usage_session_locks', ..., true)`).
- **Each writer calls it as the first statement of its transaction.**
  - `insert_batch` calls it before the COPY, with the batch's distinct session
    ids. `_build_copy_buffer` already validates every row's session
    (`store_helpers.py:85-112`), so the list comes from the same validated
    rows.
  - `insert_one` (`store_write.py:73-80`) calls it with its one session.
  - Each backfill batch calls it with the batch's sessions, after the schema
    lock it already takes (`schema.py:889`).
  - Advisory locks are re-entrant within a transaction, so taking a lock the
    transaction already holds costs nothing.
- **The trigger enforces the rule. It does not take the lock itself.** The
  recompute checks that `hashtext(S)` is in `syn.usage_session_locks`. If it
  is not, it raises `usage_session_lock_missing`. A writer added later that
  skips the pre-lock then fails loudly on its first write, in every test,
  instead of leaving a deadlock that only shows under load. A trigger that
  quietly took the lock late would bring the cycle back.

Why this is a total order:

- Every row lock on the day, turn, summary and canonical tables belongs to one
  session, because each of those keys contains `session_id`. So does the
  tool-call tally the same transaction writes
  (`packages/syn-domain/src/syn_domain/tool_call_counts.py:154,179-184`).
- A transaction holds a session's row locks only after it holds that
  session's lock.
- So two transactions can only contend on a row while one of them already
  holds the session lock, and the other is still queued on it.
- Session locks are taken in one global order (ascending key), and no
  transaction waits for one while it holds a row lock.

The wait-for graph therefore has no cycle among writers that take session
locks. What stays outside the rule:

- The schema lock comes first, and only the backfill and the DDL take it. No
  ingest transaction ever waits for it.
- The ledger is insert-only and has no unique key, so its inserts take no
  conflicting row lock.
- The totals rows are written only by the fold (D1.3), which takes no session
  lock and writes no session-keyed row. So the fold adds no edge to the
  writers' graph.
- The day-rollup reconcile (`ROLLUP_BACKFILL_SQL`, `schema.py:183-196`) takes
  no session lock and fires no canonical trigger, so it adds no new edge
  either. Its row-lock order against ingest is today's, and this ADR does not
  change it.

**Retry is not part of the mechanism.** Ordering makes the deadlock
impossible, so `insert_batch` stays without retry. Adding one would hide an
ordering bug. A `40P01` from an ingest transaction after this lands is a
defect, and it is reported as today's failed batch is.

**Assumption A2.** This is per-row trigger work inside COPY, and a batch of N
events for one session recomputes that session N times. I expect each
recompute to be a handful of index reads. Slice 3b must measure ingest
throughput before and after. If it regresses, the first optimisation is
already obvious: a turn change on a session with no winning summary is purely
additive and needs no recompute. That is an optimisation, though, and the
recompute is the specification.

**D1.2 Why triggers on the rollup tables and not on `agent_events`.** The
rollup tables are written by two paths: the trigger and the non-blocking
backfill (`schema.py:263-287`, `:402-460`). The backfill DELETEs and INSERTs
rollup rows directly and never fires the `agent_events` trigger. A trigger on
the rollup tables sees both paths, so pre-trigger history and post-trigger
writes reach the totals by the same code.

**D1.3 Append, then fold, so writers never share a row.** Writers only INSERT
into `agent_usage_totals_delta`, which has no unique key and no shared row. A
TimescaleDB job (`add_job`, in the database, so it survives restarts and has no
app-side state, ADR-060) folds the ledger into `agent_usage_totals` every few
seconds, in ONE statement:

```sql
WITH moved AS (DELETE FROM agent_usage_totals_delta RETURNING ...)
INSERT INTO agent_usage_totals ... SELECT key, SUM(...) FROM moved GROUP BY key
ON CONFLICT (...) DO UPDATE SET ... = agent_usage_totals.... + EXCLUDED....
```

The DELETE and the upsert commit together, so every snapshot sees each delta
exactly once, either in the ledger or in the totals. The fold is the only
writer of `agent_usage_totals`. Two concurrent folds cannot double-count: a
row only one of them deleted is only that one's to add. They can contend on
the totals rows, which only folds touch, so the job also takes
`pg_try_advisory_lock` and skips its turn if another fold holds it. The lock
key goes beside the other keys in `syn_adapters.advisory_locks`.

**D1.4 The read.** The global read becomes one statement:

```sql
SELECT key..., SUM(tokens...), SUM(vendor_cost_usd), SUM(summary_observations),
       SUM(reported_observations)
FROM (SELECT ... FROM agent_usage_totals
      UNION ALL SELECT ... FROM agent_usage_totals_delta) t
GROUP BY key...
```

Pricing then runs on those rows in Python, exactly as `_sum_groups` does now
(`query_service.py:319-349`). The read never touches `agent_events`,
`agent_event_day_rollup` or a per-session row. It scans the pricing groups
(models x 2) plus the deltas the fold has not moved yet.

**What is NOT changed.** The route keeps calling `query_svc.totals()`
(`metrics.py:410`). Which tier answers is decided inside
`CanonicalUsageQueryService`, so the route does not learn about it. The scoped
read (`totals(execution_ids=...)`) keeps today's session-grain path in this
ADR (see D6 and the open questions).

#### Why not (a), a continuous aggregate plus a real-time tail

ADR-026 chose TimescaleDB partly for continuous aggregates
(`ADR-026-timescaledb-observability-storage.md:85`). They lose here on the
core rule:

- **Supersession crosses buckets.** A summary written on day D2 supersedes
  that session's turns from day D1. A per-day, per-workflow aggregate has
  already summed D1's turns into D1's bucket, so the read must still undo them
  per session. That puts the O(sessions) decision back on the read, which is
  the cost we are removing.
- **The decision is not an aggregate.** "The most recent usable summary per
  session" is a window function (`canonical_usage.py:109-135`). Continuous
  aggregates materialise `GROUP BY time_bucket` aggregates. Window functions
  are not supported in that position, as far as I know (**assumption A3**, not
  verified against 2.29.2, the pinned image in `infra/README.md:55`). Pushing
  the decision into a cagg would mean a second implementation of the decision
  in a different dialect. That is the drift the single decision exists to
  prevent.
- **A real-time tail reads the raw hypertable.** It reads the rows newer than
  the materialisation watermark, from `agent_events`. Those rows are
  segmented by `session_id` and JSONB-parsed (`schema.py:924-931`), which is
  the read E1 removed. Late and out-of-order turns invalidate already
  materialised buckets and re-materialise them.
- **Freshness becomes a refresh-policy question.** Every number would gain a
  staleness bound. D3 below has none.

#### Why not a naive (b): one totals row per group, updated in the insert's transaction

This is the obvious version of (b), and it fails the north star on locks:

- Every `token_usage` insert, from every concurrent execution, would update
  one of a few rows. There is one row per (model, cost-nullness), and most
  work runs on two or three models. A row lock is held until the writer's
  COPY transaction commits (`store_write.py:131-141`). At 1,000 concurrent
  executions, every ingest transaction on a model would queue behind every
  other.
- A batch that touches two groups locks them in arrival order, so two batches
  can lock them in opposite orders. PostgreSQL resolves that by aborting one
  transaction. Because the trigger runs inside COPY, the aborted batch is lost
  telemetry unless the caller retries. `insert_batch` has no retry.
- Sharding the rows by `hashtext(session_id) % N` divides the contention but
  keeps the deadlock: a multi-session batch still locks shards in data order.
  A statement-level trigger with a transition table could sort its updates,
  but the rollup rows are written by a row-level trigger, one statement per
  row (`schema.py:361-386`), so there is no batch to sort. As far as I know
  (**assumption A4**), TimescaleDB also does not allow transition tables on a
  hypertable.

D1.3 is (b) with the shared row taken off the write path. Writers append, and
one folder owns the shared rows.

#### Why not (c), an ES projection

- **Wrong lane.** Turn-level usage is not in the event store, and must not be
  (Two-Lane rule). A projection over Lane 1 events would total
  `SessionCompleted` figures. That is the source the card left because it
  disagreed with the heatmap by about 850,000 tokens (#932,
  `query_service.py:3-8`).
- **Replay cost.** A `CheckpointedProjection` replays from position zero on
  every VERSION bump and can stall the coordinator (#1318, ADR-055). The
  existing usage tables were made "not a projection" precisely to avoid that
  (`canonical_usage.py:219-221`, `schema.py:253-257`).

### D2. Correctness: the same numbers as today's reader, byte for byte

The new tier stores **token sums and vendor-cost sums per pricing group, never
priced money.** The read prices each group's sums with the same
`price_canonical_row` and `PricingResolver`, at the same grain as today. The
grain is the totals statement's `GROUP BY` (`query_service.py:129`), so
`calculate_cost` receives the same arguments it receives today. The table
below works through each case.

| Case | Today | Rollup tier |
|---|---|---|
| **Unpriced turns** | Groups with no rate add `summary_observations`, then a per-day `agent_events` count of non-zero turns of their summary-less sessions (`query_service.py:336-338`, `:351-403`) | The group's `summary_observations + reported_observations`, added under the same condition (the group's pricing left tokens unpriced). `reported_observations` is the same predicate, evaluated on `NEW.data` at insert time instead of on `data` at read time. **Assumption A5:** the two are the same multiset of turns. The reasoning: a turn is reported in a group iff its session has no winning summary and its recorded model is that group's. Slice 2's parity run is what proves it. |
| **A summary superseding its turns** | `canonical_usage` takes the winner or the turns, never both (`canonical_usage.py:145-152`) | The session's stored canonical rows switch from its turn rows to its summary row when the summary arrives. The delta is minus the turns, plus the summary, in that insert's transaction. |
| **Late or out-of-order turns** | Summed into the session grain whenever they arrive; ignored while a winner exists | A turn arriving after the winner changes the turn rollup, the recompute yields the same canonical rows, and the delta is zero. A turn arriving before any summary adds to the turn row. |
| **A session re-summarised** | Usable first, then the most recent `time` wins (`canonical_usage.py:116-134`) | The same ranking, re-run for that session. A later usable summary replaces the winner. An all-zero or older summary changes nothing. Exact ties in (usable, time) are arbitrary today (`canonical_usage.py:124-128`), so neither path can be byte-checked on them, and the parity seed must not contain them. |
| **Pricing changes in `syn-tokens`** | The next read reprices everything | The same: money is not stored. **Totals recompute on the next read, with no backfill.** A vendor-reported cost is stored as the harness's own figure, as today. |
| **Vendor-cost scale** | `SUM(numeric)` over the winners, then `canonical_cost_usd` (`query_service.py:345`, `pricing/__init__.py:823-838`) | NUMERIC addition and subtraction are exact, but a subtraction can leave a larger scale (trailing zeros). `canonical_cost_usd` quantises and strips them, so the rendered value is equal. The parity test checks the rendered `Decimal`, not the SQL scale. |
| **A group emptied by supersession** | The group is absent | The group row exists with zeros. It prices to `RowCost(0, 0)`, so totals are equal. Slice 4's test asserts that explicitly, so the special case is not left to coincidence. |
| **`CanonicalTotals.sessions`** | Counted from the day rollup | **Dropped from the global read.** `/metrics` does not consume it (#1843, `metrics.py:333-352`). Slice 4 removes it from `totals()`, and the parity test stops comparing it. That is a change of interface, not of any served number. |

**Extending the frozen-reader parity check.** Two frozen oracles already
exist. Neither alone covers every served field, so the plan uses both, for the
fields each actually has.

- **The pre-E1 oracle.**
  - Files: `test_canonical_totals_rollup_parity.py` and
    `legacy_canonical_totals_pre_e1.py`, "FROZEN. DO NOT EDIT".
  - It covers tokens, `cost_usd`, `unpriced_tokens` and `sessions`. It runs
    four ingest batches: A before the rollup exists (backfill), B after
    (trigger), D with the trigger disabled (reconcile), and E after the
    reconcile.
  - It does **not** check `unpriced_observation_count`. That field is excluded
    by name (`_FIELDS_ADDED_AFTER_E1`,
    `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_canonical_totals_rollup_parity.py:223-247`),
    and line 264 asserts only that it is positive.
  - It stays the specification for its fields, unchanged.
- **The pre-2341 oracle.**
  - File: `apps/syn-api/tests/integration/legacy_canonical_totals_pre_2341.py`,
    "FROZEN. DO NOT EDIT".
  - It carries `unpriced_observation_count`
    (`legacy_canonical_totals_pre_2341.py:142-151,246`), and it takes an
    injected `PricingResolver` (`:171-179`).
  - The 6k gate already compares the whole `/metrics` body through it
    (`test_metrics_summary_less_sessions_at_scale.py:162-181`). That seed adds
    no summaries, though, so it never exercises a transition.
  - It becomes the oracle for the observation count, the rendered cost and
    `total_cost_display` through every transition below.

**The transition test** (new, slice 4) runs beside the pre-2341 oracle in
`apps/syn-api/tests/integration/`. It serves `/metrics` from the new tier and
from the oracle, monkeypatched as `_served_before_2341` does (`:162-177`). It
compares the WHOLE body: every token field, `total_cost_usd`,
`unpriced_observation_count` and `total_cost_display`. Each of these steps
seeds one change, compares, and goes on to the next:

| Step | Seeded change | Invariant it proves | Mutation that must turn it red |
|---|---|---|---|
| T1 | turns with non-zero tokens and **zero-token turns** on unrated model M1, for summary-less session S. Also session U, summary-less and never summarised in this test, with k turns of positive tokens (N in total, no `vendor_cost_usd`) and one zero-token turn on a second unrated model M2 | a zero-token turn is a priced zero and is not counted (#890) | count every turn as reported (drop the non-zero predicate) |
| T2 | a usable **summary arrives** for S, on a different model | the turns' group returns to exactly zero (**signed cancellation at group grain**), and the summary's group gains one observation | add the summary without subtracting the turns |
| T3 | a **later, lower** usable summary for the same session | the most recent usable summary wins, not the larger one | rank by magnitude instead of recency |
| T4 | a **late turn** for the summarised session | ignored while a winner exists: zero delta, same body | let the turn path add while a winner exists |
| T5 | an **all-zero summary** after the usable one | it does not win (`canonical_usage.py:136-144`) | let an all-zero summary win |
| T6 | no database write. The same committed state read with a **resolver that rates M2** at known per-bucket rates. U is the only usage on M2, and it is still canonical because U has no summary (`canonical_usage.py:145-152` excludes only the turns of sessions with a winner) | precondition, asserted before T6 in both readers: M2's group holds U's N tokens and its k turns count as unpriced. After T6, in both whole responses at every fold point: `total_cost_usd` rises by exactly U's buckets priced at M2's rates (non-zero), `unpriced_tokens` falls by exactly N, `unpriced_observation_count` falls by exactly k (the zero-token turn was never counted), and `total_cost_display` is re-rendered from those | store priced money in the tier, or cache the resolver's answer at fold time: the live reader keeps the pre-T6 cost and count while the frozen reader moves, so the comparison goes red |

How the comparison is controlled:

- **Fold points.** Each step is compared three times: before any fold, after
  one fold, and after a fold that runs while the next step's transaction is
  open but not committed.
- **One database state for both readers.** The test writes through
  `insert_batch` on its own connection. It holds that transaction open at a
  barrier while both readers run, then commits and runs both again. Neither
  reader can see uncommitted rows, so both see the same committed state each
  time. A false parity failure from a commit landing between the two reads
  cannot happen.
- **No other writer runs during the test.** It owns its database, as the
  existing parity fixtures do.
- **Assumption A10:** the syn-api integration tests can import the domain
  package's pre-E1 oracle. If they cannot, the token-field half of each step
  also runs in the domain parity test, against batch F (below), so both
  oracles still cover it.

**Extending the pre-E1 test** (slices 3b and 4), with the frozen file and its
seed shapes unchanged:

1. Add a batch **F** that arrives AFTER sessions in A/B/E already have
   winners. It holds a late turn on a summarised session, an older usable
   summary arriving after a newer one, an all-zero summary after a usable
   one, and a turn on an unrated model for a summary-less session. Its fields
   are compared against the pre-E1 oracle.
2. Add a property: the rows of `agent_session_canonical_usage`, grouped, equal
   the totals statement's group rows from today's reader, field by field,
   including the observation counts. This checks the intermediate tier
   directly, not just the end figure.
3. Assert invariant I (D5) after every batch: totals plus ledger equals the
   grouped canonical rows.

### D3. Freshness: none to show

The read sums the folded totals AND the unfolded ledger in one snapshot.
An observation is in the totals as soon as its insert commits, exactly as
today. The fold interval changes how many rows the read scans, not what it
returns. So there is no staleness bound and no new display field (#897's
backend-owned display fields are unchanged: `total_cost_display` is still
`format_cost(cost, unpriced)`, `metrics.py:487`).

If the fold stops (the job is disabled or broken), the read stays correct and
slows down as the ledger grows. D7's gate and ADR-075's latency telemetry are
what notice. `validate()` (`schema.py:946`) also fails startup when the fold
job is missing, alongside the other rollup objects (`schema.py:977`).

### D4. Consistency (#983): one exported snapshot for the whole response

**The totals:** one statement, in the existing
`REPEATABLE READ READ ONLY` transaction. Money and its unpriced count are
still read from the same rows. That is stronger than today, which takes three
statements in one snapshot.

**The whole response: every database-derived field is read in one snapshot,
and the global reads stay concurrent.**

What the response reads today, each on its own connection and in its own
snapshot:

| Read | Pool | Where |
|---|---|---|
| `get_dashboard_metrics()` (`total_workflows`, `total_artifact_bytes`) | projections | `metrics.py:173-197`, called first at `:424` |
| Execution status counts | projections | `metrics.py:310-330` |
| Session count | projections | `metrics.py:333-352` |
| Artifact count | projections | `metrics.py:355-373` |
| Canonical totals | observations | `metrics.py:398-416` |
| Scoped only: the workflow's execution ids | projections | `metrics.py:293-307` |
| Scoped only: execution costs | observations | `metrics.py:376-395` |
| Scoped only: phase metrics | projections | `metrics.py:239-282` |

**They are one database.** Assumption A6 in the first draft was answerable,
and the answer is yes:

- `PostgresProjectionStore._get_pool()` connects to
  `settings.syn_observability_db_url`
  (`packages/syn-adapters/src/syn_adapters/projection_stores/postgres_store.py:52-67`).
  It is the production projection store (`projection_stores/__init__.py:52`).
- The observation store's default construction uses the same setting
  (`packages/syn-adapters/src/syn_adapters/events/store_helpers.py:158-173`).
- The canonical reader gets that store's pool (`_wiring.py:758-769,800-811`).

The two are separate pools (`name="projections"`, `postgres_store.py:62-67`),
not separate databases. The Lane 1 event store is a different database, and
`/metrics` reads nothing from it.

**The mechanism: one leader transaction, exported and imported.**

1. The route opens a **leader** connection from the observation pool:
   `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`, then
   `SELECT pg_export_snapshot()`.
2. Every other read takes its own connection from its own pool, as now. It
   opens `REPEATABLE READ READ ONLY` and runs
   `SET TRANSACTION SNAPSHOT '<id>'` as its first statement, before the
   `SET LOCAL plan_cache_mode` that `custom_plans` runs
   (`agent_event_span.py:159-170`). PostgreSQL only accepts the import before
   the transaction's first query.
3. The observation-pool reads run **on the leader itself**: the totals, and
   on the scoped path the execution costs after them. So a request holds at
   most one observation-pool connection.
4. The projection-pool reads import the snapshot and run concurrently under
   `gather`, as #2341/#2361 made them. The scoped path keeps its data order:
   the execution ids first, because the totals and costs need them.
5. The leader commits after the last import has run. An exported snapshot can
   only be imported while its exporting transaction is open.

Every field in both responses then describes the same committed database
state.

**The tradeoff, and why this one.**

- **One connection, one transaction, sequential reads.** This is simpler, but
  it gives up #2361's concurrency. It would also have to move every projection
  read onto the observation pool.
- **Export and import.** This keeps the concurrency. The costs:
  - one extra round trip per read for the import;
  - a leader connection held for the whole request, not just its own read;
  - a new connection-passing seam.

  It cannot starve a pool against itself. A request holds one observation
  connection, the leader, while it waits for projection connections. A
  projection read never waits for an observation connection. So no request
  holds one pool while waiting on the same pool.
- **The seam.** A request-scoped `ReadSnapshot` port (Protocol:
  `connection() -> AsyncContextManager[SnapshotConnection]`). The query
  services and the projection-store read methods used here gain a variant
  that takes a bound connection instead of acquiring one.
  The totals' snapshot helper already takes a connection protocol rather
  than a pool (`custom_plans(conn: PlanningConnection)`,
  `agent_event_span.py:84,159`), so `CanonicalUsageQueryService` is the first
  to convert.
  The route only opens and closes the snapshot. Which pool a read uses stays
  inside the services.
- **Test and offline.** The in-memory projection store has no snapshot. A
  no-op `ReadSnapshot` is valid there, and it inherits `InMemoryAdapter`
  (ADR-060), so it refuses to construct in production.
- **Assumption A6b.** The projection store creates tables and lean columns
  lazily (`postgres_store.py:69-80`), and DDL is refused in a READ ONLY
  transaction. Those calls already run on their own pool connections, outside
  the read. Slice 7 must keep them there, and a test must read a projection
  whose table has not been created yet.

**A shared snapshot is not projection freshness.** The snapshot makes every
field agree about which rows are committed. It does not make the projections
current. Execution, session and artifact counts come from projections that the
coordinator updates asynchronously, each at its own checkpoint (ADR-055). An
execution whose events are not yet projected is still missing from the counts,
while its observations are already in the totals. That lag exists today, and
this ADR neither adds to it nor hides it. The totals tier itself has no lag
(D3).

**This is a separate slice from the rollup** (D8 slice 7). It changes the
route and the projection-store seam, not the totals tier, and either can ship
first.

### D5. Migration, backfill, VERSION, deploy order and rollback

**Projection VERSION: no.** No `CheckpointedProjection`'s stored shape
changes, and none of the new objects is a projection. They are Lane 2 tables
outside the coordinator, like the usage rollup tables before them (`schema.py:253-257`:
"a NEW object rather than a VERSION bump"). Nothing replays the event store,
so this does not need to be grouped with projection-version risk in a beta.
The orchestrator expected a bump, and that expectation would hold only for
option (c).

**Schema.** A hand-applied migration
`packages/syn-adapters/src/syn_adapters/projection_stores/migrations/011_agent_usage_totals.sql`
(the next free number after `010_shipped_ledger.sql`). The same DDL also runs
at startup through `EventStoreSchema`, under its own advisory lock,
mirroring `_create_usage_rollup` (`schema.py:819-871`). Trigger DDL follows
the existing lock-order rule: take `agent_events` first
(`schema.py:228-238`, #1934). The new triggers are on plain tables, but the
`reported_observations` change replaces `agent_usage_rollup_apply`, which is
on the hypertable.

**The invariant every step keeps (I).** At every committed state:

> `agent_usage_totals` + `agent_usage_totals_delta`, summed per pricing group,
> equals `agent_session_canonical_usage` grouped the same way.

Exactly one function writes `agent_session_canonical_usage`: the per-session
recompute. It writes the ledger rows for its own change in the same statement
sequence and the same transaction. So no write to the canonical table can
happen without its delta. The three tables are created, truncated and dropped
**together, in one transaction, and never one at a time**.

Given I, the totals are correct exactly when the canonical table is. A
recompute of any session S brings S's share into line, whatever happened
before, because it diffs against S's stored rows and emits that difference.

**This is why the slices ship the canonical table and the ledger together**
(D8 slice 3b). A canonical table populated before the ledger existed would
break I. Its rows would have no deltas, and a later recompute would see
old = new and emit zero, so their history would never reach the totals.
(Example: S stored as 100 tokens, then an empty ledger is added, then a
recompute emits 0, then the totals read returns 0 for S.) No slice therefore
creates the canonical table without the ledger and the totals, and no
"seed the totals from the canonical table" step exists to get wrong.

**Backfill, in this order. Each step is idempotent and resumable:**

1. **`reported_observations`.** Use the same snapshot-subtraction backfill as
   #1558 r2 (`schema.py:263-287`): per session batch, the non-zero turns in
   the snapshot MINUS the trigger's counted turns in the same snapshot. The
   keep condition (`schema.py:456`) must widen so that a key whose turn count
   already balances can still receive its reported count. This is the one
   genuinely new SQL in the backfill. Slice 2 proves it with the four-batch
   parity seed and `test_usage_rollup_backfill_does_not_block_ingest.py`.
2. **The canonical tier, from empty.** In one DDL transaction, under a new
   schema lock taken after `agent_events` (#1934):
   - create, or TRUNCATE together, the canonical table, the ledger and the
     totals;
   - mark `agent_usage_totals_state` incomplete;
   - create the triggers.

   TRUNCATE takes ACCESS EXCLUSIVE on the three tables until commit. Ingest
   that fires the trigger waits for that commit, then runs against empty
   tables with the triggers live. Both outcomes satisfy I.

   **Step 2r, repair without reset.** The same DDL transaction, under the
   same locks, minus the TRUNCATE: replace the recompute function, `DROP
   TRIGGER IF EXISTS` and `CREATE TRIGGER` for both canonical-maintenance
   triggers (which also restores a disabled one), and mark
   `agent_usage_totals_state` incomplete. The trigger and the invalidation
   commit together, so there is no committed state with the tier marked
   ready and a trigger absent. This is what the usage rollup already does
   for its own trigger: it recreates it and marks itself incomplete in one
   DDL transaction before its backfill
   (`packages/syn-adapters/src/syn_adapters/events/schema.py:857-868`).
   From that commit, every replica's `totals()` reads the state as
   incomplete and serves the session-grain path (Read switch, below), so no
   replica serves the stale tier while the repair runs.
3. **Visit every session.** Read the session list from the day rollup
   (`USAGE_ROLLUP_BACKFILL_SESSIONS_SQL`, `schema.py:395-399`) after step 2
   commits. For each batch, take the schema lock, then the batch's session
   locks (D1.1a), then call the SAME recompute the trigger calls.
   - Every canonical row starts empty, so each visit emits that session's full
     history as a delta. That IS the backfill of the totals.
   - A session the trigger already recomputed after step 2 is diffed against
     correct rows, so its visit emits zero.
   - A session first seen after the list read has no history from before
     step 2.
4. **State row.** Write `agent_usage_totals_state` complete once every listed
   session has been visited, with the triggers live throughout. The same
   transaction re-checks that both triggers exist and are enabled, and
   leaves the state incomplete if either is not, so a trigger lost during
   the visit cannot be followed by a ready mark.
   `_rollup_is_complete` (`schema.py:896`) is the precedent.

**Readiness, interrupted upgrades and re-upgrades.** Startup decides with the
same rule the usage rollup uses,
`needs_backfill = not (trigger_is_live and marked_complete)`
(`schema.py:866`). It extends that with a third input: whether all three
tables exist.

| Startup finds | Action | Why it is safe |
|---|---|---|
| Triggers live, state complete, all three tables | nothing | I holds, and every session has been visited |
| Triggers live, state incomplete (backfill interrupted) | resume at step 3, no TRUNCATE | the triggers were live, so I held throughout, and a re-visit is a diff |
| A trigger missing or disabled, all three tables present | step 2r (restore both triggers and mark incomplete, in one transaction, no TRUNCATE), then steps 3-4 with the triggers live throughout | the recompute is the only canonical writer, so a gap left canonical rows stale **together with** their deltas, and I still holds. 2r closes the gap before the session list is read, so a write after 2r reaches the tier and a write before it is in the day rollup the list is read from. The re-visit repairs the stale sessions. Readers fall back from 2r's commit until step 4 |
| Any of the three tables missing (partial drop, or rollback then re-upgrade) | step 2 (TRUNCATE all three), then 3-4 | I cannot be known, so start the whole tier from empty |

The backfill is awaited at startup, after the DDL, exactly as the usage
rollup's is (`schema.py:869-870`). It is not an API background task. Startup
running a backfill longer than this one has never been decided, and this ADR
does not decide it.

Under `SYN_SKIP_AUTO_CREATE_TABLES=true` (`events/store.py:83-106`), startup
runs no DDL and no backfill. The operator applies migration 011, which runs
steps 2-4 in its documented order. `validate()` then refuses to start without
the tier's objects.

**Read switch.** `totals()` reads `agent_usage_totals_state` in its own
snapshot. Until the state is complete, it serves today's session-grain path.
So a deploy never 503s mid-backfill, and the reader never serves a partial
total.

**Deploy order.**

- Slice 3a (the pre-lock) ships first, on its own. It changes no number.
- Slice 3b creates the tier and backfills it, with the reader unchanged.
- Slice 4 switches the reader.

3b and 4 may ship in the same release. 4 is still safe if 3b has not finished
its backfill, because 4 reads the state row. No separate API and worker
ordering is needed, because the API is the only reader.

**Rollback.**

- **Reverting slice 4** returns the reader to the session-grain path, which
  still works unchanged. The tier keeps being maintained, so I keeps holding,
  and re-applying 4 is immediate.
- **Reverting slice 3b** (a down migration) drops, in one transaction:
  - the two triggers on `agent_summary_usage` and `agent_turn_usage_rollup`;
  - the recompute function;
  - the fold job;
  - `agent_session_canonical_usage`, `agent_usage_totals_delta`,
    `agent_usage_totals` and `agent_usage_totals_state`.

  Re-upgrading hits the "table missing" row above and rebuilds from empty.
- **Reverting slice 3a** is optional. The pre-lock is harmless without the
  tier. If slice 3b is still installed, its trigger raises
  `usage_session_lock_missing` on every write, so 3a cannot be reverted while
  3b is installed.
- `reported_observations` can stay. The old trigger function ignores it, and
  the old reader never reads it.
- No data in the existing rollups is rewritten, so nothing needs restoring.

### D6. Scale

- **Read.** O(pricing groups + unfolded deltas). Pricing groups are models x 2,
  tens of rows. **Assumption A7:** at 1,000 concurrent executions each
  emitting about one `token_usage` per second, a 5 s fold leaves at most about
  5,000 narrow ledger rows. Summing those has no JSON parse, join or window
  function. That is comparable in row count to today's 6,000-session gate, but
  far cheaper per row. A 1 s fold cuts it fivefold. The fold interval is the
  tuning knob, and slice 4 sets it from measurement, not from this estimate.
- **Write amplification, per `token_usage` event.** Today: one hypertable
  row, one day-rollup upsert, one turn-rollup upsert, and the tool-call tally
  (`store_write.py:139-141`). Added: one per-session recompute (a few index
  reads, one to k canonical-row writes) and 0 to k ledger inserts, where k is
  the number of the session's models whose canonical rows changed. A first
  winning summary is the largest change: minus each turn model, plus one.
  Plus WAL for each.
- **Lock contention.** The new locks are all per session: the advisory lock
  and the canonical rows. That is the same scope as the existing turn-rollup
  upsert, so writers of different sessions do not wait on each other. Ledger
  inserts share no row. The totals rows are touched only by the fold, under
  one advisory lock. The naive (b) above would put every writer on a few
  shared rows. This design puts none there.
- **Deadlock.** Per-session scope alone does not rule out deadlock, because
  one batch can touch several sessions, days and models. D1.1a's pre-lock in
  ascending key order is what rules it out.
  - **What the pre-lock costs:** one extra statement per ingest transaction,
    and earlier serialisation of two concurrent batches for the same session.
    Those batches already serialise today on that session's turn-rollup rows,
    so the change is when they wait, not whether.
  - **The cost to measure:** a batch that spans many sessions holds all of
    their locks for the whole COPY. Slice 3a prints the distribution of
    distinct sessions per batch from the ingest benchmark.
    **Assumption A9:** it is small, because batches are per execution.
  - A throughput benchmark shows the cost. It does not prove deadlock safety:
    the ordering argument does, and slice 3a's interleaving tests pin it.
- **Scoped reads** stay on the session grain, bounded by the workflow's
  sessions rather than all history, at 78.6 ms against a 300 ms budget. That is
  not the problem #2383 measured. A per-execution totals grain would double
  the ledger writes to serve them, which is why it is an open question.
  Slice 2's `reported_observations` column does let the scoped read drop its
  per-day `agent_events` branches cheaply. That is optional slice 6.

### D7. Gate

- **Until the behaviour slice lands,** the 100 ms global budget stays
  (`test_dashboard_latency_budget.py:42`).
- **After it lands, proposed: 50 ms global** (owner OK required). Raise it to
  the issue's target only after three CI runs on main print a median round
  p95 under about 30 ms, so the 1.6x runner spread still fits under the
  budget. The scoped budget is unchanged.
- **The scale gate must add a flatness proof that does not depend on runner
  speed:**
  1. A **structural** assertion: the global totals statement's plan
     (`EXPLAIN`) references no `agent_events` chunk, no
     `agent_event_day_rollup` and no per-session table. A regression to a
     history-sized read then fails deterministically, whatever the runner.
  2. A **history-size sweep**: seed 6,000 and 24,000 summary-less sessions
     (4x), and assert the global median round p95 at 24k is within 1.25x of
     the one at 6k. Today's reader cannot pass that. **Assumption A8:** the
     1.25x tolerance is my guess at noise. It should be set from the first
     runs, and stated in the test with its runs.
  3. The response must still equal the frozen reader's
     (`test_metrics_summary_less_sessions_at_scale.py:162-181`).

### D8. Implementation slices

Each slice is under about 400 LOC including tests, merges `origin/main` first,
passes `just preflight-agent` and `uv run pytest -m unit -q`, and commits
mutation patches under `.mutations/` for the orchestrator's trusted run. The
slices are ordered so each one is useful and shippable alone.

| # | Slice | Tests | Mutations that must die |
|---|---|---|---|
| 1 | This ADR | n/a | n/a |
| 2 | **Port + first column.** `reported_observations` on `agent_turn_usage_rollup`: trigger, widened backfill, migration 011 part 1. The reader is unchanged. The query service gains one narrow internal port, `UsageTotalsSource` (Protocol: `group_rows(snapshot) -> Sequence[PricingGroupRow]`, a frozen dataclass), and today's SQL becomes its first implementation, so slices 3-4 swap the source and leave `_sum_groups` as it is. | Parity batches A/B/D/E assert `Σ reported_observations` = the non-zero turns per key; backfill-does-not-block test extended; a unit test that the port's session-grain implementation and `_sum_groups` produce today's `CanonicalTotals` | Count zero-token turns as reported; drop the widened keep condition (backfilled keys lose their count); count the turn in the backfill AND the trigger |
| 3a | **Session pre-lock.** `agent_usage_lock_sessions(text[])`, the lock class in `advisory_locks`, and the call as the first statement of `insert_batch`, `insert_one` and each usage-backfill batch (D1.1a). There is no canonical tier yet, so no number changes. | **Interleaving test:** two connections run the D1.1a schedule (session S, D1/M1 then D2/M2, against D2/M2) with barriers between statements, and both must commit. **Backfill against ingest:** a multi-session backfill batch runs alongside a multi-session COPY that shares two sessions in the opposite order, and both commit. A unit test checks the function's lock order on unsorted input with duplicates. The sessions-per-batch distribution is printed (A9). | Lock in input order instead of sorted order (the opposite-order interleaving deadlocks); drop the pre-lock from `insert_batch` (the S schedule deadlocks once 3b's trigger exists, so this mutant is re-run in 3b, where the enforcement check also fails it) |
| 3b | **The canonical tier, from empty.** `agent_session_canonical_usage`, `agent_usage_totals_delta`, `agent_usage_totals` and `agent_usage_totals_state`, created together. The recompute function, built from `rollup_usage_sources` + `CANONICAL_USAGE_DECISION_CTE`, writes the canonical rows and their deltas, and enforces the pre-lock (`usage_session_lock_missing`). Triggers on both rollup tables, the fold job and its lock, the D5 startup table and backfill steps 2-4, and migration 011. The reader is unchanged. | Property: the grouped canonical rows equal today's totals group rows over the parity seed plus batch F. Invariant I after every batch. Concurrent recompute and backfill converge. **Upgrade test:** install 3a with real history (the parity seed plus the 6k seed), then upgrade to 3b while a writer ingests, and check pre-E1 parity and I before and after a fold. **Resume and reset tests:** stop the backfill midway and restart, which must resume without TRUNCATE. Drop only the ledger and restart, which must reset all three tables and rebuild. **Trigger-gap test:** from a complete tier, disable one canonical-maintenance trigger (and, in a second run, drop the other), ingest during the gap (new turns, and a summary superseding turns), then restart while a concurrent writer ingests. A second connection, standing in for another replica, must read the state as incomplete from 2r's commit until step 4 commits, so `totals()` serves the fallback throughout. After startup both triggers exist and are enabled. Pre-E1 parity and I hold after further writes and a fold; slice 4 re-runs the test against the pre-2341 whole response. A write without the pre-lock raises. Ingest throughput is printed before and after (A2). | Add the summary without subtracting the turns; rank by magnitude instead of recency; let an all-zero summary win; skip the DELETE trigger (a backfill re-run doubles a session); write a canonical row without its delta when the old row is absent (the upgrade test loses history); the reset TRUNCATEs the canonical table but not the ledger and totals (the reset test double-counts); 2r skips restoring the triggers (writes after the restart never reach the tier, and parity after further writes fails); 2r skips marking incomplete (the second connection reads the tier as ready during the repair, and the fallback assertion fails); remove the enforcement check (the 3a "drop the pre-lock" mutant then deadlocks instead of raising) |
| 4 | **Read switch.** The `UsageTotalsSource` implementation over the totals and the ledger, switched on the state row. The `validate()` objects. Drop `sessions` from `totals()`. | The D2 transition test T1-T6, against the pre-2341 oracle, at three fold points. The emptied-group test. A fold racing ingest. A `validate()` test that a missing job fails startup. The 88 ms breakdown printed (A1). A fold run while another fold holds the lock reports itself as skipped, and leaves the ledger untouched. | Fold that deletes without upserting; a read that skips the ledger (stale by one fold); a switch that ignores the state row; each T-row mutation in D2; take the fold lock with `pg_advisory_lock` instead of `try` (the skipped-fold assertion fails because the second fold blocks, then runs) |
| 5 | **Gate.** The EXPLAIN structural test, the 6k/24k sweep, and the budget change after the owner OKs the number | The tests are the deliverable | Revert slice 4's read switch: the structural test and the sweep must both fail |
| 6 | *(optional)* Scoped read drops its per-day `agent_events` branches using `reported_observations` | Parity, filtered, for the three workflows and the empty set | Same as slice 2's first mutation, on the scoped path |
| 7 | **One snapshot for the whole response** (D4). The `ReadSnapshot` port and its export/import implementation. Connection-taking variants of the reads `/metrics` uses. The route opens one snapshot per request on both paths, and `get_dashboard_metrics()` and the scoped phase reads join it. Independent of slices 2-6. | **The #983 concurrency test**, global and scoped. A hook pauses the request after the leader exports. Another connection then commits, in one transaction, a new execution, session and artifact (the projection rows) and its observations. The request is released and its body must be entirely from before that commit. A second run commits before the export and must be entirely from after it. A pool-pressure test: N concurrent requests against a projection pool of size 1 all complete. The A6b lazy-DDL test. | Drop `SET TRANSACTION SNAPSHOT` from the projection reads (some counts include the commit); open the leader `READ COMMITTED`; commit the leader before `gather` finishes (the import fails); run the totals on a second observation connection instead of the leader (the pool-pressure test starves under a size-1 observation pool) |

Implementation code back-references this ADR by its slug,
`ADR-079-metrics-totals-rollup`, at the top of the new schema section and in
the query service.

## Consequences

**Better**

- The global totals read stops growing with history: no `agent_events`, no
  per-session window function, and no unused session count.
- Pricing stays a read-time decision, so a rate-card change takes effect on
  the next read with nothing to backfill.
- Freshness is unchanged: a committed observation is in the next read.
- Nothing replays the event store, and no projection VERSION moves.
- The canonical decision still has one definition. The new tier calls it per
  session instead of restating it.

**Worse**

- Ingest does more work per event: a per-session recompute and ledger inserts.
  That is measured in slice 3b, and the additive fast path exists if it is
  needed.
- There is one more moving part, a database job. If it stops, reads slow down
  but stay correct. That failure is visible in latency telemetry and at
  startup through `validate()`, not hidden.
- The backfill gains one genuinely new piece of SQL
  (`reported_observations`), with the history of #1906/#1934/#1952 as the
  warning that rollup backfill ordering is where bugs live.
- Three tiers of Lane 2 tables now derive from one another. Anyone changing
  `summary_usage_columns`, `turn_usage_columns` or the decision CTE must run
  the parity test, which already covers both lower tiers and will cover the
  new one.

## Open questions for the owner

1. **Whole-response snapshot (#983).** D4 proposes one exported snapshot that
   every read imports. It keeps `gather`, and costs a held leader connection
   per request plus a connection-passing seam in the projection store. Do you
   accept that seam, or would you rather give up concurrency for one
   connection read sequentially now that the totals are cheap? Either way the
   requirement is met, and slice 7 is where it lands.
2. **Scoped totals.** Is the 300 ms scoped budget the goal, or should scoped
   reads also be flat in history? The second means a per-execution totals
   grain and roughly twice the ledger writes.
3. **The tightened budget.** Is 50 ms global the number to aim for once the
   rollup lands, as proposed in D7, or something else?
4. **Fold interval.** Is a database job (`add_job`) acceptable as a new kind
   of moving part, or should the fold run from the API's lifecycle instead,
   under the advisory lock? I prefer the database job: it holds no app state
   and keeps running across API restarts.
5. **Ingest cost ceiling.** What regression in ingest throughput, measured in
   slices 3a and 3b, would make you prefer the additive fast path from the
   start?
6. **Fail-loud enforcement.** D1.1a makes a write that skips the session
   pre-lock raise, so that batch's telemetry is lost and nothing deadlocks
   later. Is losing that batch acceptable as the way an ordering bug shows up?
   The other way is to log and take the lock late, which keeps the batch but
   risks the deadlock.
