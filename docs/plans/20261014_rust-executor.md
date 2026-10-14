# Rust ExecutionHost: revised plan (replaces `docs/plans/20261014_rust-executor.md` on PR #1874)

**Baselines.**
- syntropic137 `main` = `1ffef8404`. Every unprefixed `file:line` below was re-read at this commit in this phase.
- agentic-workspace (AW) `main` = `34a4872`. Citations marked **AW** are relative to the AW repository root. They were
  read at that commit by the research and review phases (`git show`, without moving the pin). This phase could not
  re-read them, because the syntropic137 gitlink pins AW at `914129d`, which predates the Rust operations port (AW#60,
  merged as `900d021`).
- #1894 and #1908 are **merged** (2026-10-14). The old plan listed them as open.
- #1921 (the #1310 1.7 schema gate) is **open**.

**This document is the in-place revision of `docs/plans/20261014_rust-executor.md`.** That file exists only on branch
`docs/runtime-research-20261012`. It is not on `main` and was not in this phase's checkout, and this phase had no git
tool. So this text has not been committed yet. See Readiness.

---

## 0. Decision (recorded, not argued)

> **H1, decided by the owner on 2026-10-14.** We move execution away from Python and build the Rust ExecutionHost, as
> briefed. Rust is the host. It calls the Python domain code (aggregates, decisions, Lane 1 and Lane 2 writers)
> through a bridge that Rust owns. The Python domain then moves to Rust one slice at a time behind that seam. The
> same event-stream conformance tests prove each slice. **The measurement experiment runs first. Its numbers order
> the work; they do not decide whether the work happens.**

The previous version recommended "Python stays the executor" (boundary (c)) and rejected options (a), (b) and (d).
That recommendation is withdrawn. Its reasoning survives only where it names a real risk, in §8, and each such risk
has a mitigation. Old option (d), a Rust claim loop supervising Python workers, is now Stage A of this plan. It is a
waypoint, not the destination.

## 1. Where we start

One Python process serves the API and also runs every execution. `start_execution_host` constructs `ExecutionHost`
inside the API process (`apps/syn-api/src/syn_api/services/execution_host_runner.py:70`, `:89`; stop at `:104`).

| Piece | Where | What it does |
|---|---|---|
| Claim loop | `packages/syn-adapters/src/syn_adapters/execution_host/host.py:57` | Each turn heartbeats, sweeps `opening`, reconciles, then claims while it has room (`:113-127`). Sleeps `loop_interval` between turns (`:97`) |
| Timing | `packages/syn-adapters/src/syn_adapters/execution_host/host.py:44-54` | Loop 5 s; lease TTL 90 s; opening sweep 2 min; renew every TTL/3 |
| Per-run drive | `packages/syn-adapters/src/syn_adapters/execution_host/host.py:134-156` | Drain task plus `LeaseKeeper`. A drain that escapes with an exception leaves the row `claimed` for its lease to expire (`:144-148`). Close happens under the token (`:154`) |
| Shutdown | `packages/syn-adapters/src/syn_adapters/execution_host/host.py:86-105` | Cancels held runs (each takes the #1381 interruption path), awaits them, and leaves the rows for their leases |
| Lease keeper | `packages/syn-adapters/src/syn_adapters/execution_host/lease.py:32-46` | Renews while the drain task is alive. **Liveness is "task not done", not output progress** |
| Reconciler | `packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:1-7`, `:44-72` | An expired claim is never re-run. It goes fence, then reap, then interrupt through the aggregate, then close |
| Seams | `packages/syn-adapters/src/syn_adapters/execution_host/ports.py:16-22` (`ClaimedRunDrainer`), `:25-34` (`DeadHostReaper`), `:37-44` (`RunInterrupter`) | Protocols |
| Queue SQL | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py` | register `:49`, heartbeat `:74`, reserve `:104`, claim `:120-161` (epoch predicate `writer_epoch<=$2` at `:142`), renew `:163`, fence `:196-209` (epoch `:203`), takeover `:211-231` (epoch `:219`), close_interrupted `:246`, budget handover `:287-320` |
| Drainer | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:470-512` | `run_claimed`: folds this run's to-dos from its stream (`:490`), reloads the aggregate (`:496`), drains |
| To-do loop | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:620-698` | Four dispatch branches. The enum has a fifth action, `COMPLETE_EXECUTION` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/TodoValueObjects.py:23-27`). Terminal completion, failure and cancel run **outside** the loop (`WorkflowExecutionProcessor.py:545-594`, `:700-715`) |
| Journal | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/execution_journal.py:105-126` | `EventsNotRecordedError` means the write is not durable only when caused by a concurrency conflict, and unknown otherwise. Any other exception means the events are durable |
| Execution repository | `packages/syn-adapters/src/syn_adapters/storage/repositories.py:189-203`; `save` at `:98-102` | Delegates straight to the SDK. **There is no append-side epoch raise** |
| Epoch | `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:13` (`= 1`); `:5-6` says the fitness function and the append-side check are not built | Only the claim/fence predicates enforce it today |
| Stream (after #1908) | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:151-160` (`OperationHost`), `:242` `bind_launch`, `:260` `start`, `:270` `status`, `:278` `cancel`, `:288-303` bounded `observe` with gap recording (`_PAGE_BYTES` `:61`) | Already on AW's operation contract (Python twin) |
| Lane 2 writer | `apps/syn-api/src/syn_api/_wiring.py:304` | `observability_writer=event_store` |
| Container identity | `packages/syn-adapters/src/syn_adapters/workspace_backends/host_labels.py:38-44` | `syn.host_id` = `SYN_HOST_ID` (or hostname) plus a **per-process** random suffix when the run queue is on |

