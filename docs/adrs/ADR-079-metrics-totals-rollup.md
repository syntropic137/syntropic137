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
Three new objects and one new column:

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

Recomputes of one session are serialized by
`pg_advisory_xact_lock(hashtext(S))`. That lock is per session, so writers of
different sessions never wait on each other through it.

**Assumption A2.** This is per-row trigger work inside COPY, and a batch of N
events for one session recomputes that session N times. I expect each
recompute to be a handful of index reads. Slice 3 must measure ingest
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

**Extending the frozen-reader parity check.**
`test_canonical_totals_rollup_parity.py` already runs the frozen pre-E1 reader
(`legacy_canonical_totals_pre_e1.py`, "FROZEN. DO NOT EDIT") beside the live
one on one database. It seeds four ingest batches: A before the rollup exists
(backfill), B after (trigger), D with the trigger disabled (reconcile), and E
after the reconcile. It compares every field. Each slice extends it, and
neither the frozen file nor its seed shapes change:

1. Add a batch **F** that arrives AFTER sessions in A/B/E already have
   winners. It holds a late turn on a summarised session, an older usable
   summary arriving after a newer one, an all-zero summary after a usable
   one, and a turn on an unrated model for a summary-less session. These are
   the cases above that the existing seed does not hit in that order.
2. Compare at three points: before the fold, after one fold, and after a fold
   that runs **while** batch F is being written. That shows the ledger and the
   totals sum to the same value in any snapshot.
3. Add a property: the rows of `agent_session_canonical_usage`, grouped, equal
   the totals statement's group rows from today's reader, field by field. This
   checks the intermediate tier directly, not just the end figure.

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

### D4. Consistency (#983)

**The totals:** one statement, in the existing
`REPEATABLE READ READ ONLY` transaction. Money and its unpriced count are
still read from the same rows. That is stronger than today, which takes three
statements in one snapshot.

**The whole response: not decided here.** The global route deliberately takes
four connections and four snapshots for concurrency (#2361,
`metrics.py:454-458`). The other three reads are projection reads.
One snapshot for the whole response would mean running them on one connection
in one transaction, which is only possible if they live in the same database
(**assumption A6, unverified**). With the totals at a few milliseconds,
`gather` buys less than it did. This is a real choice with a cost either way,
so it is an open question for the owner, not a decision taken by default.

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

**Backfill, in this order. Each step is idempotent and resumable:**

1. **`reported_observations`.** Use the same snapshot-subtraction backfill as
   #1558 r2 (`schema.py:263-287`): per session batch, the non-zero turns in
   the snapshot MINUS the trigger's counted turns in the same snapshot. The
   keep condition (`schema.py:456`) must widen so that a key whose turn count
   already balances can still receive its reported count. This is the one
   genuinely new SQL in the backfill. Slice 2 proves it with the four-batch
   parity seed and `test_usage_rollup_backfill_does_not_block_ingest.py`.
2. **`agent_session_canonical_usage`.** For each session in the day rollup,
   in batches (the list `USAGE_ROLLUP_BACKFILL_SESSIONS_SQL` already reads,
   `schema.py:395-399`), call the SAME per-session recompute the trigger
   calls, under the same per-session lock. A recompute replaces and emits a
   difference, so the backfill and a concurrent trigger converge in any
   interleaving. The backfill needs no separate totals step: starting from an
   empty table, the recomputes' deltas ARE the backfill of the totals.
3. **State row.** Write `agent_usage_totals_state` once every session has been
   visited with the triggers live. `_rollup_is_complete` (`schema.py:896`) is
   the precedent.

**Read switch.** `totals()` reads the state row in its snapshot. Without it,
the reader serves today's session-grain path. So a deploy never 503s
mid-backfill and never serves a partial total.

**Deploy order.** One release. Startup creates the objects (triggers first),
the backfill runs in the background as the usage rollup's does
(`schema.py:873`), and the reader switches when the state row lands. No
separate API and worker ordering is needed, because the API is the only
reader.

**Rollback.**

- Reverting the reader code goes back to the session-grain path, which still
  works unchanged.
- The new triggers add ingest cost, so a down migration drops them, the job
  and the three new tables. `reported_observations` can stay: the old trigger
  function ignores it, and the old reader never reads it.
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
| 3 | **Per-session canonical rows.** `agent_session_canonical_usage`, the recompute function built from `rollup_usage_sources` + `CANONICAL_USAGE_DECISION_CTE`, triggers on both rollup tables, per-session lock, batched backfill and state row. The reader is unchanged. | Property: the grouped canonical rows equal today's totals group rows over the parity seed plus batch F; concurrent recompute and backfill converge; ingest throughput printed before and after (A2) | Add the summary without subtracting the turns; rank by magnitude instead of recency; let an all-zero summary win; skip the DELETE trigger (a backfill re-run doubles a session) |
| 4 | **Ledger, fold, read switch.** `agent_usage_totals_delta`, `agent_usage_totals`, the fold job and its lock, `validate()` objects, the `UsageTotalsSource` implementation over them, switching on the state row; drop `sessions` from `totals()`. | Full parity at three fold points (D2); emptied-group test; a fold racing ingest; a `validate()` test that a missing job fails startup; the 88 ms breakdown printed (A1) | Fold that deletes without upserting; fold without the advisory lock running twice; read that skips the ledger (stale by one fold); a switch that ignores the state row |
| 5 | **Gate.** The EXPLAIN structural test, the 6k/24k sweep, and the budget change after the owner OKs the number | The tests are the deliverable | Revert slice 4's read switch: the structural test and the sweep must both fail |
| 6 | *(optional)* Scoped read drops its per-day `agent_events` branches using `reported_observations` | Parity, filtered, for the three workflows and the empty set | Same as slice 2's first mutation, on the scoped path |

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
  That is measured in slice 3, and the additive fast path exists if it is
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

1. **Whole-response snapshot (#983).** Keep four snapshots with `gather`
   (today), or co-locate the four reads in one transaction now that totals are
   cheap? This is only possible if the projection store and the event store
   are one database (A6).
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
   slice 3, would make you prefer the additive fast path from the start?
