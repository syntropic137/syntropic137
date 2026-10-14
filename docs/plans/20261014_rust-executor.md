# Plan (final): #1891 phase 2, where Rust enters the executor and the gates before it

Intended home once accepted: `docs/plans/20261014_rust-executor.md`. This phase produces the plan
only. Nothing is committed, prototyped or measured.

**Baselines.**
- syntropic137 `d646b67bd` (= `origin/main`, 2026-10-14).
- PR #1894 (ExecutionHost claim loop, OPEN) @ `777544489`.
- PR #1908 (operation adoption, OPEN).
- AgentParadise/agentic-workspace#60, merged as `900d021`. It is **not** in the pinned gitlink
  `5c4e559`.
- Provider-operation plan `docs/plans/20261013_provider-operation-contract.md`, on branch
  `docs/runtime-research-20261012`.

**Citation tags.** Citations without a tag were re-read on `main` for this revision. Tags mark the
other sources:
- **(#1894)**, **(#1908)**: the PR branch.
- **(AW 900d021)**: the agentic-workspace commit. Not checked out at the pin, so it could not be
  re-read here. These citations come from the review and the research.
- **(rr-branch)**: the runtime-research branch.

---

## Decision in one paragraph

**Recommendation: no Rust ExecutionHost in phase 2. Boundary (c): Python stays the only
implementation of domain decisions and the only Lane 1 and Lane 2 writer.** Phase 2 does three
things, in order:

1. **Measure** the post-split Python executor and **attribute** its CPU. The split is how much goes
   to stream I/O, to JSONL decode and harness parsing, and to aggregates and the journal.
2. Only if that attribution says I/O is worth moving, put **workspace I/O only** behind a Rust
   **operation bridge** owned by agentic-workspace. That covers the `docker exec` stream, spooling,
   bounded paging, cancel, finalize and owner-loss cleanup. **Decoding, line framing and harness
   parsing stay in Python in phase 2.** The seam merged in AW#60 is a byte transport, not a
   normalization boundary.
3. Moving harness normalization to Rust needs a **normalized live-stream contract** that does not
   exist. It is a separate, gated step (R2). Its contract is specified here, but it is not scheduled.

A full Rust ExecutionHost is deferred behind gate G3. It needs a language-neutral decision kernel
that does not exist and is not designed here. The brief asked for a Rust executor, so this rescope
**needs the owner's decision (H1)**.

---

## 1. Problem

The north star is 20 concurrent executions now, 100 next and 1,000 for production
(`docs/north-star.md:11-13`). The pass bar is:
- p95 of the dashboard list and detail reads under 500 ms;
- zero lost or orphaned executions;
- reconciled event counts;
- held for 30 minutes, with every run admitted within 5 minutes (`docs/north-star.md:15-21`).

At 100, the capacity model's "single process" line describes the **API process**: "100 `docker
exec` streams and every projection in one process". It is labelled **hypothesis**, and its remedy is
the executor/API split (`docs/north-star.md:166`). ADR-072 D1 then moves projections to the `api`
role and keeps them out of the `executor` role
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:66-70`). So the thing a Rust
executor would speed up is the **post-split executor**: claim loop, `run_claimed`, agent streams,
credential keeper, artifact collection and reconciliation. Nobody has measured it. Per-run RSS is
"**unmeasured**" (`docs/north-star.md:77`). The host-CPU estimate (about 1.2 CPU per run, 7.5x over
at 100) is mostly **workspace** load, which no executor language reduces
(`docs/north-star.md:73,163`).

Every domain decision runs in-process in the executor today, for example
`aggregate.complete_execution(...)` followed by `journal.append(aggregate)`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:713-714`).
A second-language executor therefore needs either a second implementation of domain truth or a
boundary that does not exist.

#1891's own rule is "No phase starts without the measurement that justifies it", and that
measurement does not exist yet.

**Observable goal.** N concurrent runs hold the pass bar with lower executor CPU-seconds and memory
per active run. The streams must be byte-for-byte equivalent (after canonicalization, §3) to what the
Python path writes. The queue must keep its fencing and lease guarantees unchanged.

## 2. Ownership boundary (brief item 1)

### 2.1 Options weighed

**(a) Port the aggregates to Rust and append through the Rust ESP SDK.** Rejected.
- The SDK's error contract is compatible. `ConcurrencyConflict` is a separate variant from transient
  errors (`lib/event-sourcing-platform/event-sourcing/rust/src/error.rs:25-31`), and saves carry an
  idempotency key (`lib/event-sourcing-platform/event-sourcing/rust/src/repository.rs:6-27`). That
  matches what `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/execution_journal.py`
  relies on.
- The cost is a second implementation of the decision rules:
  - 18 command handlers in
    `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/WorkflowExecutionAggregate.py`;
  - about 1.3k lines of value objects;
  - the legacy-shape readers;
  - the slice-level decisions (`phase_verdict.py`, `phase_outcome.py`, `unpushed_work_guard.py`,
    about 2.6k lines);
  - the AgentSession and Artifact aggregates the executor also writes.
- Only sampling tests would keep the two in agreement.
- The D9 epoch fitness function, which would stop a differently built writer from mis-reading
  events, is not built
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:5-6`).