The AW Rust side already exists on AW `main` but is not pinned here:
- **AW** `crates/workspace-core/src/operations/mod.rs:42-84` (`SupportsOperations`: describe, start (idempotent per
  `(workspace, operation_key)` with an equal spec), status, observe (one bounded page), cancel, finalize). Its module
  docs say it does not widen `WorkspaceProvider` (**AW** `crates/workspace-core/src/operations/mod.rs:3`).
- **AW** `crates/workspace-core/src/operations/mod.rs:32-37` (`CredentialResolver`).
- **AW** `crates/workspace-core/src/lib.rs:365` (`WorkspaceProvider`: provision, hydrate, collect, destroy).
- **AW** `crates/workspace-core/src/operations/contract.rs:1,8-10,566`: the APSS EXP-V1-0006 0.2.0 serde models, a
  twin of the Python models on shared fixtures, plus the 0.2.1 `lost` flag.
- **AW** `implementations/docker/src/operations.rs:686` (`DockerOperations`) and `:1014` (the impl). It spawns one
  `docker` CLI child per operation (`:834-840`) and enforces same-key spec equality (`:1070`). **Its operation
  records are in memory** (`:694`, `:716`), so re-attach works only while the provider instance lives.

There is no Rust code in syntropic137 today, no PyO3 anywhere, and no AW bridge daemon.

---

## 2. The experiment: PR 1, first, before any host or bridge code

**Why new tooling is needed.** `ContainerRoles` has `api`, `postgres`, `event_store` and `socket_proxy` and **no
executor** (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:110-116`). The load test samples `docker stats` per
container (`packages/syn-perf/src/syn_perf/loadtest/driver.py:404-421`). The executor runs inside the API process, so
today nothing can separate executor CPU from API CPU.

**Method.**
- Run the existing scripted-agent load test at N = 20 and N = 50, and at N = 100 if the box has the cores.
- During the run, `py-spy record --idle=false --format raw` samples the `all`-role process.
- A pure bucketing module in `packages/syn-perf/src/syn_perf/loadtest/` folds every stack into exactly one bucket.
  The deepest matching repository-root path wins. It is written in the same "pure judge over observations" style as
  `packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:1-18`.

| Bucket | Paths (repository root) |
|---|---|
| host-loop | `packages/syn-adapters/src/syn_adapters/execution_host/`, `packages/syn-adapters/src/syn_adapters/execution_runs/` |
| stream | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py`, the `agentic_isolation` package |
| harness-parse | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/EventStreamProcessor.py`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/CodexStreamProcessor.py` and the parser/accumulator modules beside them |
| lane2-write | `packages/syn-adapters/src/syn_adapters/events/` |
| lane1-decide-append | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/execution_journal.py`, the ESP Python SDK |
| workspace-io | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_workspace.py`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/` (provision and collect) |
| credentials | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/credentials.py` |
| api | `apps/syn-api/src/syn_api/routes/`, the projection coordinator, the pollers |
| other | everything else |

The run also records:
- CPU-seconds per execution-minute (all buckets except `api`);
- the RSS slope against active executions, in MB per concurrent execution, because #1552 was an OOM.

**Validity bars.** A run that fails any one of these is reported as **not evidence**:
1. The existing `concurrency` check passes. It requires both the peak and the sustained concurrency
   (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:297-305`); otherwise it was a queue test.
2. The profiler actually collected samples, and its output parsed. A missing or empty profile fails the run by name,
   in the same way `container_stats` fails (`packages/syn-perf/src/syn_perf/loadtest/pass_bar.py:387-389`).
3. `other` is under 10% of the non-`api` samples.
4. Two runs at the same N agree on every bucket's share within ±5 percentage points.

**Pass and fail, and what each changes.** Stage A always comes first, because Stage A *is* the host. The outcome
reorders only C1–C3 and D (§5). The rules are applied **in this precedence order**, and the first one that matches
sets the order. That makes overlapping thresholds deterministic.

| # | Observation (share of non-`api` CPU at the largest valid N) | Resulting order after A → B |
|---|---|---|
| 1 | RSS slope × 1,000 exceeds the executor host's RAM | Memory binds. Add a per-run memory budget to Stage A's acceptance. **Then also apply the first matching rule from 2–5** |
| 2 | stream + harness-parse + lane2-write ≥ 40% | C1 → C2 → C3 → D |
| 3 | workspace-io ≥ 30% | C2 → C1 → C3 → D |
| 4 | lane1-decide-append ≥ 25% | C1 → D → C2 → C3 (D still needs every prerequisite in §6) |
| 5 | none of the above | Default: C1 → C2 → C3 → D |
|, | Two attempts are both invalid | Use the default order. **The two invalid reports, with their failure reasons, are the PR 1 deliverable.** Re-measure in PR 6, where the Rust host has its own container and `docker stats` separates it |

**No outcome stops the program.** The thresholds above are defaults the owner may change. They are not an approval
gate.

**Acceptance for PR 1 (V1).**
- A unit test feeds one **captured** stack per bucket (fixtures recorded from a real run, not hand-written) and
  asserts the bucket for each.
- A second unit test asserts that **every path in the bucket map exists in the checkout**. A module rename then fails
  the test instead of silently moving CPU into `other`.
- A third asserts that an unknown module lands in `other`, and that a report with `other` ≥ 10% is marked invalid.
- The merged PR includes the report: either the valid numbers, or the two invalid attempts.

---

## 3. The Rust host: responsibilities

**Packaging.** The host is a new crate, `crates/syn-executor/`, and the repository's first Rust crate. It ships as a
second binary in the **same** `syn-api` image, so it keeps ADR-072 D1 (two roles, one image:
`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:61-74`). It runs in the `executor` role. The role
split (`SYN_PROCESS_ROLE`) is not built yet. It is a prerequisite (§7, P1).

| Responsibility | Contract it keeps | Proven by |
|---|---|---|
| Register, deregister, budget handover | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:49-72`, `:287-320` (D3: capacity never doubles across a restart) | V2 |
| Heartbeat, honouring `draining` | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:74-84`; `packages/syn-adapters/src/syn_adapters/execution_host/host.py:113-127` | V2 |
| Claim (capacity + epoch in one transaction) | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:120-161`. **The same SQL text, loaded from shared `.sql` files**, never re-typed in Rust | V2, V5 |
| Lease renewal every TTL/3 and self-fence on loss | `packages/syn-adapters/src/syn_adapters/execution_host/host.py:44-54`, `packages/syn-adapters/src/syn_adapters/execution_host/lease.py:32-46`. Renewal is bound to **worker liveness for that run's lease token** (§4.4), not to agent output | V2, V6a, V6b |
| Drain: stop claiming and wait | `packages/syn-adapters/src/syn_adapters/execution_host/host.py:82-105` | V2 |
| Reconcile: fence, reap, interrupt, close | `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:196-247`; `packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:44-72`. The interrupt is a domain decision and goes over the bridge (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:37-44`) | V2 |
| Shutdown | Cancel every held run over the bridge. Python takes the #1381 preserve-and-re-raise path (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:19`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:595-610`). Rows are then left for lease expiry, as `host.py:86-105` does today | V2 |
| Executor identity on containers | Every container created for a run must carry the **host's** registered `syn.host_id`, because the reaper selects by `syn.host_id=<run.executor_id>` (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:28`). Today each Python process draws its own suffix (`packages/syn-adapters/src/syn_adapters/workspace_backends/host_labels.py:33-44`), so workers would label with the wrong id. The host injects its full executor id, and `executor_host_id()` returns it verbatim (code change in PR 3) | V2 reap cases; V6a |
| Operation calls (start, observe, status, cancel, finalize) from Stage C1 | **AW** `crates/workspace-core/src/operations/mod.rs:42-84` and `:32-37`; the APSS EXP-V1-0006 0.2.x contract per **AW** `crates/workspace-core/src/operations/contract.rs:1,8-10,566`; Docker via **AW** `implementations/docker/src/operations.rs:686,1014`. The host **links** these crates and never reimplements them | AW LH-1..LH-7 conformance; V7 |
| Workspace lifecycle (provision, collect, destroy) from Stage C2 | **AW** `crates/workspace-core/src/lib.rs:365` (`WorkspaceProvider`), a **separate port** from operations (**AW** `crates/workspace-core/src/operations/mod.rs:3`) | V8 |

**Operation keys** are derived deterministically from `(execution_id, phase_id, attempt)`. Same-key starts with an
equal spec return the existing operation (**AW** `implementations/docker/src/operations.rs:1070`). This lets a host
that still holds its provider re-attach to a live agent. It does **not** survive a host restart: provider records
are in memory (**AW** `implementations/docker/src/operations.rs:694,716`). After a host crash, runs are interrupted
and never re-attached, exactly as today.

**Out of the host, permanently:** harness stream and transcript parsing. Under "Where does this change belong?",
that is AW work, behind AW's `HarnessTranscript` / `TranscriptExtractionResult` normalisers.

---

## 4. The bridge

### 4.1 Recommendation: IPC to supervised Python decision workers

- The Rust host spawns a small, fixed pool of Python **decision workers** as child processes in the executor
  container. They die with the host (parent-death signal on the process group).
- They speak gRPC over a Unix-domain socket. One `.proto` file generates both sides' types. gRPC is already the
  event-store wire protocol in both languages (`lib/event-sourcing-platform/event-sourcing/python/pyproject.toml:29-30`).
- Workers live in the executor's failure domain, never the API's. This keeps ADR-072's consequence that "an API OOM
  no longer takes executions with it" (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:634-635`).
- **Run affinity:** a run is pinned to one worker for its whole life. That worker holds the aggregate, the
  run-scoped fold, the `PhaseRuntime`, and the in-memory result lists that today's `_drain` keeps
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:530-532`).

**Why not PyO3 embedding:**
- A Python fault or OOM kills the host and every run it holds. With IPC, the blast radius is one worker's runs.
- The GIL caps decisions at one core per host, which would make 1,000 concurrent executions depend on Python
  free-threading.
- `run_claimed` is `async`. Driving it from tokio needs a pyo3 asyncio bridge with no prior art here.

**What would reverse the choice:** the PR 4 spike (V4) shows IPC round-trip p99 above the bar at N = 100, and
batching does not fix it.

### 4.2 Interface by stage (each stage deletes the previous surface)

- **Stage A (coarse):** `RunClaimed(claimed, lease_token) -> stream<Liveness> then Result`, plus
  `Cancel(execution_id)` and `Interrupt(fenced_run)`. This is exactly `ClaimedRunDrainer` and `RunInterrupter`
  (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:16-22,37-44`). Python still does all I/O through
  the Python AW provider. **The host owns claim, lease, drain and reconcile; Python owns the run.**

- **Stage B (loop inverted, infrastructure still Python):** the host runs the to-do loop that is today
  `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py:620-650`.
  The bridge becomes:
  - `Open(claimed) -> Opened | NoStream`. The worker builds the fold, reloads the aggregate and reads the start pins
    (`WorkflowExecutionProcessor.py:487-512`).
  - `Next(execution_id) -> TodoItem | Empty`.
  - `Act(execution_id, TodoItem) -> Continue | Terminal(result)`. **The worker executes today's dispatch branch for
    that item, unchanged**: provision with session lifecycle and prompt/command build
    (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_workspace.py:167-216`),
    run agent (`WorkflowExecutionProcessor.py:766-778`), collect, and complete phase (`WorkflowExecutionProcessor.py:673-698`).
    An exception inside `Act` takes today's `_fail_execution` path in the worker (`WorkflowExecutionProcessor.py:574-594`),
    which returns `Terminal`.
  - `Finish(execution_id) -> Terminal(result)` when `Next` is `Empty`. It runs today's completion or
    cancel-and-release path (`WorkflowExecutionProcessor.py:545-573`, `:700-715`).
  - `Cancel` and `Interrupt` as in Stage A.

  Stage B removes `RunClaimed` only because `Open`/`Act`/`Finish` cover every capability it had, including the
  terminal paths. No capability is dropped. The host holds **no** business logic. It loops `Next` → `Act` until
  `Terminal`, which is the "processor reads the to-do list and dispatches" role in CLAUDE.md.

- **Stage C (infrastructure moves to the host, one `Act` branch at a time):** each C slice replaces the Python body
  of one action with host-side code. The worker keeps only the domain part:
  - **C1:** the host owns the operation (start, observe, cursor, cancel) through Rust `SupportsOperations`. Python
    supplies a typed `LaunchSpec` (environment, command, fallback) from `PrepareLaunch(execution_id, phase_id)`, and
    observed pages go back to Python's harness processor
    (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:401`)
    until AW ships Rust harness normalisers.
  - **C2:** the host provisions and collects through Rust `WorkspaceProvider` (**AW** `crates/workspace-core/src/lib.rs:365`).
    Python's `Decide(ProvisionCompleted | ArtifactsCollected)` appends the domain events.
  - **C3:** the credential keeper (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:47-51`
    schedule kept) and `CredentialResolver`.

  The four-way outcome appears with `Decide`: `Recorded(version)`, `NotRecorded` (conflict cause only), `Unknown`
  (store acknowledgement lost) and `Rejected(domain_error)`. It carries the journal's distinction
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/execution_journal.py:105-126`)
  across the wire. What to do with each variant is decided in Python (reload or fail), not by the host.

- **Stage D:** `Decide` for a command family is implemented in Rust (§6).

**Lane 1 until Stage D:** only Python appends orchestration events. The host never does.

### 4.3 Failure and restart semantics

The rule: **a worker restart is not a run recovery.** The worker holds infrastructure state (workspace handles,
context managers, environment, command, fallback, pre-run starting points) that the stream cannot rebuild:
- `PhaseRuntime.attach_workspace` stores the workspace, environment and command
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_runtime.py:384-389`) before
  the provision event is appended
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_workspace.py:194-216`).
- `launch` indexes those maps directly and raises without them
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_runtime.py:429-445`).
- The starting point can only be read before the agent runs
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_runtime.py:391-401`).