**(b) A Rust executor drives phases and calls a thin Python command API.** Rejected.
- No such API exists. The decisions are interleaved with infrastructure work across about 22.7k lines
  of `slices/execute_workflow`. Either Rust re-derives the decisions, which is (a), or every step is
  an RPC and Rust is a loop around Python.
- It also makes running executions depend on the API being up. That reverses ADR-072's stated gain
  that an API OOM no longer takes executions with it
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:634-635`).

**(d) A Rust claim loop that supervises Python run workers.** Rejected for phase 2.
- The loop does one heartbeat and claim every 5 s (#1894 `HostTiming`), so its CPU cost is
  negligible.
- Porting it duplicates the compare-and-set SQL of D3/D4/D5/D9
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:107-148`) for no measured gain.
- Process isolation is already available as k Python executors, each with its own budget row
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:150-161`).

**(c) Chosen: Python keeps every decision; Rust enters below the workspace operation seam, staged
and gated.**

### 2.2 Ownership after phase 2

| Concern | Owner | Where today |
|---|---|---|
| Claim, heartbeat, renew, defer, close, fence, reconcile (D3-D5, D9) | **Python** ExecutionHost (#1894) | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:107-148` |
| Aggregate decisions, phase verdicts, unpushed-work guard, every Lane 1 append | **Python** processor through `ExecutionJournal` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:470-715` |
| Pricing, cost, attribution, every Lane 2 write | **Python** | `apps/syn-api/src/syn_api/_wiring.py:303` |
| JSONL decode, line framing | **Python** in phase 2 (the #1908 decoder); moves only with R2 | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:186` (`read_lines`) |
| Harness parsing (Claude, Codex) into tool, token, session and subagent facts | **Python** in phase 2; AW-owned normalization only with R2 | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/EventStreamProcessor.py`, `CodexStreamProcessor.py`, chosen at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:401-449` |
| Domain judgments on those facts: cost limit, push observer, cancel via controller | **Python, always** | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:412-413,436-449` |
| Workspace I/O: exec, byte stream, spool, page, cancel, finalize, owner-loss cleanup | **`SupportsOperations` port.** Python provider by default (#1908); Rust bridge for the canary (R1) | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:176-182`; the duplicate exec path documented at `:150-153` |
| Credential renewal schedule, setup-then-clear, revocation | **Python** keeper; values reach Rust only through the bridge's resolver callback (§4.3) | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:87-110` |

**One source of domain truth.** Every decision has exactly one implementation, in Python. Rust never
writes an event, never writes Lane 2, and never decides anything. In R1 it moves bytes. In R2
(gated) it emits **harness facts**: what the CLI said. Python turns those facts into the same
commands and judgments it makes today.

**What R1 actually buys, stated narrowly.**
- Today one `asyncio.create_subprocess_exec` of the docker CLI runs per agent, and Python reads it
  line by line through a pipe buffer of up to 10 MB
  (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:176-182`).
- Under R1, one Rust process per executor holds every exec stream, spools it and serves bounded
  pages. Python still decodes and parses every byte.
- So R1's gain is bounded by the I/O share of executor CPU and by the pipe and buffer memory. It
  saves nothing on parsing or the journal. Whether that share is worth a phase is what G1 decides.
- The AW Docker provider is "still one `docker exec` client per running operation"
  (rr-branch, `docs/plans/20261013_provider-operation-contract.md` §5.2). Whether the Rust bridge
  keeps docker CLI children or attaches through the Engine API is AW's choice, and it materially
  changes R1's gain. It is recorded as H5.

### 2.3 R2: the normalized live-stream contract (specified, not scheduled)

R2 moves harness normalization into the AW Rust bridge. It runs only if G1 attributes executor CPU
mainly to JSONL decode and harness parsing. Before any code moves, AW publishes a JSON-Schema
`HarnessFact` stream as an extension of `HarnessTranscript`/`TranscriptExtractionResult`, per
CLAUDE.md "Where does this change belong?".

The stream carries harness facts only:
- `session_started{harness_session_id, model}`;
- `tool_started{tool_use_id, name, input_digest, input}` and `tool_finished{tool_use_id, is_error, output}`;
- `subagent_started` and `subagent_finished`;
- `token_usage{input, output, cache_read, cache_write, model}` per turn;
- `embedded_jsonl{source:"tool_result", line}` for the post-commit hook lines that arrive inside a
  `tool_result` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:140-145`);
- `result{status, error}`;
- `raw_unrecognized{line}`, so no line is ever silently dropped.