So a lost worker's runs take **today's dead-host path: fence, reap, interrupt, never re-run**
(`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:1-7`).

| Failure | Host behaviour | Why it is safe |
|---|---|---|
| Worker crashes (any stage A–C) | For every run pinned to it: stop renewing (as today, when a drain escapes: `packages/syn-adapters/src/syn_adapters/execution_host/host.py:144-150`), do not re-dispatch, start a fresh worker for **new** claims. The leases expire, and a reconciler (possibly this host) fences, reaps by `(syn.host_id, syn.execution_id)` and interrupts through the aggregate | Same as a process crash today. No second agent launch and no decision on an empty runtime. Output in the workspace is lost only as it is on a crash today |
| Worker hangs (no liveness for that run's token within the deadline) | Stop renewing those runs, SIGKILL the worker, then as above | Prevents a Rust host keeping a lease alive for a dead Python decision (R1) |
| Healthy run with a quiet agent (no output for minutes) | Keep renewing. Liveness is the worker's event loop answering for the token, not agent output | Matches today's renewal, which watches the drain task (`packages/syn-adapters/src/syn_adapters/execution_host/lease.py:32-33`) |
| `Act` or `Decide` returns `Unknown` or `NotRecorded` | Not handled by the host. Python decides, as today (reload or the failure path) | The host holds no business logic |
| Host shutdown (SIGTERM) | `Cancel` every held run. Python runs the #1381 preserve path and re-raises. Rows are left for their leases | Identical to `packages/syn-adapters/src/syn_adapters/execution_host/host.py:86-105` |
| Host crash or executor-container OOM | Workers die with it. Leases expire, and another executor reconciles (ADR-072 D5). The API is untouched | Identical to today, plus API isolation |

**Blast radius.** One worker loss interrupts the runs pinned to that worker: at most `capacity / pool_size` runs.
The pool size is a host setting. PR 4's spike reports the trade-off between pool size and per-worker run count.

**When a worker restart may *resume* instead of interrupt.** Only after the host holds **every** piece of runtime
state for a phase: the workspace handle (C2), the `LaunchSpec`, the credential reference (C3), the operation key and
cursor (C1), and the recorded starting point (moved into a `Decide` result in C2). The ordered PRs list that as an
explicit milestone, "R-resume", with its own crash tests (V9). Until it lands, interrupt is the contract.

### 4.4 Liveness, separately from progress

- Each `RunClaimed`/`Act` call is bound to the run's `lease_token`.
- The worker answers a `Liveness(token)` probe from its event loop every TTL/3. The answer covers awaits on the agent
  and slow store calls.
- The host renews a lease only if the last liveness answer for that token is younger than the deadline (default
  TTL/3 × 2).
- A probe for a stale token (a fenced and re-claimed run) is answered `Unknown token`, and the host stops renewing.

---

## 5. Which slices move, in what order

| Stage | What moves to Rust | Domain change |
|---|---|---|
| A | Claim, heartbeat, lease, drain, reconcile, shutdown. The executor role runs the binary | None |
| B | The to-do loop (`Next`/`Act`/`Finish`) | None. The Python branches run unchanged inside `Act` |
| C1 | Operation start/observe/cancel and the stream cursor. Later, Lane 2 writes (after the AW Rust harness normaliser contract) | Python keeps parsing until then |
| C2 | Workspace provision, collect, destroy via `WorkspaceProvider`; starting-point read | `Decide` events only |
| C3 | Credential keeper and resolver | None |
| R-resume | Worker restart resumes instead of interrupting | Crash tests (V9) |
| D | `WorkflowExecutionAggregate` decisions and fold, one command family at a time, shadow first (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/WorkflowExecutionAggregate.py`, commands `:480-806`, applies `:807-1022`) | Rust appends Lane 1 |

A and B are fixed first. PR 1's outcome orders C1–C3 and D (§2). R-resume follows the last of C1–C3.

---

## 6. Event compatibility (#1310 1.7) once a Rust slice writes Lane 1

Stage D may not start until all of the following hold:

1. **#1921 is merged.** It provides the write-once
   `ci/fitness/event_sourcing/snapshots/orchestration_events.epoch-N.json` snapshot of every orchestration `@event`'s
   type, version and Pydantic validation schema; the snapshot fitness test (V13 in #1310); and
   `just check-event-compat` (V9 in #1310). None of these is on `main` today.
2. **The append-side epoch guard exists.** ADR-072 D9 requires it on **every** append, because the API appends to
   executions it did not admit (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:486-497`). The ADR
   specifies the raise and the 409 (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:516-528`). It is
   **not implemented**:
   - `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:5-6` says so;
   - `RepositoryAdapter.save` delegates straight to the SDK (`packages/syn-adapters/src/syn_adapters/storage/repositories.py:98-102`).

   The ADR's citation of `packages/syn-adapters/src/syn_adapters/storage/repositories.py:182`
   (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:562`) now points at the `WorkflowTemplate`
   repository, not at an execution write gate. PR P2 builds the guard in the execution repository path
   (`packages/syn-adapters/src/syn_adapters/storage/repositories.py:189-203`) for all writers: the executor journal
   and the API's eval, tag, resume and reconciliation routes. It is tested with mixed-epoch appends in every row
   state of the table, including a race against a claim. **The Rust SDK writer in Stage D calls the same guard SQL
   (from the shared `.sql` directory) before it appends.**
3. **The Rust side:** a test serializes every Rust event type's fixtures and validates them against the current
   epoch's snapshot schema.
4. **The Python side:** #1921's probe is extended to parse a corpus of **Rust-written** payloads with the current and
   the previous `syn-domain`. This closes research Q3: aliases and datetime format are not captured by a validation
   schema alone.
5. **One epoch:**
   - while Python decides, the host registers the epoch its workers report at startup;
   - once Rust folds a stream, a fitness test fails if the Rust constant differs from
     `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:13`.
6. **Differential conformance** for every moved command family:
   - the same stream prefix, the same command, and injected ids and clock must give byte-equal canonical events from
     Python `Decide` and Rust `Decide`;
   - the corpus is #1921's nine lifecycle fixtures plus streams recorded from the `apps/syn-api/tests/integration/test_1310_*.py` runs.
7. **Shadow before cutover:** for one release, Rust `Decide` runs beside Python's. Python's result is appended.
   Divergences are counted, and cutover needs zero over the agreed volume.

The Rust append uses the ESP Rust SDK's distinct conflict variant
(`lib/event-sourcing-platform/event-sourcing/rust/src/error.rs:31`) and its idempotency key
(`lib/event-sourcing-platform/event-sourcing/rust/src/repository.rs:5-32`). That SDK is labelled Alpha in ESP. Any
gap found there is fixed in the submodule, not worked around.

---

## 7. Ordered PRs

**Nothing in the host and bridge track opens before PR 1 has merged with its report.**

| # | PR | Depends on | Repo |
|---|---|---|---|
| 1 | **Experiment.** Profiler bucketing module, the report section in `syn-perf`, runs at N = 20 and 50 (and 100); report merged with the PR. V1 | none | syn |
| P1 | ADR-072 D1 role split (`SYN_PROCESS_ROLE`, `executor` service in compose) and the drain route. Neither exists on `main`. Bump the AW gitlink `914129d` → ≥ `34a4872`. That also moves the Python twin to contract 0.2.x, so syn's suite must pass on it | 1 | syn |
| P2 | Append-side epoch guard for all execution writers, with mixed-epoch and race tests (§6.2). If #1310 already tracks it, this plan depends on that item instead of duplicating it | 1 | syn |
| 2 | Bridge contract: `.proto`, generated Python and Rust types, a Python decision worker serving the Stage A RPCs over the existing `run_claimed`, `Liveness(token)`. Bridge vocabulary (decision worker, Act, Liveness) added to `docs/architecture/orchestration-ubiquitous-language.md`. V3 | 1, P1 | syn |
| 3 | Executor identity injection: `executor_host_id()` returns a host-provided id verbatim (`packages/syn-adapters/src/syn_adapters/workspace_backends/host_labels.py:38-44`) | 1 | syn |
| 4 | Bridge spike (IPC vs PyO3, worker pool size) against the V4 bar. The outcome is recorded in this document | 2 | syn |
| 5 | **Stage A host.** `crates/syn-executor/`; queue SQL moved to shared `.sql` files loaded by both implementations; claim, lease, drain, reconcile, shutdown; the `executor` role runs the binary; `ContainerRoles` gains `executor`. V2, V5, V6a, V6b | P1, 2, 3, 4 | syn |
| 6 | Bounded-concurrency canary: one Rust executor beside Python executors on one queue. Its capacity caps its **concurrency**. It does not set a traffic share, because every host claims the oldest eligible work while it has room (`packages/syn-adapters/src/syn_adapters/execution_host/host.py:120`, `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:139-143`). Record the actual workload mix each host took | 5 | syn |
| 7 | Re-measure with PR 1's tooling and per-container stats. Confirm or change the C order | 5 | syn |
| 8 | **Stage B.** `Open`/`Next`/`Act`/`Finish`; delete `RunClaimed` in the same PR. V3 extended to every action and terminal path | 5 | syn |
| 9.x | C1, C2, C3 in the order fixed by PR 7. C1's Lane 2 half needs an AW contract PR first (Rust harness normalisers). V7, V8 | 8 | AW + syn |
| 10 | R-resume: worker restart resumes runs whose state the host holds. V9 | last of 9.x | syn |
| 11.x | Stage D per command family: conformance, then shadow, then cutover | 8, P2, #1921 | syn |
|, | CI: a cargo job and its `scripts/check_ci_parity.py` mapping. **Delivered as a patch** in the PR 5 workspace's `artifacts/output/`, because workspace credentials cannot push `.github/workflows/`; the owner pushes it | 5 | owner |

---

## 8. H2–H6 under this direction, and risks kept from the rejected rescope

- **H2 (G1 thresholds as go/no-go): dropped.** The owner's caveat makes it moot. The thresholds survive only as the
  ordering rules in §2.
- **H3 (bridge built from the AW gitlink inside the `syn-api` image): reshaped and still open.** No AW bridge binary
  is built. The question is now whether the `syn-api` image gains a cargo build stage for `syn-executor`. Yes keeps
  ADR-072 D1; a separate image would amend D1.
- **H4 (canary cohort predicate on the hot claim): dropped.** Each host's own budget row already bounds its
  concurrency (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:125-160`). The canary is described as
  bounded-concurrency, not a traffic share (PR 6).
- **H5 (AW bridge daemon; CLI vs Engine API): daemon half dropped.** The host links the crates in process. The
  CLI-per-operation spawn (**AW** `implementations/docker/src/operations.rs:834-840`) becomes an AW performance
  follow-up, filed only if PR 7 shows process spawn in a hot bucket.
- **H6 (P0 timing): reduced to P1 and P2.** #1894 and #1908 are merged.

| Old argument | Real risk | Mitigation |
|---|---|---|
| (a) porting aggregates means two implementations | The API still appends through the Python aggregate (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:486-490`), so the Python and Rust folds must agree during D | Differential conformance and shadow (§6); D comes last |
| (b) a thin Python command API | Hosted in the API, it re-couples executions to API uptime | Workers are host children in the executor container (§4.1) |
| (a)/(b) a second serializer of orchestration events | A differently built writer is what D9 guards against, and the guard is not built | Python is the only Lane 1 writer until D; P2 builds the guard; #1921 plus the Rust-payload probe |
| (d) a supervisor adds a process boundary | Lease renewal decoupled from the work it protects, and worker state lost across that boundary | Token-bound liveness (§4.4); worker loss takes the interrupt path, never a re-run (§4.3) |

## 9. Risks

| # | Risk | Signal |
|---|---|---|
| R1 | The host renews a lease for a hung worker's run | V6a fails. In production: a run with no liveness answer past the deadline (host metric) |
| R2 | A restart re-runs an agent | Two starts for one `(execution, phase, attempt)` operation key; duplicate `PhaseCommitPushed` |
| R3 | Rust and Python queue SQL diverge | V5 fails |
| R4 | A Rust-written event is unreadable by Python | §6.4 probe fails; validation errors on reload |
| R5 | The folds disagree during D | Shadow divergence > 0 |
| R6 | IPC overhead erases the gain | PR 7 CPU per execution-minute (host plus workers) > PR 1 baseline + 10% at N = 20 |
| R7 | Image build time and size grow with a cargo stage | Reported in PR 5 |
| R8 | AW crates are pinned at an unreviewed `main` commit | Owner decision below |
| R9 | Containers are labelled with a worker id, not the host id, so a reap misses them | V2 reap cases fail; orphaned containers after a worker kill |

**Standing cost:**
- From PR 5 on, the repository carries two languages, one `.proto` file and one shared SQL directory.
- During D it carries **two implementations of the execution aggregate**, held together only by conformance and the
  shadow counter. That ends only when the API's own appends also move to Rust, which is outside this plan.

## 10. Verification

- **V0 (this revision):**
  - `docs/plans/20261014_rust-executor.md` no longer contains "Python stays the only implementation" or
    "no Rust ExecutionHost";
  - it contains "decided by the owner";
  - every `file:line` resolves at `1ffef8404` (syn) or `34a4872` (AW);
  - the diff against `main` touches only that file.
- **V1 (PR 1):** §2 acceptance.
- **V2 (PR 5):** convert behaviours and host launch sites, not just a file count.
  - **Launch sites:** the subprocess executor `apps/syn-api/tests/integration/_1310_executor_process.py:155`, and the
    in-process host builder in
    `apps/syn-api/tests/integration/test_1310_execution_host_claims_fences_and_reconciles_on_real_stores.py:98`, which
    its budget, completion and expiry cases construct directly. Both must be parameterised to launch either the
    Python host or `syn-executor` (the production binary), plus a mixed Python and Rust peer pair.
  - **Behaviours covered:** budget and capacity handover, completion and close, drain, fencing by a live peer
    (`apps/syn-api/tests/integration/test_1310_v12_a_stalled_executor_is_fenced_by_a_live_one.py`), killed-executor
    reap (`apps/syn-api/tests/integration/test_1310_v7_a_killed_executor_is_reaped_by_a_live_one.py`), and
    reconciliation resume (`apps/syn-api/tests/integration/test_1310_reconciliation_resumes_from_the_row_on_real_stores.py`).
  - **New epoch-negative cases.** Every existing test registers with the current epoch
    (for example `apps/syn-api/tests/integration/test_1310_v12_a_stalled_executor_is_fenced_by_a_live_one.py:147`).
    Add a future-epoch `admitted` row that must not be claimed, and a future-epoch expired `claimed` row that must not
    be fenced or taken over (`packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:142,203,219`).
  - **Mutation check:** removing the epoch predicate from the shared SQL fails those cases.
- **V3 (PR 2, PR 8):** a contract test drives every RPC and every response variant against the Python worker. This
  includes `Terminal` from completion, failure and cancel. `NotRecorded` must appear only for a conflict cause, and a
  store timeout must give `Unknown`. Collapsing the variants fails the test.
- **V4 (PR 4):** 100 concurrent runs × `Act`/`Decide`. Proposed bar: p99 round-trip < 5 ms, and host plus worker CPU
  within 10% of in-process.
- **V5 (PR 5):** a fitness test asserts that no inline queue SQL remains in
  `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py` or `crates/syn-executor/`, and that both load the
  same files.
- **V6a (PR 5):** SIGSTOP a worker. `leased_until` stops advancing, and a peer fences the run within TTL plus one loop
  interval.
- **V6b (PR 5):** a scripted agent silent for more than 2 × TTL keeps its lease and completes.
- **V6c (PR 5):** SIGKILL a worker at three points:
  - after the provision event is durable and before RUN_AGENT;
  - during observation;
  - after agent completion and before collection.

  Each must end `interrupted` through the reconciler, with the workspace reaped by host id and no second agent
  launch for that operation key.
- **V7 (PR 9, C1):** replaying a recorded stream through Rust observe gives the same pages, gaps and `agent_events`
  rows as the Python path.
- **V8 (PR 9, C2):** provision and collect through Rust `WorkspaceProvider` give the same `WorkspaceProvisionedForPhase`
  and `ArtifactsCollectedForPhase` events (differential, ids injected).
- **V9 (PR 10):** V6c's three crash points re-run with the expectation reversed: the run **resumes**, with exactly one
  agent operation per key and the output preserved.
- **V10 (PR 11.x):** §6.3–6.7.
- **Gates for each code PR:** `just preflight-agent` and `uv run pytest -m unit -q` in workspaces; `just qa-ci`
  locally for anything that touches cargo, because `preflight-agent` cannot run cargo.

## 11. Out of scope

- Source changes in this revision (docs only).
- Moving the API, its routes or its appends to Rust.
- Rust harness normalisers (AW's own contract PR).
- The Docker CLI vs Engine API choice inside AW.
- Bumping the APSS gitlink. The host consumes AW's vendored contract (**AW** `crates/workspace-core/src/operations/contract.rs:8-10`).
- Re-arguing H1.

## 12. Needs a human decision

1. **H3, reshaped:** may the `syn-api` image gain a cargo build stage for `syn-executor`? Needed before PR 5.
2. **The AW crate source:** is a reviewed AW `main` commit acceptable as a crate source, or must it come from AW
   `release`? Needed before P1's gitlink bump. CLAUDE.md treats `main` as `:edge`, which is unreviewed for images.
3. **Defaults the owner may override:** the ordering thresholds (40/30/25%, RSS rule), the V4 bridge bar, the liveness
   deadline, and the shadow volume for a Stage D cutover. These are not gates. PR 1 runs with the defaults if the
   owner says nothing.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1: worker restart ≠ aggregate reload | **Accepted.** Verified: runtime state is attached before the provision append (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_workspace.py:194-216`), `launch` indexes it directly (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_runtime.py:429-445`), and the reconciler interrupts rather than re-runs (`packages/syn-adapters/src/syn_adapters/execution_host/reconciler.py:1-7`) | §4.3 rewritten: worker loss takes the fence, reap, interrupt path and is never re-run. "R-resume" became an explicit later milestone (PR 10) that lists the state the host must hold. Added crash tests V6c (interrupt, no second launch) and V9 (resume). Operation-key re-attach limited to a live provider (**AW** `implementations/docker/src/operations.rs:694,716`) |
| B2: Stage B deletes `RunClaimed` before replacing its capabilities | **Accepted.** Verified: `TodoItem` holds only ids (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/TodoValueObjects.py:30-42`); terminal paths sit outside the loop (`WorkflowExecutionProcessor.py:545-594`, `:700-715`); `SupportsOperations` does not widen `WorkspaceProvider` (**AW** `crates/workspace-core/src/operations/mod.rs:3`) | Stage B is now `Open`/`Next`/`Act`/`Finish`, with Python running each existing branch and the terminal paths unchanged. Infrastructure moves per action in Stage C. C2 uses `WorkspaceProvider` (**AW** `crates/workspace-core/src/lib.rs:365`), separately from operations. V3 covers terminal variants |
| B3: append-side epoch guard described as present | **Accepted.** Verified: `packages/syn-adapters/src/syn_adapters/storage/repositories.py:182` is in `get_workflow_repository` (WorkflowTemplate); the execution `save` at `:98-102` has no raise; `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/event_epoch.py:5-6` says it is not built | Removed every "the raise stays in its one place" claim. Added PR P2 (guard for all writers, mixed-epoch and race tests) as a Stage D prerequisite, separate from #1921. Noted the stale citation at `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:562` |
| B4: V2 leaves tests green with Rust broken | **Accepted.** Verified: the in-process builder `apps/syn-api/tests/integration/test_1310_execution_host_claims_fences_and_reconciles_on_real_stores.py:98` bypasses the subprocess helper, and every test registers `ORCHESTRATION_EVENT_EPOCH` (for example `apps/syn-api/tests/integration/test_1310_v12_a_stalled_executor_is_fenced_by_a_live_one.py:147`) | V2 now names the launch sites and behaviours, adds a mixed-peer pair, adds future-epoch claim and fence/takeover negatives, and a mutation check on the epoch predicate |
| B5: PR graph does not require the experiment first | **Accepted** | PR 1 is now the predecessor of every other PR, including the prerequisites. Thresholds have a fixed precedence order. Two invalid attempts and their reasons are the required deliverable before the default order applies. Thresholds are labelled defaults, not a gate |
| I1: capacity is a concurrency ceiling, not a traffic cohort | **Accepted.** Verified: `packages/syn-adapters/src/syn_adapters/execution_host/host.py:120`, `packages/syn-adapters/src/syn_adapters/execution_runs/postgres.py:139-143` | PR 6 renamed to a bounded-concurrency canary, which records the actual workload mix. H4's text was corrected the same way |
| I2: the synthetic bucketing test misses renames | **Accepted** | V1 uses captured stacks, a test that every mapped path exists in the checkout, and a validity bar that the profiler collected and parsed |
| I3: specify liveness separately from progress | **Accepted.** Verified: today's renewal watches only `drain.done()` (`packages/syn-adapters/src/syn_adapters/execution_host/lease.py:32-33`) | New §4.4: token-bound `Liveness` from the worker's event loop. Blast radius per worker stated. Positive quiet-run test V6b added beside the SIGSTOP test V6a |
| I4: citation cleanup; four branches vs five actions | **Accepted** | All paths are written from the repository root, with no ellipses. §1 states four dispatch branches and five enum actions (`COMPLETE_EXECUTION`) |
| (new, found in this phase) worker processes label containers with their own executor id | n/a (own finding) | `packages/syn-adapters/src/syn_adapters/workspace_backends/host_labels.py:33-44` draws a per-process suffix, and the reaper selects by `syn.host_id=<run.executor_id>` (`packages/syn-adapters/src/syn_adapters/execution_host/ports.py:28`). Added an identity row in §3, PR 3, risk R9, and reap assertions in V2 and V6c |

## Readiness

PR 1 (the experiment) is ready to implement now. PR 5 (the Rust host) is blocked on two owner decisions: whether
the `syn-api` image may gain a cargo build stage (H3), and whether AW crates may come from a reviewed AW `main`
commit or must come from AW `release`. **This text is not yet committed to `docs/plans/20261014_rust-executor.md` on
`docs/runtime-research-20261012`:** this phase was granted no git or shell tool, so a follow-up step must commit and
push it.