These stay in Python and consume the facts:
- `PhaseCostLimit` (cost is pricing, which is domain);
- the `PushObserver`;
- cancel through the controller;
- observation attribution (`execution_id`, `phase_id`, `workspace_id`);
- every `record_observation` call
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/EventStreamProcessor.py:85-96`).

The R2 exit gate is the §3 L1 corpus. The Python and Rust normalizers must emit identical
`HarnessFact` sequences for every recorded Claude and Codex transcript. The §3 L2 fixture must then
pass with the Rust normalizer selected. R2 gets its own plan once G1 passes for it.

## 3. Parity contract (brief item 2)

There are three layers. Each one fails if the thing it guards is reverted.

**L0: queue semantics, unchanged.**
- The host stays Python, so the six `test_1310_*` files (#1894) run unchanged and stay required.
- The stale-write rejection asserted by the subprocess harness (#1894
  `apps/syn-api/tests/integration/_1310_executor_process.py:65`) is kept as it is.

**L1: provider contract (AW-owned).**
- The same recorded byte stream is fed through the Python and Rust providers. The resulting
  `ObservationPage` sequences must reassemble to identical bytes.
- Page boundaries, gap/loss reporting and cursor resumption must agree.
- This reuses the #1908 recording tests, which already exercise page boundaries and gaps (#1908
  `packages/syn-adapters/tests/workspace_backends/agentic/test_stream_on_operations.py`).
- For R2 only: identical `HarnessFact` sequences.

**L2: the production-path parity fixture (new, PR 4).** V5 as it stands cannot detect a provider
defect. Both its reference run and its claimed run use `FakeAgentExecutionHandler`, a memory
workspace backend and `observability_writer=None`
(`apps/syn-api/tests/integration/test_1310_a_claimed_three_phase_run_succeeds_on_real_stores.py:13,189,221,291,308`).
It also compares event types only (`apps/syn-api/tests/integration/test_1310_a_claimed_three_phase_run_succeeds_on_real_stores.py:239,335`).
V5 is kept as is, as a queue test, and a new fixture is added beside it. It runs on the real-infra
fixtures (Postgres 16 image, event store, MinIO):
- **Real path.** A real labelled workspace container runs the #1717 stub agent image. It replays a
  committed corpus of recorded Claude **and** Codex JSONL, including embedded `tool_result` JSONL, a
  subagent, a tool error and a cost-limit trip.
- **Real handlers.** The real `AgentExecutionHandler`, the real stream adapter on the selected
  provider, real Lane 2 (`AgentEventStore`), and real capture and artifact collection.
- **Runs.** The identical corpus is run once per provider (`python`, `rust`).
- **Bridge traversal is proven, not described.** The Rust bridge keeps a per-operation call ledger
  (`start`, `observe` count, `cancel`, `finalize`) that the test reads back from the bridge process.
  The `rust` case asserts ≥1 `start` and `finalize` per phase and ≥1 `observe` per phase. A wiring
  revert to the Python provider leaves the ledger empty, and the case fails. `describe()` identity is
  not used as proof.
- **Comparison: every stream, every payload.** WorkflowExecution, every AgentSession and every
  Artifact stream are read back in full, together with every Lane 2 row for the run.
  - Volatile fields (timestamps, durations) are masked by **one** allowlist in one function.
    Anything not on it is compared.
  - Generated ids are **canonicalized by correspondence**, not erased. Each distinct id is replaced
    by `<kind>#n` in first-seen order across all streams, so a broken cross-stream link
    (session→execution, artifact→phase) changes the canonical form and fails.
  - Lane 2 rows are compared as full rows, after the same canonicalization: observation type, the
    full `data` payload, `execution_id`, `phase_id` and `workspace_id`. A multiset of types and
    counts would accept corruption.
- **Mutation checks (exit test of PR 4).** The test fails for each of these, injected one at a time
  through a test-only perturbing provider:
  1. a changed token count where totals are kept equal by a compensating change;
  2. a tool name or `tool_use_id` altered with types and counts unchanged;
  3. a dropped `session_id` attribution on one observation;
  4. a swapped artifact→phase link;
  5. one dropped embedded-JSONL line.

**L3: owner death (PR 5).** Under the Rust bridge:
1. Start a real Rust operation whose agent process forks a descendant.
2. SIGKILL the owning executor process, and separately SIGSTOP it past the TTL.
3. Assert:
   - the bridge terminates the operation (no `docker exec` child and no agent descendant remain in
     the container);
   - the dead host's containers are reaped through `syn.host_id`;
   - the row ends `interrupted`;
   - a late write from the stopped executor is rejected (the retained stale-write assertion).

This is the new risk the bridge introduces, and #1894's `_StallingDrainer` cannot exercise it,
because it launches `docker run ... sleep 600` directly with no operation in between
(#1894 `apps/syn-api/tests/integration/_1310_executor_process.py:46-64`).

The brief's literal requirement, "identical event sequences vs the Python executor", holds by
construction, because there is one executor. L2 checks it per provider.

## 4. Telemetry, capture and credential parity (brief item 3)

### 4.1 Lane 2
- Writing stays in Python. The bridge never connects to `SYN_OBSERVABILITY_DB_URL`.
- Parity is the full-row Lane 2 comparison in L2.

### 4.2 Capture
- Session capture and transcript extraction are unchanged in phase 2. Python still parses.
- Parity is the AgentSession stream equality in L2, plus the #1550 reconciliation ("per-run event
  counts match the recorded transcripts", `docs/north-star.md:21`), run during every canary step.

### 4.3 Credentials
The bridge's `CredentialResolver` is a Rust trait (AW 900d021). Across the process boundary it
becomes a **callback over the bridge's own socket**:
- the bridge asks Python for a named credential when it starts an operation;
- Python answers with the value;
- the bridge delivers it to `docker exec` only as `-e NAME` with the value in the child's
  environment, never in argv (AW plan §5.2);
- the value is held only for that call.

The renewal schedule, setup-then-clear (ADR-024) and revocation stay in the Python keeper.
`keep_credential_fresh` exposes injectable `now` and `sleep`
(`packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:87-100`).
It renews first at 40 minutes, then every 40 minutes, retrying every 3 minutes
(`packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:47-51`).
It replaces credentials and never revokes them, because revocation is teardown's job
(`packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:25-28`).

The PR 5 exit test runs each case against a **real selected-provider operation**, for both
providers:
- **No secret leaks.** No secret value appears in any host process argv (`/proc/*/cmdline` sampled
  while the operation runs), in the bridge's ledger or logs, or in any Lane 2 row.
- **Setup-then-clear.** The agent's exec environment after setup lacks the cleared values.
- **Renewal succeeds.** With the injected clock driven past `FIRST_RENEWAL`, a renewal lands while
  the operation is running, and the next exec the agent makes uses the new token.
- **Lapse.** With renewals failing until expiry, `on_lapse` fires exactly once with a
  `CredentialLapse`, and the operation keeps running.
- **Cancellation.** When the operation ends, the keeper task is cancelled with no renewal after it.
- **Teardown.** Revocation runs once for each unexpired minted token
  (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:328`).

## 5. Rollout (brief item 4)

### 5.1 Shipping the bridge
- `PINNED_DIGESTS` pins **workspace images** only
  (`packages/syn-shared/src/syn_shared/settings/workspace_images.py:598,680`). It does not identify a
  host-side binary.
- The `syn-api` image installs AW **Python source** from the gitlink today
  (`infra/docker/images/syn-api/Dockerfile:31-33,59-61`).
- The bridge binary is therefore **built from the same gitlink** in a cargo stage of the `syn-api`
  Dockerfile and copied into the final image. Its identity is the `lib/agentic-workspace` gitlink
  plus the `syn-api` image digest. That is still "one pin, one build identity"
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:72-74`), and no ADR change is
  needed (H3 confirms).
- The bridge prints its gitlink SHA in `describe()`, and the executor logs it at registration.

### 5.2 Pool
- A second compose service, `executor-rs`, runs the same image with `SYN_PROCESS_ROLE=executor`,
  `SYN_WORKSPACE_OPERATION_PROVIDER=rust` and `SYN_EXECUTOR_POOL=rs`.
- Both settings live in Pydantic Settings classes per ADR-004 and are regenerated into
  `.env.example`.
- The service registers its own `host_id`, so it has its own `execution_budget` row (D3).

### 5.3 Canary share: an enforced cohort
A capacity ratio is **not** a share. The claim takes the oldest eligible run and checks only the
claiming host's room (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:115-130`).
A one-slot Rust host can take every run that arrives sparsely. Global capacity in D3 is a reporting
sum, not an allocation rule
(`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:154-156`), so a run-eligibility
rule does not weaken D3. The plan therefore adds one:

- **Schema.** `execution_runs.pool TEXT NOT NULL DEFAULT 'default'` and
  `executor_hosts.pool TEXT NOT NULL DEFAULT 'default'`. They are added with idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements after the `CREATE TABLE IF NOT EXISTS`
  blocks. Changing the declarations alone would not alter existing installations
  (`packages/syn-adapters/src/syn_adapters/execution_runs/schema.sql:1,21`). The index is
  `(state, pool, admitted_at)`.
- **Admission.** `reserve` stamps `pool='rs'` when
  `hash(execution_id) mod 10000 < SYN_EXECUTION_CANARY_BASIS_POINTS`. The share is decided per run,
  deterministically, at admission.
- **Claim.** One added predicate in the candidate CTE
  (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:127-130`):
  `AND (r.pool = $host_pool OR r.admitted_at < clock_timestamp() - $hold)`.
  - An `rs` host claims only `rs` rows, so sparse arrivals cannot pull default work onto it.
  - A default host takes an `rs` row only after `hold` (default 120 s). A dead or drained canary
    pool therefore never strands work. The cost is that the share is an upper bound during a canary
    outage, and that case is reported.
- **Measured share.** Every step reports the realized share: runs closed by `rs` hosts out of all
  closed runs, from `execution_runs` joined to `executor_hosts`. It also reports how many `rs` rows a
  default host took after `hold`.
- **Steps.**
  1. 1% (100 bp);
  2. 10%;
  3. 25%;
  4. 50%;
  5. 100%.

  Each step is held for at least one beta and one #1550 detector run. The Python-provider pool is
  then kept registered at capacity ≥1 for one release as the rollback target.
- **Tests (PR 6).**
  - Saturated load: the realized share is within ±5 points of the target across 200 runs.
  - Sparse arrivals (one run at a time, both pools idle): an `rs` host never claims a `default` row.
  - Canary pool down: `rs` rows are claimed by a default host after `hold` and not before.

H4 asks the owner to accept this predicate on the hot claim. The alternative is an explicit
"concurrency ceiling, uncontrolled share", with the realized share measured. The plan recommends
the cohort.

### 5.4 Kill switch
- **Routing:** set `SYN_EXECUTION_CANARY_BASIS_POINTS=0`. New runs go to `default` at admission,
  and `rs` rows already admitted fall back after `hold`.
- **Lossless:** drain the `executor-rs` host with `PUT /executors/{host_id}/drain`. It stops
  claiming, finishes what it holds, deletes its row and exits 0
  (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:577-585`). **This route does not
  exist on `main`**: the only drain-related route file, `apps/syn-api/src/syn_api/routes/maintenance.py`,
  is the pit-stop drain. It is a prerequisite (P0), or PR 6 builds it.
- **Immediate:** stop the container. Its runs become `interrupted` through D5 reconciliation and are
  never re-run.

### 5.5 Rollback
Route to 0 and drain `executor-rs`. Both providers write the same streams (L2), so nothing is
migrated and no projection is rebuilt.

## 6. Measurement (brief item 5)

### 6.1 Entry point
The load test already has one: `python -m syn_perf.loadtest --n N --tier platform|node`
(`packages/syn-perf/src/syn_perf/loadtest/__main__.py:1-6,44-80`). The earlier draft said it lacked
one; that was wrong. PR 1 extends it with an `--executor-container` option (repeatable) and an
`--arm` label.

### 6.2 What is wrong with the current instruments
- `ContainerStat` has CPU percent and memory bytes, with no timestamp and no active-run count
  (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:102-106`).
- The samples come from `docker stats --no-stream` snapshots
  (`packages/syn-perf/src/syn_perf/loadtest/driver.py:404-413`).
- `ContainerRoles` has no executor role (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:109-124`).
- `PassBar.read_p95_seconds` is the **threshold**, not an observation
  (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:145`). The observed values are
  `LoadTestReport.list_p95_seconds` and `detail_p95_seconds`
  (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:190-191`).

### 6.3 PR 1 instruments
- **Raw executor samples.** A new `ExecutorSample` is taken every 5 s for each executor container,
  and for the bridge process wherever it runs. It holds:
  - `at` (monotonic and wall clock);
  - the container id;
  - cumulative cgroup v2 `cpu.stat usage_usec`;
  - `memory.current` (cgroup usage, including page cache);
  - `memory.stat anon` (reported as the RSS proxy, labelled as such);
  - the executor's `execution_budget.in_use`, read from Postgres in the same tick;
  - the count of that executor's active phases.

  All raw samples are written to the report.
- **Derived values, per arm.**
  - **CPU:** CPU-seconds per active-run-minute, from the cumulative `usage_usec` deltas divided by
    the in-use integral. The cgroup includes `docker exec` and bridge children.
  - **Memory:** the regression of `anon` on in-use per executor, reporting the **intercept** (fixed
    per-process memory) and the **slope** (marginal per-run memory) with 95% intervals.
    `memory.current` is reported beside it.
  - **Idle baseline:** executors registered with zero runs for 5 minutes.
  - **Pool totals.**
- **Attribution (decides R1 vs R2 vs neither).** On the test stack only, the executor in arm A runs
  under `py-spy record` for 10 minutes at N=20 (needs `SYS_PTRACE`). Its samples are bucketed by
  frame into four buckets:
  - stream I/O (`read_lines`, subprocess pipes);
  - decode and harness parse (`EventStreamProcessor`, `CodexStreamProcessor`);
  - domain and journal (aggregates, `ExecutionJournal`, event-store client);
  - other.
- **Claim latency.**
  - Columns `first_claimed_at` and `claimed_at`, added through idempotent
    `ADD COLUMN IF NOT EXISTS`. `claim` sets `claimed_at = clock_timestamp()` and
    `first_claimed_at = COALESCE(first_claimed_at, clock_timestamp())` in the same UPDATE
    (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:131-134`).
  - First-claim latency = `first_claimed_at − admitted_at`.
  - Re-claim latency (after `defer`) = `claimed_at − retry_at` for rows whose
    `claimed_at > first_claimed_at`. It is reported separately.
  - The driver exports p50/p95 of both with one SQL query, and the report names the query.
- **Dashboard reads.** Observed `list_p95_seconds` **and** `detail_p95_seconds`.
- **Pass bar unchanged.** 30-minute sustain, admission within 5 minutes, zero lost or orphaned,
  counts reconciled (`docs/north-star.md:16-21`).
- **Repetition.** 3 runs per arm and N. The report gives the median and the min-max range, and an
  arm difference is claimed only when the ranges do not overlap.

### 6.4 Arms (same host; N=20, then N=100)

| Arm | Executors | Provider | Purpose |
|---|---|---|---|
| A | 1 process | Python | post-split baseline (the control) |
| B | k processes (k = N/10) | Python | does isolation alone clear the bottleneck? |
| C | 1 process | Rust bridge (R1) | the R1 effect |
| D | k processes | Rust bridge (R1) | the R1 effect with isolation |

Arm B stays the honesty control. If k Python processes already clear the 100-tier executor limit,
Rust has to win on cost, not on feasibility.

### 6.5 Gates
- **G1, after PR 1, arms A and B at N=20, then N=100.** Proceed to R1 only if **both** hold:
  - the executor role is ≥10% of host CPU-seconds per active run, or its memory intercept plus 100 ×
    slope exceeds one executor container's limit; **and**
  - the stream-I/O bucket is ≥30% of executor CPU.

  If decode and parse dominate instead, write the R2 plan (§2.3) and skip R1. If neither holds, stop.
  The effort goes to cheaper runs (#1714) and to budget sizing (#1715): below 10%, even an infinitely
  fast executor saves less than 10% of host CPU. The thresholds are H2.
- **G2, after PR 7 (canary at 100%), arms C and D.** R1 is kept only if arm C beats arm A on executor
  CPU per active-run-minute or on the memory slope, by non-overlapping ranges. Otherwise it is rolled
  back and the bridge is not shipped as the default.
- **G3.** A full Rust ExecutionHost is re-proposed, with its own ADR and a decision-kernel design,
  only if the remaining Python executor cost still binds at 100 after G2.

## 7. Ordered PRs with exit tests (brief item 6)

**P0, prerequisites (not planned here):**
- #1894 merged.
- ADR-072 Phase 1: `SYN_PROCESS_ROLE` and an `executor` compose service. Today the only API-role
  service is at `docker/docker-compose.syntropic137.yaml:237`.
- The `PUT /executors/{host_id}/drain` route.
- #1717's stub agent image (7b).
- **#1908 reviewed and merged.** It brings the Python `OperationHost`, the operations-backed adapter,
  the line decoder, observe/status handling and cancellation. Its recording tests are reused for L1.
  This plan does **not** re-implement that seam.

| # | Repo | Change | Exit test (what it asserts; what reverting the change does) |
|---|---|---|---|
| 1 | syn | **Measure.** The §6.3 instruments: `ExecutorSample`, executor and bridge roles, attribution, the claim-latency columns through idempotent ALTERs plus the export query, observed list and detail p95, repetitions. | (i) `packages/syn-perf/tests/test_loadtest_pass_bar.py`: a report lacking executor samples, lacking `detail_p95_seconds`, or whose dashboard figure equals `PassBar.read_p95_seconds` rather than being computed from samples **fails validation**. (ii) A schema test applies the **current** `schema.sql`, inserts rows, runs the new `ensure_ready` twice and asserts the columns exist and the rows survive. (iii) A `test_1310_*`-style claim test asserts `admitted_at ≤ first_claimed_at ≤ claim return`, and that after `defer` and re-claim `first_claimed_at` is unchanged while `claimed_at` moves. **Then run arms A and B at 20 and 100 and record them in `docs/experiments/`. G1 is decided here.** |
| 2 | AW | **Bridge contract.** A JSON-Schema (APSS) request/response protocol over a Unix socket: `start`, `observe(cursor, max_bytes)` with bounded pages, `status`, `cancel`, `finalize`, `resolve_credential` (bridge→host callback), and `ledger`. Owner loss: the socket closing, or the parent's death through `PR_SET_PDEATHSIG`, cancels every operation and kills its exec children. Failures are typed (`not_found`, `lost`, `provider_error`, `credential_unavailable`) with a stated mapping to Python exceptions. | Schema fixtures validated by both the Python and Rust implementations. A Rust test: closing the socket mid-operation leaves no exec child within 5 s. A page never exceeds `max_bytes`. |
| 3 | AW | **Bridge binary** (`aw-opd`) over `implementations/docker` (AW 900d021), implementing PR 2. Released from AW `release`. | L1: recorded streams reassemble byte-identically under both providers, with page and gap behaviour equal (the #1908 corpus). |
| 4 | syn | **Bump the AW gitlink** to include PRs 2-3. **Add the L2 production-path parity fixture** (§3), Python provider only at first, with the five mutation checks. V5 stays as is. | Each mutation in §3 L2 fails the fixture. An unperturbed run passes. Fixture run time is recorded. `git merge-base --is-ancestor 900d021 <gitlink>` holds. |
| 5 | syn | **Provider selection.** `SYN_WORKSPACE_OPERATION_PROVIDER`, a cargo stage in the `syn-api` Dockerfile building `aw-opd` from the gitlink, a Python `BridgeOperations` client satisfying `SupportsOperations`, the L2 fixture parametrized over the provider, L3 owner death, and the §4.3 credential cases. | The `rust` case reads a non-empty ledger for every phase; reverting the wiring fails it. L3 passes under SIGKILL and SIGSTOP. Every §4.3 credential case passes on both providers. The six `test_1310_*` files stay green. |
| 6 | syn | **Pool and cohort.** The `pool` columns (idempotent ALTERs), stamping in `reserve`, the claim predicate with `hold`, `SYN_EXECUTOR_POOL` and `SYN_EXECUTION_CANARY_BASIS_POINTS`, the `executor-rs` compose service, the drain route if P0 did not deliver it, and the realized-share query. | The §5.3 tests: share under saturation, no default row on an `rs` host under sparse arrivals, fallback after `hold`. The six `test_1310_*` files stay green with the predicate in place. |
| 7 | ops | **Canary** steps 1% → 100% (§5.3), each held for at least one beta and one #1550 run, with a kill-switch drill (route to 0, then drain) at step 1. Then arms C and D at 20 and 100. **G2 is decided here.** | The #1550 detector reports zero dropped starts. Per-run event counts of `rs` runs equal their transcripts. The realized share is reported per step. A drained `executor-rs` exits 0 with `in_use=0`. |

PRs 2-3 can proceed in parallel with PR 1 once the contract (PR 2) is agreed. They are only
*merged into use* (PR 5 onward) if G1 selects R1.

**Maintenance cost.**
- **syn** gains:
  - two settings and two pool columns;
  - one claim predicate;
  - one compose service during the canary;
  - a cargo stage;
  - the parity fixture with its allowlist and recorded corpus.
- **AW** gains a bridge binary and protocol. AW already committed to two provider implementations
  held together by shared fixtures.
- **The domain** gains **zero** second implementations.
- **Net:** adopting the operation seam (#1908) removes the documented second exec path
  (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:150-153`).

## 8. Risks

| Risk | Signal / mitigation |
|---|---|
| R1's gain is negligible, because executor CPU is mostly parse and journal, or host CPU is mostly workspace (`docs/north-star.md:163`) | G1 attribution stops R1 before any syn change. If G2 shows no non-overlapping improvement, roll back |
| The bridge keeps docker CLI children, so per-run processes do not fall | H5; visible in G2 as a flat memory slope |
| A Rust operation outlives a dead executor (orphan agent, effects after reap) | L3 in PR 5. In production: containers labelled with a departed `syn.host_id` after `interrupted`, and the D5 reap-window alert |
| A provider page or gap bug corrupts a stream while counts still match | L2 full-row comparison plus the mutation checks; the #1550 per-run counts in the canary |
| A secret leaks through argv, the ledger or a bridge log | §4.3 cases in PR 5; the callback holds a value only for the call |
| The claim predicate slows the hot claim or starves a pool | The PR 6 share tests; claim latency p95 from PR 1 compared before and after PR 6; `hold` fallback |
| AW delivery latency (merge → release → gitlink) stalls PRs 3-5 | PR 2 is agreed before PR 1 finishes. Flag it if PR 3 is not released two weeks after G1 |
| #1908 changes shape before it merges | It is a P0 prerequisite; PR 4 rebases on whatever merges |
| The bridge build adds cargo to the `syn-api` image build and to CI | Map the new job in `scripts/check_ci_parity.py`. `just preflight-agent` cannot run cargo; CI does |

## 9. Verification

- `uv run pytest packages/syn-perf/tests/test_loadtest_pass_bar.py -q`: the report validation from
  PR 1.
- `uv run pytest apps/syn-api/tests/integration -k "1310" -q`: the six queue files, green on the
  PR 4, 5 and 6 heads.
- The L2 fixture, with `-k "python or rust"`: both providers pass, and each mutation fails.
- L3 and the credential cases (PR 5).
- The cohort tests (PR 6).
- `just preflight-agent` and `uv run pytest -m unit -q`. CI runs cargo, docker and integration.
- Load runs:
  `uv run python -m syn_perf.loadtest --n 20 --arm A --executor-container <name> ...`, then
  `--n 100`. Results go in `docs/experiments/`, with the G1 and G2 verdicts and the raw samples.

## 10. Out of scope

- Porting any aggregate, projection or the run queue to Rust.
- A Rust ExecutionHost (G3, its own ADR).
- R2 normalization (its own plan, after G1).
- The D9 epoch fitness function. It is needed anyway but is not on this path.
- Multi-host placement (#1734), remote sandboxes (#350), Adopt/Reattach.
- Event-store, Postgres or Redis upgrades.

## 11. Needs a human decision

1. **H1, the rescope.** Accept "Python remains the executor; Rust enters as an I/O bridge below the
   operation seam (R1), with normalization (R2) and a Rust ExecutionHost (G3) gated", instead of the
   brief's Rust ExecutionHost. This is the owner's call.
2. **H2, the G1 thresholds.** The executor share of host CPU (10%) and the stream-I/O share of
   executor CPU (30%), and the G2 criterion (non-overlapping ranges over 3 repeats).
3. **H3, building the bridge from the AW gitlink inside the `syn-api` image.** Confirm that this
   satisfies ADR-072 D1, or amend D1.
4. **H4, the canary.** Approve the cohort predicate on the hot claim, with `hold` = 120 s, or accept
   a ceiling-only canary with uncontrolled share.
5. **H5, AW bridge internals.** A long-lived per-executor daemon (recommended: a per-operation
   subprocess re-adds a process per run, which is the cost being cut). Also whether exec goes
   through the docker CLI or the Engine API. AW owns both.
6. **H6, timing.** P0 (#1894, the role split and drain route, the 7b image, #1908) lands before
   PR 1's measurement can run.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1: the operation seam is a byte transport, not a normalization boundary; there is no bridge | **Accepted.** The syn side is verified: `EventStreamPort.stream` yields `str` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:198-210`), and the Python processors are selected at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:401-449`. The AW-side claims could not be re-read at the pin and are taken from the review | The scope is narrowed: R1 moves I/O only, and decode and parse stay in Python (§2.2). R2 is a specified, unscheduled `HarnessFact` contract that keeps domain judgments (cost limit, push observer, attribution) in Python (§2.3). AW PRs 2-3 are added for the bridge protocol and binary: bounded pages, the credential callback, owner-loss cancel, typed failures. H5 now carries a recommendation |
| B2: the parity and orphan tests can pass without touching a Rust operation | **Accepted.** Verified: V5 uses `FakeAgentExecutionHandler`, a memory backend and `observability_writer=None` (`apps/syn-api/tests/integration/test_1310_a_claimed_three_phase_run_succeeds_on_real_stores.py:13,221,291,308`) | V5 is kept as a queue test. A new L2 production-path fixture is added: real container, stub agent replaying Claude and Codex, real handler, Lane 2, MinIO. A bridge call ledger replaces the `describe()` check. Ids are canonicalized by correspondence. Lane 2 is compared as full rows. Five mutation checks are added. L3 owner death runs against a real Rust operation with a descendant |
| B3: PR 1 does not instrument the G1/G2 measurements | **Accepted.** Verified: `read_p95_seconds` is the threshold (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:145`) and `ContainerStat` has no timestamp (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:102-106`). `CREATE TABLE IF NOT EXISTS` would not add a column (`packages/syn-adapters/src/syn_adapters/execution_runs/schema.sql:1,21`) | §6 is rewritten: cumulative cgroup CPU, `anon` vs `memory.current`, in-use per executor, intercept and slope, idle baseline, observed list **and** detail p95, 3 repeats with ranges, py-spy attribution, first-claim vs re-claim, idempotent ALTERs with an old-schema test, the export query, and validation tests that fail on a missing metric. Also corrected the plan's own error: `python -m syn_perf.loadtest` already exists (`packages/syn-perf/src/syn_perf/loadtest/__main__.py:1-6`) |
| B4: a capacity ratio is not a canary share | **Accepted.** Verified: the claim picks the oldest eligible run and checks only the claimer's room (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:115-130`). D3's global capacity is "a derived figure for reporting" (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:154-156`), so the "splits global capacity" rejection was unsupported | The capacity-ratio canary is dropped, and rejected alternative (e) is reversed. Added a deterministic admission cohort (`pool` columns), a claim predicate with a `hold` fallback, a realized-share report, and tests for saturated, sparse and pool-down cases. H4 is reframed |
| I1: depend on #1908 rather than re-scheduling the seam | **Accepted** (#1908 read through the review, not re-read here) | #1908 is a P0 prerequisite. The old PR 4 ("operation seam, Python provider") is deleted. L1 reuses #1908's recording tests |
| I2: abbreviated citations; `PINNED_DIGESTS` does not pin a host binary | **Accepted.** Verified: `packages/syn-shared/src/syn_shared/settings/workspace_images.py:598,680` pins images, and `infra/docker/images/syn-api/Dockerfile:31-33,59-61` installs AW Python source | Every citation now uses its repository-root path. The bridge is built from the AW gitlink in a cargo stage of the `syn-api` image, and its identity is the gitlink plus the image digest (§5.1, H3) |
| I3: credential parity misses renewal, lapse and teardown; the line-55 citation is wrong | **Accepted.** Verified: `:55` is `CredentialLapse`, the schedule is at `packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:47-51`, and the injectable clock at `:87-100` | §4.3 adds renewal-during-operation, lapse, keeper cancellation and teardown revocation cases for both providers, driven by the injected clock. The citation is corrected |
| I4: the baseline describes the API process, not the executor | **Accepted.** Verified: `docs/north-star.md:166` is the "API process" row, and D1 keeps projections out of the executor (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:66-70`) | §1 is reworded. Arm A is now explicitly the post-split Python executor. The memory intercept (fixed per process) and slope (per run) are both reported, and arm B is kept |

## Readiness

Blocked on a human decision: H1, whether the owner accepts rescoping phase 2 from a Rust
ExecutionHost to a gated Rust I/O bridge with Python as the sole executor. Execution also waits on
the P0 prerequisites (#1894, the executor role and drain route, the 7b stub image, #1908).

