# Plan (final): take the orchestrator out of the evidence loop

Owner priority, 2026-10-15. Design plan only: no source changes, no commits. The orchestrator commits this file.
Every claim was checked against `main` @ `366e650b1`. Every path is repo-root, as `git ls-files` prints it.

This revision answers the cross-model review. All five blockers were accepted, and each one changed the design. The changes:

- **Cleanup moves.** `.mutations/` is removed only at the gate in front of the final phase (B1).
- **A gate survives interruption only through a person-started resume.** The resume inherits the open gate (B2).
- **Attempt identity is recorded before any dispatch** (B3).
- **A complete typed transport and a host-side head observation** carry each request to the aggregate (B4).
- **Reports reach the next workspace through the existing injection path, plus a manifest** (B5).

The disposition table is at the end.

---

## 1. Problem

Some SDLC changes need evidence a workspace cannot produce:

- integration tests against real services;
- mutation evidence that drives Docker.

Workspaces have no Docker by design (ADR-021, #568). CI skips integration on PRs into `main` (`.github/workflows/ci.yml:250-254`). The workspace token cannot dispatch workflows: the App's documented permission is `Actions: Read` (`docs/deployment/github-app-setup.md:93`, `:436`), and every phase holds the installation's own permissions (`packages/syn-adapters/src/syn_adapters/github/agent_token.py:3-17`).

So a run that needs that evidence stops short of a ready PR:

- **Under v3** it spends its repair rounds and ends `blocked`.
- **Under v4** it ends as a draft with a `Certified pending orchestrator evidence` comment (`workflows/sdlc/implement-v4-precheck/phases/finalize_pr.md:89-114`).

A person (today, the orchestrator agent) then does the rest by hand:

1. dispatches `ci.yml` or `just mutation-evidence` (`justfile:1229-1261`);
2. watches the run and reads the result;
3. deletes `.mutations/`, which must be gone before merge (`.github/workflows/ci.yml:636-652`);
4. re-checks the head and marks the PR ready.

PC-197 makes this worse. A second mutation dispatch for the same PR cancels the first (`.github/workflows/mutation-evidence.yml:89-92`).

The brief says "about half" of runs end this way. That rate is not verifiable in the repository, so decision 7 measures it before acceptance.

## 2. Facts the design rests on

| Fact | Evidence | Consequence |
|---|---|---|
| A `certified` verdict skips every non-final phase | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/review_rounds.py:136-137` | An "evidence phase" would be skipped in exactly the case it exists for. Evidence goes **on the transition**, not into a phase |
| The aggregate decides the next phase synchronously when artifacts are collected | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/WorkflowExecutionAggregate.py:674-697` | The gate is decided at that point, from replayed state only |
| A verdict reaches the aggregate by explicit copying at each hop | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_verdict.py:307-319` → `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:592-607` → `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py:410-448` → `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/phase_step_events.py:50-69` | Evidence requests need every hop (§A.2) |
| `ArtifactsCollectedCommand` carries ids, a preview and the recovery flag, and nothing about the forge | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py:461-482` | A host-side head observation must be added to it (§A.2) |
| Reviewers check out the exact SHA from the author's artifact and stop if the PR head differs | `workflows/sdlc/implement-v4-precheck/phases/verify.md:58-67`, `:101-102` | No platform commit may land between an author phase and its review (§A.3, B1) |
| A head that still tracks `.mutations/` fails `Mutation Patches Not Merged`, and `CI Success` requires it | `.github/workflows/ci.yml:636-652` | Reviewers must read that red check as expected while cleanup is pending (§A.11) |
| A lease expiry interrupts the execution and clears its to-do list | `packages/syn-adapters/src/syn_adapters/execution_host/interrupter.py:34-53`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execution_todo/projection.py:411-413` | No handler "runs again after restart" (B2) |
| An interrupted run is never re-run elsewhere, and resume is a fork started only by a person | `docs/adrs/ADR-014-workflow-execution-model.md:149-155`, `:369-372`; `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:322-324` | Recovery goes through resume, and the fork inherits the open gate (§A.7) |
| Resume admission inherits completed phases, their artifact ids and the skipped ids | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_rules.py:282-317` | The open gate must be added to what is inherited |
| Next-phase injection resolves only completed phase ids, the in-process cache wins, and `record` **replaces** a phase's files | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:399-413`; `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/processor_types.py:67-74` | Reports are filed under the requesting phase and appended to the cache (§A.6, B5) |
| The alias ranking prefers a primary-flagged artifact, then the earliest one | `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:70-83` | Non-primary reports created later cannot displace a phase's own deliverable |
| Executor capacity is a count (`max_concurrent`) | `apps/syn-api/src/syn_api/services/execution_host_runner.py:98-106` | A waiting gate holds a slot (§A.9, I1) |
| An executor drain waits for that executor's runs | `docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:659-668` | A long gate delays a Phase 1 drain |
| A token can be minted with a permission subset | `packages/syn-adapters/src/syn_adapters/github/client_token.py:265-271` | Workspace tokens can be capped at `actions: read` while the App holds `write` |
| The branch-read port exists and reports the PRs open from a branch | `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/RemoteBranchPort.py:24-34` | The PR number comes from the forge, not from prose |
| A phase's own pushes are recorded as typed events | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/PhaseCommitPushedEvent.py:11-35` | These are the branches to observe for undeclared patches |
| Pipeline observers are best-effort, and are skipped for deduplicated and cold-start-fenced events | `packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py:66-82`, `:91-114`, `:132-139` | Webhooks can only accelerate a wait. The poll is the mechanism (§A.8, I2) |
| Mutation evidence voids a red, empty, skipped or xfailed baseline, and applies every patch with one test selection | `scripts/mutation_evidence.py:609-654` | Requests must be unioned per head (I4). Integration needs the same per-test discipline (I3) |
| The mutation runner refuses a directory with no patches | `scripts/mutation_evidence.py:285-291` | Integration evidence needs its own runner |
| Integration CI runs `pytest -m integration -x -q` | `.github/workflows/ci.yml:288` | That command reports no per-test outcome. The evidence runner will (§A.1) |
| `ci.yml` dispatches get a concurrency group of their own; only PR runs cancel | `.github/workflows/ci.yml:21-23` | Only `mutation-evidence.yml` has the cancel trap |
| "Same pattern as the host-side draft PR (#1197)" | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/errors.py:1325-1327`; `packages/syn-adapters/src/syn_adapters/github/agent_token.py:3-11` | **No such precedent exists.** These are the first host-side GitHub writes made on a phase's behalf, which makes them an ADR decision (§A.13) |

---

## 3. Approach

An **evidence gate** sits on the transition from phase P to the phase the aggregate decided runs next.

**What opens a gate:**

- P declared typed evidence requests in its `TASK_RESULT`; or
- the platform's own head observation found `.mutations/` on a branch this execution pushed.

**What the gate does:**

1. The aggregate records `EvidenceRequested`, carrying the already-computed `NextPhase`, and holds `NextPhaseReady`.
2. One to-do action, `RUN_EVIDENCE_STEP`, drives the steps.
3. A host-side runner dispatches the target repository's evidence workflow with an App token scoped to `actions: write`.
4. It records an attempt identity **before** posting, adopts the run, and waits with a batched host poll.
5. It reads a machine-readable `evidence.json` and settles each step.
6. **Only at the gate in front of the final phase, after a certified review,** it removes `.mutations/` with one compare-and-swap commit S→S′, then runs integration and waits for the required check on S′.
7. Reports and a manifest are filed as artifacts of P. They reach the next workspace at `artifacts/input/<P>/platform-evidence/<gate-id>/` through the existing injection path.

The gate opens on **any** outcome. Evidence is input to the next phase, not a verdict on the execution.

**Two entry points, one mechanism:**

| Entry | Gate sits between | What runs | Cleanup |
|---|---|---|---|
| An author (implement / fix) commits `.mutations/` and declares mutation tests | author → review | mutation (and integration if declared) on the author's head S | **never** here: the reviewer must find the PR head equal to S |
| A certified reviewer declares Docker or database evidence | review → `finalize_pr` | mutation on S if not already passed for S → remove patches S→S′ → integration on S′ → required check on S′ | **only** here |

### A.1 Contracts

**Phase to platform.** `TASK_RESULT` gains an optional key, `evidence`: a list of entries.

```json
{"kind": "mutation",    "repository": "owner/name", "branch": "b", "pr": 123, "head_sha": "<40 hex>", "tests": ["path::id", "..."]}
{"kind": "integration", "repository": "owner/name", "branch": "b", "pr": 123, "head_sha": "<40 hex>", "tests": ["path::id", "..."]}
```

- `kind` is a closed `StrEnum`.
- `tests` is required and non-empty for both kinds (I3). Node ids are validated with the same grammar `scripts/mutation_evidence.py validate` enforces.
- `repository` must be one of the execution's repositories, or the entry settles `void: repository not in this execution`. A phase cannot aim the platform's App token at another repository.
- The parser is `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_verdict.py`. A malformed entry is **not dropped**: it becomes a request that settles `void: unreadable evidence request`. A silent drop would read as "no proof needed".
- `EvidenceRequest` is a Pydantic model (`frozen=True`, `extra="forbid"`).

**Platform to repository.** A kind maps by convention to `.github/workflows/<kind>-evidence.yml` in the **target** repository. That workflow must:

- take `workflow_dispatch` inputs `pr`, `tests` and `dispatch_id`;
- put `dispatch_id` in its `run-name`;
- upload an artifact named `evidence` holding `evidence.json`.

`evidence.json` is schema 1, defined once as a Pydantic model with a generated JSON Schema that both scripts validate against in their tests. Fields:

- `schema`, `kind`, `pr`, `head_sha`, `dispatch_id`;
- `verdict`: `passed | failed | void`;
- `requested[]`: per requested node id, `{id, outcome: passed|failed|skipped|xfail|not_collected}`;
- `suite`: `{collected, passed, failed, skipped}`;
- `summary`, `report_md`.

**Verdict rules.**

- **Mutation:** the existing semantics (`scripts/mutation_evidence.py:609-654`) carry over unchanged. `passed` means every patch was killed.
- **Integration** (I3), written by a new `scripts/integration_evidence.py`. It runs the full `-m integration` suite **without `-x`**, with JUnit XML, so that every outcome is recorded.
  - `failed`: any test failed or errored.
  - `void`: any **requested** id was not collected, or was skipped, xfailed or xpassed.
  - `passed`: otherwise.
  - So `passed` proves: the whole integration suite was green on that SHA, **and** every test the phase named actually executed and passed. Unrelated suite skips are reported in `suite.skipped` but do not void.

**Other repositories.** A repository without the workflow settles `unavailable: workflow_absent` (dispatch 404/422), and that run falls back to today's human handoff.

### A.2 Transport: request and observation into the aggregate (B4)

Each hop is explicit, and each has a test that fails when the hop is removed:

| Hop | Change |
|---|---|
| Parse | `AgentVerdict` gains `reported_evidence: tuple[EvidenceRequest, ...] = ()` beside `reported_review_verdict` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_verdict.py:315-319`). `_ReportedResult` and `_StatusAliasResult` accept `evidence: object \| None` |
| Handler | `AgentExecutionHandler` copies it onto the command (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:592-607`) |
| Command | `AgentExecutionCompletedCommand.reported_evidence` (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py:410-448`) |
| Event | `AgentExecutionCompleted` gains `reported_evidence` (additive, defaults to empty), copied in `agent_completed_event` (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/phase_step_events.py:50-69`) |
| Replayed state | The aggregate keeps the latest run's requests per phase. Like `ReviewRecord._reported`, a retry overwrites them (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/review_rounds.py:76-92`) |
| Observation | During collection (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_workspace.py:390-416`), host-side and **before** `aggregate.artifacts_collected`, an `EvidenceHeadObserver` reads every branch this execution pushed (`PhaseCommitPushed` on its stream, inherited ones included) plus every declared branch. It uses `RemoteBranchPort.read_branch`, plus a new `RemoteTreePort.has_path(repository, sha, ".mutations")`. The clone directory name maps to `owner/name` through the execution's repository slugs, as `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/pull_request_observation.py:61` already does |
| Command | `ArtifactsCollectedCommand` gains `observed_heads: tuple[ObservedHead, ...]`, where `ObservedHead` holds repository, branch, head_sha, readable, mutation_patches_present and open_pr_number (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py:461-482`). The observation is a fact recorded on `ArtifactsCollectedForPhase`. The aggregate does no I/O |

**Identity.**

- `head_sha` and `pr` come from the declaration and are **checked against the observation**. A declared head that is not the forge's head settles `void: head moved`. A declared PR that is not open from that branch settles `void: pr mismatch`.
- No identity is ever parsed from markdown.

**Unreadable forge.**

- With nothing declared, it opens no gate. That is logged, and Lane 2 counts it. `Mutation Patches Not Merged` still guards merge (`.github/workflows/ci.yml:636-652`).
- With something declared, it settles `unavailable: forge_unreadable`.

### A.3 Gate rules (pure module)

The rules live in a new `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/evidence_gate.py`, beside `review_rounds.py`, with the same split: pure functions plus a replayed record.

**When a gate opens.** All four must hold:

- the flag `SYN_EVIDENCE_GATE_ENABLED` is on;
- P is collected;
- `next_phase(...)` returned a `NextPhase`, so a gate never sits after the final phase;
- any one of the following:
  - P declared requests;
  - an observed head carries `.mutations/` without passed mutation evidence for that SHA;
  - the decided next phase is the final phase, P's verdict is `CERTIFIED`, and an observed head carries `.mutations/`.

When a gate opens, the aggregate emits `EvidenceRequested` **instead of** `NextPhaseReady`. The `NextPhase` is computed once and stored on the request. Its skipped ids are added to `ReviewRecord.skipped` at that point (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/review_rounds.py:82-84`). The skip is a decision already taken, and resume reads it from there (§A.7).

**Step planning** happens once, at request time, and is ordered:

1. **Mutation steps, normalized (I4).** All mutation requests for the same `(repository, head_sha)` collapse into **one** step with the sorted union of tests. Undeclared patches with no passed evidence for that head reuse the latest test selection declared earlier in this execution. If nothing was declared, they get one synthetic step that settles `void: patches present, no tests declared`.
2. **Reuse.** A `(kind, repository, head_sha, tests ⊆ settled tests)` that already settled `passed` in this execution, inherited ones included, is not dispatched again. The step settles `passed (reused)` and points at the earlier report.
3. **`remove_mutation_patches`**, only when all three hold:
   - the held next phase is the final phase;
   - P's verdict is `CERTIFIED`;
   - every mutation step for that head is `passed`.

   Otherwise the patches stay, so a person or a resumed fix round can see them (B1).
4. **Integration steps,** on S′ when cleanup is planned and on S otherwise.
5. **`required_check`,** only after cleanup. It waits for the check named by `SYN_EVIDENCE_REQUIRED_CHECK` (default `CI Success`) to conclude on S′. The App-authored push triggers `pull_request: synchronize`. This step is read-only, needs `checks: read`, and lets `finalize_pr` decide without waiting itself.

Steps a person cannot declare (patch removal, the required check) are platform-internal.

**Gate opens** when every step has settled, whatever the outcomes. The final settle emits `EvidenceStepSettled`, then `NextPhaseReady` with the held `next_phase_id` and `skipped_phase_ids`.

### A.4 Lane 1 events and Lane 2 telemetry

Lane 1 events go on the `WorkflowExecution` stream. Each is either needed after an interruption or decides what runs next.

| Event | Carries | Why Lane 1 |
|---|---|---|
| `EvidenceRequested` | gate_id, after_phase_id, held next_phase_id and skipped_phase_ids, ordered steps (index, kind, repository, branch, pr, head_sha, tests) | The decision to hold, and the plan |
| `EvidenceAttemptStarted` | gate_id, step, attempt n, `dispatch_id` (UUID), started_at, `not_after` (absolute step deadline) | Recorded **before** the POST, so any later process knows which nonce to look for (B3) |
| `EvidenceRunAdopted` | gate_id, step, attempt, run_id, run_url | Progress recorded while the run executes (B3) |
| `MutationPatchesRemoved` | gate_id, repository, branch, `before_sha`, `after_sha`, the commit's author | A write we made, and the provenance that keeps evidence about S valid at S′ |
| `EvidenceStepSettled` | gate_id, step, outcome (`passed/failed/void/unavailable`), reason, run_id, head_sha_evidenced, report artifact ids, `manifest_artifact_id` on the last step | The fact that opens the gate |

Reports are artifacts referenced by id, never inlined in an event.

Lane 2 goes to the observability recorder: queue latency from dispatch to start, runner duration, poll calls, rate-limit waits, attempts, and gate-held slot-seconds (§A.9). None of it passes through the aggregate.

### A.5 Handler, ports, and the attempt protocol (B3)

**Plumbing.**

- `TodoAction` gains `RUN_EVIDENCE_STEP`, and `TodoItem` gains `evidence_gate_id` and `evidence_step` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/TodoValueObjects.py:14-42`).
- The projection gains `on_evidence_requested`, which appends step 0, and `on_evidence_step_settled`, which appends the next step or nothing. `on_next_phase_ready` is unchanged (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execution_todo/projection.py:365-397`).
- The processor gains one branch, with zero logic.
- A new handler, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/EvidenceStepHandler.py`, is kept under 200 LOC.

**Ports.** Both go in `packages/syn-domain/src/syn_domain/contexts/orchestration/ports/`. There are two because gathering evidence and writing to a branch carry different trust.

`EvidenceRunner` exposes:

- `dispatch(attempt) -> Accepted(run_id | None) | Refused(reason) | Ambiguous`;
- `find_run(attempt) -> RunRef | None`;
- `await_run(run, not_after) -> RunConclusion`;
- `fetch_report(run) -> EvidenceReport | None`.

`RemoteBranchWriter` exposes `remove_paths(repository, branch, before_sha, paths) -> Removed(after_sha) | Adopted(after_sha) | HeadMoved`.

**The handler reads only the rehydrated aggregate**, never a runner object it held earlier. Every action below is a command, saved before the next side effect:

1. **No attempt yet.** Issue `StartEvidenceAttemptCommand` (n=1, a new `dispatch_id`, `not_after = now + SYN_EVIDENCE_STEP_DEADLINE_SECONDS`), **save**, then `dispatch`.
   - `Accepted` with a run id: `RecordEvidenceRunAdoptedCommand`.
   - `Refused`: settle `unavailable: permission` (403) or `unavailable: workflow_absent` (404/422).
   - `Ambiguous` (timeout, 5xx, 429 after its wait, or a crash after the POST): go to 2. An accepted-but-invisible dispatch is **never** re-POSTed straight away.
2. **Attempt n started, no run recorded.** `find_run` lists the workflow's `workflow_dispatch` runs with `created >= started_at - 2 min` and **paginates until a page predates that bound**. That is bounded by time, not by a count of 20 (`justfile:1241-1243` uses `--limit 20`, I2). Matching is on `dispatch_id` in the run name.
   - Found: adopt it.
   - Not found within `SYN_EVIDENCE_DISPATCH_VISIBILITY_SECONDS` (default 120) of `started_at`: the dispatch is treated as not having happened. Start attempt n+1 if attempts < 2, otherwise settle `unavailable: dispatch_lost`.
   - A run from attempt n that appears late is ignored and costs only runner minutes. Once PC-197 is fixed it cancels nothing.
3. **Run adopted.** `await_run` until `not_after`, then `fetch_report`.
   - A report is present: settle with its verdict. `head_sha` different from the step's settles `void: head moved`. A `passed` report from a run whose job concluded `failure` settles `void: report disagrees with run`.
   - No report and a conclusion of `failure`: an infrastructure failure. Attempt n+1, otherwise `unavailable: runner`.
   - `cancelled`: attempt n+1, otherwise `unavailable: superseded`.
4. **`not_after` passed** at any point: settle `unavailable: timeout`. Retries share the step's `not_after`.
5. **`remove_mutation_patches`.** A compare-and-swap with no pre-event: the result identifies itself. `Removed` or `Adopted` record `MutationPatchesRemoved`, then settle `passed`. `HeadMoved` settles `void: head moved`.

The aggregate guards every command: no attempt for a settled step, no adoption for an attempt that is not current, no settle twice.

### A.6 Delivering reports to the next phase (B5)

- **Filing.** Each settled step's `evidence.json` and `report.md` are stored as artifacts **owned by phase P**, non-primary. Their `source_path` is `artifacts/output/platform-evidence/<gate-id>/<step>-<kind>.{json,md}`. The ranking prefers primary-flagged, then earliest, so they cannot displace P's alias (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:70-83`).
- **The manifest is authoritative.** Before the final settle, the handler writes `manifest.json` for the gate from the **events**, not from `evidence.json`. It lists:
  - every planned step, with outcome, reason, run URL and head SHA;
  - reuse pointers;
  - `MutationPatchesRemoved` provenance (`before_sha`, `after_sha`, author);
  - `complete: true`.

  A step with no report still appears with its recorded outcome, so a missing report can never read as "all passed". Finalize trusts S→S′ only from this manifest.
- **Injection** goes through the existing sink and its path validation (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:437-509`). Files land at `artifacts/input/<P>/platform-evidence/<gate-id>/`, and two gates in one execution never collide. There is no second file writer.
- **Live path.** `PhaseOutputCache` gains `append(phase_id, files)`. `record` replaces (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/processor_types.py:67-74`), and the cache wins over the projection (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:399-413`), so without `append` the reports would be invisible live.
- **Resume path.** The inherited phase P's `artifact_ids` include its settled gates' report and manifest ids. That makes `_files_by_owner` resolve them (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/resume_handoff.py:110-136`), with references attributed to the fork as ADR-014 §7 requires (`docs/adrs/ADR-014-workflow-execution-model.md:185-193`).
- **Artifact store unavailable** at the manifest write: the step settles with `manifest_artifact_id=None` and a reason. Prompts read a missing manifest as "not proven", so the PR stays a draft. This fails closed.

### A.7 Interruption and resume (B2)

Nothing new is automatic. The model stays ADR-014 §7/§9.

**Executor loss during a gate.**

- The lease expires, the reconciler interrupts the execution, and its to-do record is cleared.
- The GitHub run continues and finishes. Its report and marker comment exist, but nobody watches it.
- This is accepted, and the ADR says so.

**A person resumes** (`syn execution resume`). Resume rules (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_rules.py:282-317`) gain one input: the parent's open gate, meaning an `EvidenceRequested` with no `NextPhaseReady` after it.

1. **The resume point** is the held `next_phase_id`. The held skips are already in `ReviewRecord.skipped` (§A.3), so a certified skip survives into the fork.
2. **`ExecutionResumedEvent`** gains `inherited_evidence_gate`. It carries the plan, the settled steps with their report ids, `MutationPatchesRemoved` provenance, and, for each unsettled step, its last attempt (`dispatch_id`, run_id).
3. **The fork's first to-do** is `RUN_EVIDENCE_STEP` for the first unsettled step, not `PROVISION_WORKSPACE`.
   - The handler first tries to **adopt** the parent's attempt by run_id or `dispatch_id`. A completed run with a report is evidence, and is not re-run.
   - Otherwise it starts a fresh attempt with a fresh `not_after`. A person-started resume is a new decision, so it gets a new deadline.
4. **Interruption after cleanup and before integration settled.** The fork inherits the provenance and runs integration on S′. If the removal commit was pushed and its event was lost, the compare-and-swap adopts it.
5. **No acknowledgement needed.** The gate's own external effects are idempotent by recorded attempt identity and by compare-and-swap. Resuming at an unstarted held phase therefore needs no `acknowledge_external_effects` (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/resume_rules.py:290-302`). The ADR states this as a deliberate choice.

**Cancellation** during a gate clears the to-do list. Dispatched runs are left to finish. Cancelling them is a follow-up behind the same port.

### A.8 Adapter: dispatch and waiting (host-side GitHub)

New module: `packages/syn-adapters/src/syn_adapters/github/evidence_runner.py`.

**Token.**

- Minted per call with `installation_token(..., permissions={"actions": "write", "metadata": "read"}, repositories=[repo])` (`packages/syn-adapters/src/syn_adapters/github/client_token.py:265-271`). It never reaches a workspace.
- Only `<kind>-evidence.yml` files can be dispatched, because `kind` is a closed enum. Release workflows are unreachable from this code.

**Waiting (I2): a batched host poll is the mechanism.**

- One watcher task per executor process makes **one paginated list call per (repository, workflow) per tick** for all of its waiters. The interval is `SYN_EVIDENCE_POLL_SECONDS`, default 30.
- That is O(repositories), not O(runs). At 100 waiting runs across 5 repositories and 2 workflows, it is about 1,200 req/h, against the installation's 5,000/h. A per-run poll would be about 12,000/h.
- Re-entry after a fork is ordinary handler re-entry from persisted attempts. No in-memory waiter has to survive.
- This satisfies the brief's "no polling loop in an agent". No agent waits on anything.

**Webhooks are acceleration only, and deferred.**

- `workflow_run` arrives at the API process through `EventPipeline`, while waits live in executor processes (ADR-072 D1).
- Observers are best-effort and do not fire for deduplicated or cold-start-fenced events (`packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py:66-82`, `:132-139`).
- A follow-up may register an observer through `add_observer` that signals executors. It can never replace the poll.

**Outcome mapping.**

| Situation | Settles as |
|---|---|
| Void baseline | `void` from the report |
| Runner flake (no artifact, `failure`) | one retry, then `unavailable: runner` |
| `cancelled` | one retry, then `unavailable: superseded` |
| 403 | `unavailable: permission`, no retry |
| 404 / 422 | `unavailable: workflow_absent` |
| Deadline passed | `unavailable: timeout` |

**429.** `packages/syn-adapters/src/syn_adapters/github/client_api.py:21-39` maps only a 403 rate limit today. It gains 429 → `GitHubRateLimitError`, with the reset taken from `Retry-After`. The runner sleeps until the reset if that is before `not_after`; otherwise the step settles `unavailable: timeout (rate_limited)`. A rate-limited POST is `Ambiguous`, never blindly re-posted.

**`packages/syn-adapters/src/syn_adapters/github/remote_branch_writer.py`** uses the Git Data API.

- It builds a tree from `before_sha`'s tree without `.mutations/`, creates a commit whose parent is `before_sha`, and runs `PATCH refs/heads/<branch>` with `force: false`.
- **Adoption** applies when the head is a commit whose parent is `before_sha`, whose tree differs only by removing `.mutations/`, and whose author is the App.
- Anything else is `HeadMoved`. It never overwrites.

**Wiring.** `apps/syn-api/src/syn_api/_wiring.py` gets no in-memory fallback (ADR-060). Test doubles inherit `InMemoryAdapter`. With no App configured, the runner is `Unavailable`: every step settles `unavailable: not_configured`, which is today's behaviour, made explicit. Settings go in `packages/syn-shared/src/syn_shared/settings/` (ADR-004).

### A.9 Capacity (I1)

**The gate holds its executor slot while it waits.** The execution stays claimed under its lease and counts against `max_concurrent` (`apps/syn-api/src/syn_api/services/execution_host_runner.py:98-106`).

- It holds no workspace, no container and no CPU. The host's binding constraint is CPU (`docs/north-star.md:35`). But the slot is a count, and the north star counts only agents actively working (`docs/north-star.md:15-16`).
- So with `max_concurrent=10` and 3 executions in gates, 7 agents work.
- A Phase 1 executor drain also waits for those gates (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:659-668`).

**Expected cost.** A gate holds roughly the evidence wall time: queue plus run, 10-40 minutes for mutation (job bound 60). Reuse (§A.3) and a single normalized step per head keep it to one or two runs per gate.

**Measured.** Lane 2 records `evidence_gate_slot_seconds`.

**Releasing the slot while waiting** would need a run-queue state such as `parked`, which is an amendment to ADR-072 D3/D11. That is larger than this feature. It is deferred with an explicit trigger: **if gate-held slot-seconds exceed 10% of executor slot-seconds over a week of dogfood, open that ADR-072 amendment.** The event model does not change if waiting moves out of the executor later: only who executes `RUN_EVIDENCE_STEP` changes. This is decision 6.

### A.10 Tokens and App permission

- **Workspace tokens are capped first.** `mint_agent_token` (`packages/syn-adapters/src/syn_adapters/github/agent_token.py:31-50`) passes the installation's permissions with **only** `actions` lowered to `read`. Repository scoping stays exactly as it is.
  - Prompts already expect `gh run rerun` to 403 (`workflows/sdlc/implement-v4-precheck/phases/finalize_pr.md:103-105`).
  - This does not repeat #1197, which downgraded `pull_requests` (`packages/syn-adapters/src/syn_adapters/github/agent_token.py:3-11`).
- **Only after the cap is deployed** is the App granted `Actions: Read and write`. That is DevOps lane work (PR 7).

### A.11 Prompts (whichever workflow adopts this: decision 4)

**Author prompts** (`implement`, `fix`): when you commit `.mutations/`, declare `TASK_RESULT.evidence` with kind `mutation`, your head SHA and the killing tests. Do not ask the orchestrator.

**Reviewer prompts** (`verify`, `reverify`, `reverify_2`). This replaces B1's single "effective head" with a simpler invariant: **between an author phase and its review the head never moves on the platform's account**, so the existing checkout check (`workflows/sdlc/implement-v4-precheck/phases/verify.md:58-67`, `:101-102`) is unchanged.

- Read the latest `artifacts/input/<author-phase>/platform-evidence/*/manifest.json`. It is evidence about the SHA you checked out: judge it. A surviving mutation is `REPAIRABLE`.
- A red `Mutation Patches Not Merged` on a head whose patches still await the final gate is expected, not a finding.
- An `ORCHESTRATOR_EVIDENCE` row that is integration or mutation evidence is **also** written to `TASK_RESULT.evidence`, with tests. Rows of any other kind remain human handoffs.

**`finalize_pr`.**

- Read `artifacts/input/<final-review-phase>/platform-evidence/<latest-gate>/manifest.json`.
- Accept the branch head if it equals the certified SHA, **or** equals the manifest's `after_sha` whose `before_sha` is the certified SHA. This replaces the single-SHA rule at `workflows/sdlc/implement-v4-precheck/phases/finalize_pr.md:62-71` for this case only.
- Mark ready only when all four hold:
  - the manifest is present and `complete`;
  - every step `passed`;
  - `required_check` passed on the head;
  - no other handoff is open.
- Otherwise stay a draft and post the manifest summary.
- Finalize still never pushes (`workflows/sdlc/implement-v4-precheck/phases/finalize_pr.md:155`). The only push is the platform's own, and it is recorded.

### A.12 Workflow YAML shape

**No new phase kind, no new phase field, no workflow YAML change.**

- The gate is platform behaviour, triggered by what a phase reports and what the forge shows. ADR-069 D5 ("a schema field must apply or refuse") therefore has no field to police.
- An "evidence phase" would be skipped by every certified verdict (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/review_rounds.py:136-137`). It would also need a new execution type through `require_supported_execution_type` (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/value_objects.py:69`).
- The earlier draft reserved a phase id named `platform-evidence`. That is **dropped**: reports now live under P's own directory.

### A.13 ADR to amend in place

**ADR-014 gains §10, "Platform-run evidence between phases (2026-10-15)"** (`docs/adrs/ADR-014-workflow-execution-model.md`). It is the execution-model ADR, already revised in place with dated §7-§9. §10 states:

1. the gate semantics and the opens-on-any-outcome rule (§A.3), in line with §8's split between deliverable and side effects;
2. that these are **the first host-side GitHub writes made on a phase's behalf**: a dispatch, a branch commit, and implicitly the trigger of CI, with the trust statement in Risks;
3. that a gate holds its executor slot (§A.9);
4. that interruption during a gate follows §7/§9, with the fork inheriting the open gate, and that gate effects need no acknowledgement (§A.7);
5. the `evidence.json` and manifest schemas.

`docs/deployment/github-app-security.md` and `docs/deployment/github-app-setup.md:93`, `:436` record the permission change. They are not ADRs.

ADR-072 (hosting) is **not** amended in v1. The parked-slot follow-up would amend D3/D11.

The duplicate ADR-072 numbering is noted for whoever renumbers, and is out of scope here.

### A.14 Failure modes

| Mode | Behaviour |
|---|---|
| Void baseline (red, zero tests, skipped, xfail) | `void` from the report. The gate opens. The reviewer or finalize reads it. No patch removal |
| Runner flake (no artifact, `failure`) | one re-dispatch with a new attempt, then `unavailable: runner` |
| 429 / secondary limit | wait for `Retry-After` within `not_after`. A POST that hit it is `Ambiguous`, so the next action is look-up-before-redispatch |
| PC-197 cancel trap | fixed in the workflow (PR 3): group `mutation-evidence-pr-${{ inputs.pr }}-${{ inputs.dispatch_id }}`, so a run can be cancelled only by its own attempt |
| Dispatch accepted, run invisible | the visibility window, then one new attempt, then `unavailable: dispatch_lost` |
| Head moved (a human push) | `void: head moved`. The compare-and-swap refuses. Nothing is overwritten |
| Executor lost mid-gate | `INTERRUPTED`. A person resumes, and the fork adopts the run (§A.7) |
| Artifact store down | `manifest_artifact_id=None`. Prompts stay draft |
| App lacks `actions: write` | `unavailable: permission`, which is today's handoff |
| Repository has no evidence workflow | `unavailable: workflow_absent` |

### A.15 Ordered PRs

`[W]` means a workspace agent can push it. `[D]` means the 4b DevOps lane: `.github/`, App settings, installation approvals. A workspace credential cannot push `[D]` work. Workspace agents write those changes as patches into `artifacts/output/`.

| # | PR | Lane | Depends on |
|---|---|---|---|
| 1 | ADR-014 §10. `EvidenceRequest`, `evidence.json` and manifest models with generated JSON Schema. Vocabulary in `docs/architecture/orchestration-ubiquitous-language.md`: *evidence gate, evidence request, evidence step, attempt, settled, void, unavailable, patch removal, evidence manifest*. Spike: whether dispatch returns run ids, and the `created` filter on the workflow-runs list | W |, |
| 2 | `scripts/mutation_evidence.py` also writes `evidence.json`. New `scripts/integration_evidence.py` (full suite, JUnit, per-requested-id outcomes). `just test-integration-ci`. Schema tests for killed, survived, void, and an integration skip of a requested id | W | 1 |
| 3 | `.github/workflows/mutation-evidence.yml`: per-dispatch concurrency group (PC-197), plus upload of the `evidence` artifact. New `.github/workflows/integration-evidence.yml`: dispatch-only, `pr`/`tests`/`dispatch_id`, the same resolve and fork refusal, `python-integration-env`, `scripts/integration_evidence.py`, and an `evidence` artifact. It is dispatch-only, so it is not PR-gating and `scripts/check_ci_parity.py` needs no entry | D | 2 |
| 4 | Cap workspace tokens at `actions: read`. Map 429 with `Retry-After` | W |, |
| 5a | Transport and observation (§A.2): verdict → command → event → replayed state, plus `ObservedHead` on `ArtifactsCollectedCommand`. Recorded only, with no behaviour change | W | 1 |
| 5b | Gate (§A.3-§A.6): `evidence_gate.py`, events, commands, projection, processor branch, `EvidenceStepHandler` with the attempt protocol, ports and doubles, report filing, `PhaseOutputCache.append`, manifest. Flag off | W | 5a |
| 5c | Resume (§A.7): `inherited_evidence_gate`, resume rules, the fork's first to-do, inherited artifact ids | W | 5b |
| 6 | Adapters: `evidence_runner.py` (dispatch, paginated look-up, batched watcher, report parse), `remote_branch_writer.py`, `RemoteTreePort` adapter, wiring, settings | W | 4, 5b |
| 7 | Grant the App `Actions: Read and write`. Find and update the manifest location (research Open Q7). Update `docs/deployment/github-app-setup.md:93`, `:436` and `docs/deployment/github-app-security.md`. Each installation owner approves | D | **4 deployed** |
| 8 | Read path (`apps/syn-api/src/syn_api/types.py`, `just codegen`). Prompts (§A.11) in the adopted workflow. `CLAUDE.md`/`AGENTS.md` "Verification gates" and `.claude/skills/devops/agent_mutation_evidence.md` changed to "declare it". Flag on. Acceptance | W | 2, 3, 5c, 6, 7 |

**What can run in parallel:** 2, 4 and 5a once 1 lands; 3 once 2 lands. **What serialises:** 7 must follow 4 *deployed*, not merely merged.

**What 4b's DevOps lane owns:**

- PR 3, both workflow files;
- PR 7, the App permission, the manifest and every installation's re-approval;
- never a branch-protection change, because none is needed;
- the decision on whether `ci.yml` integration should run on PRs into `main` (decision 5).

### A.16 Cost

- **Runner minutes.** Mutation is bounded at 60 minutes per run. Integration is one job, not all of `ci.yml`. Reuse and normalization keep this to one run per kind per head. They are GitHub-hosted minutes; repository visibility, and so billing, was not established.
- **API.** About 1 POST, 1-2 paginated look-ups, 1 artifact download and 1 tree read per step, plus O(repositories × workflows) list calls per watcher tick.
- **Executor slots.** One per execution in a gate (§A.9). This is the real cost, and it is measured.
- **Saving.** Every orchestrator turn spent dispatching, watching, deleting patches and marking ready. The PR no longer waits for someone to notice it.
- **Maintenance.** One handler, three ports, one pure rules module, five events, two schemas, and two workflow files in DevOps' lane.

---

## B. In-workspace test infrastructure (the fast inner loop)

**What B adds over A.** A answers "did it pass on a runner the agent does not control?" once per gate, at 10-60 minutes per round trip. B lets `implement` and `fix` iterate on database- and Docker-backed tests *inside* the phase, in seconds to minutes. Bugs are caught before review, which means fewer repair rounds and fewer runs ending `blocked`. A's gates then mostly confirm instead of discovering.

**Why A comes first:**

1. **A removes the orchestrator from the loop. B does not.** Without A, a phase that ran integration tests in-workspace still hands publication to a person.
2. **Publication policy.** ADR-029 says to verify external state independently ("claims are testimony, not evidence", `docs/adrs/ADR-029-ai-agent-testing-verification.md:49-51`). It does not name a hosting location. *Proposed* (decision 8): a READY transition requires evidence produced outside the agent's workspace. Under that policy A stays necessary after B, and B makes A's gates cheaper by making them pass the first time.
3. **A uses machinery that exists; B depends on unsettled security design.**
   - #568 (open) proposes Envoy-proxied Docker orchestration and rejects socket mounts.
   - The microVM plan, `docs/plans/20261013_selfhosted-microvm-pool.md`, is **not on `main`**. It exists only on the branch `docs/runtime-research-20261012`, which describes itself as "a candidate, not an established winner". It allows nested Docker only under `KATA`/`SYSBOX`, gated on experiment E0b (research §2).

**B, staged:**

- **B1 (#568 scope): platform-provided test services.** A phase declares `test_services: [timescaledb, eventstore]`. The platform starts them as sidecars on the workspace network, with no Docker socket, and injects `TEST_TIMESCALEDB_*` / `TEST_EVENTSTORE_*`, which the fixtures already auto-detect. This covers database- and event-store-backed integration tests. It does not cover tests that drive Docker themselves (PC-193's OOM test, `apps/syn-api/tests/integration/test_oom_killed_phase_reaches_the_api.py`).
  - The sidecar lifecycle lives in agentic-workspace's isolation providers: image and isolation belong there (the CLAUDE.md boundary test).
  - The phase field, behind a Protocol, lives here. The contract comes first.
  - The ADR is ADR-021 or `docs/adrs/ADR-072-workspace-platform-access.md`, not ADR-014.
- **B2: nested Docker in a microVM.** Only after E0b reports and the microVM plan merges. It covers the remainder.
- **Not B:** mounting the Docker socket. ADR-021 and #568 rule it out.

B is a separate plan, written after A's PR 8. Its acceptance: "a fix round runs an integration test in-phase, and the following gate's integration step settles `passed` on the first attempt".

---

## Rejected alternatives

| # | Alternative | Why rejected |
|---|---|---|
| R1 | Workspace tokens with `actions: write`; the agent dispatches and waits | An agent polling on paid tokens inside a phase timeout. `actions: write` is repository-wide, so every workspace could also dispatch release workflows, cancel runs and delete artifacts |
| R2 | A new phase kind or `execution_type` | Skipped by every certified verdict (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/review_rounds.py:136-137`). Needs a new execution type (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/value_objects.py:69`). Forces authors to predict at design time a need discovered at runtime |
| R3 | Dispatch `ci.yml` for integration | Runs the whole suite, has no `dispatch_id`, and gives no per-test outcome. Kept as the fallback if DevOps declines PR 3 |
| R4 | `CheckRunIngestionService` to learn completion | Synthesizes failures only (`packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/check_run_synthesizer.py:26`, `:51`). Dispatched runs attach to the dispatched ref |
| R5 | Parse the handoff table or the marker comment | Free text. The marker comment is one mutable comment shared by every run for a PR |
| R6 | Label-triggered `pull_request` runs | Breaks the "trusted tooling from the dispatched ref" model. `pull_request_target` with a PR checkout is the pwn-request shape |
| R7 | A separate `EvidenceRun` aggregate plus a ProcessManager outside the execution | **Reconsidered per I1, rejected for v1.** It would release the slot and own restarts. But the execution must still wait for the result before its next phase, so a slot is released only if the run queue gains a parked state (ADR-072 D3/D11), and that is the costly part, not the coordinator. v1 keeps the decision on the execution stream, where §A.7's resume can inherit it. The trigger in §A.9 reopens this with data |
| R8 | Remove `.mutations/` after the author phase | **Rejected per B1.** The reviewer checkout requires PR head == the author's SHA (`workflows/sdlc/implement-v4-precheck/phases/verify.md:58-67`, `:101-102`) |
| R9 | `finalize_pr` (the agent) deletes `.mutations/` | `finalize_pr` has no checkout and must never push (`workflows/sdlc/implement-v4-precheck/phases/finalize_pr.md:46`, `:155`). It would also lose the before/after provenance |
| R10 | Automatic continuation of an interrupted gate on another executor | Contradicts ADR-014 §9 and ADR-072 D5 (`docs/adrs/ADR-014-workflow-execution-model.md:369-372`). Out of scope for an evidence feature |

## Risks

| Risk | Signal |
|---|---|
| **Auto-ready trusts PR-authored code.** With `docker: true`, PR code runs on the runner and could forge `evidence.json` (`.github/workflows/mutation-evidence.yml` header, research §5). Today a person reads the report first | Stated in ADR-014 §10. Ready is not merged, and merge review still applies. A `passed` report from a run whose job failed settles `void` |
| PR 7 granted before PR 4 deployed | The token log line (`packages/syn-adapters/src/syn_adapters/github/client_token.py`, the "Installation token generated" log) shows `actions=write` on an agent token. A unit test pins the cap |
| The token cap breaks something that needed `actions: write` | "Resource not accessible by integration" outside `gh run rerun` after PR 4 deploys. The documented manifest is `Actions: Read`, so none is expected |
| Gates eat capacity | `evidence_gate_slot_seconds` against the §A.9 trigger |
| Poll too slow | `EvidenceStepSettled` time minus the run's `completed_at` > 2× the poll interval |
| Rate limiting at scale | rate-limit wait time. `unavailable: timeout (rate_limited)` counts |
| An execution waits forever | impossible by `not_after`. A query for executions with an open gate older than the deadline returns zero |
| Evidence workflow drift across repositories | `workflow_absent` and schema-failure counts per repository |

## Verification

Each test must fail with its change reverted. New modules carry the `unit` marker.

**Unit:**

1. **`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_evidence_gate.py`:**
   - a held transition has no `NextPhaseReady`;
   - the gate opens on `failed`, `void` and `unavailable`;
   - a certified skip survives the gate;
   - mutation requests for one head become one step with the unioned tests (I4);
   - a passed step for the same head and tests is reused, not re-planned;
   - **no `remove_mutation_patches` at an author-to-review gate** (B1);
   - cleanup only before the final phase after `CERTIFIED`, and only when every mutation step passed;
   - integration's head is `after_sha`;
   - undeclared patches with no earlier tests give a synthetic void.
2. **Transport through production plumbing (B4).** A real closing `TASK_RESULT` with `evidence` goes through `AgentVerdict.from_agent_text` → `AgentExecutionHandler` → the aggregate. Assert `EvidenceRequested`. Variants: a malformed entry yields a void request; a head with patches and no declaration (observation only) yields a gate. One test per hop, each failing when that hop's copy is deleted.
3. **Attempt protocol (B3)**, run from persisted state with a fresh handler and runner per step:
   - crash before the POST (attempt recorded, nothing posted): look-up first, then one POST;
   - crash after an accepted POST and before adoption is recorded: look-up adopts, with **zero** further POSTs;
   - crash during the retry attempt: adopts attempt 2, never posts attempt 3;
   - `Ambiguous` 429 / 5xx: no immediate re-POST;
   - a late run from an old attempt is ignored.
4. **Delivery (B5):**
   - actual workspace file writes at `artifacts/input/<P>/platform-evidence/<gate-id>/`, live (cache append) **and** after resume (inherited ids);
   - two gates in one execution do not collide;
   - an artifact-store failure gives no manifest, and the finalize fixture reads that as draft;
   - P's flat alias is unchanged after reports are filed;
   - a missing report still appears in the manifest with its outcome.
5. **Resume (B2):**
   - interruption with a step unsettled → resume → the fork's first to-do is `RUN_EVIDENCE_STEP`, it adopts the parent's run_id, and its resume point is the held next phase with the held skips;
   - interruption after `MutationPatchesRemoved` and before integration settles → the fork runs integration on S′;
   - the removal was pushed but its event was lost → the compare-and-swap adopts.
6. **Projection:** step 0 then step n+1; interruption clears; replaying twice gives the same list.
7. **Adapters:**
   - `packages/syn-adapters/tests/github/test_agent_token.py`: `actions == "read"`, other permissions unchanged, repositories unchanged.
   - `packages/syn-adapters/tests/github/test_client_api.py`: a 429 with `Retry-After`.
   - `packages/syn-adapters/tests/github/test_evidence_runner.py`: 403 / 404 / 422 mapping; a report whose `head_sha` disagrees gives void; a `passed` report from a failed job gives void; **a waiter whose run is on page 3 of the list is still found** (I2); one list call per (repository, workflow) per tick with N=50 waiters.
   - `packages/syn-adapters/tests/github/test_remote_branch_writer.py`: `force: false` and a moved head give `HeadMoved` with no second PATCH; the tree differs only by `.mutations/`; adoption.
8. **Scripts:** `scripts/tests/test_mutation_evidence.py` and a new `scripts/tests/test_integration_evidence.py` check that `evidence.json` validates against the schema, and that a skipped requested id gives `void` while a skipped unrelated test does not (I3).

**Mutation evidence** for 1, 3 and 7 (the hold, adoption and the cap): commit `.mutations/*.patch` and run it by hand one last time, or through the gate itself once PR 6 is live.

**Gates:** `just preflight-agent`, `just qa-ci`. `check-untyped-dicts` must not rise: every new structure is a dataclass or a Pydantic model. `vsa` passes with the handler in `slices/execute_workflow/handlers/`.

**Acceptance (PR 8)**, on dogfood with the flag on. The run is the adopted SDLC workflow, on a task whose change needs integration and mutation evidence, for example code covered by `apps/syn-api/tests/integration/test_oom_killed_phase_reaches_the_api.py` (PC-193).

- **AC1, author gate (B1).** Implement pushes S with `.mutations/` and declares mutation tests. The stream shows `EvidenceRequested` after implement, mutation `passed` on S, and **no** `MutationPatchesRemoved` at that gate. Verify's report shows `rev-parse == S`, `headRefOid == S`, and cites the manifest.
- **AC2, final gate, in order (I5).** Reverify certifies S. Then, in this order:
  - mutation settles on S (or is reused);
  - `MutationPatchesRemoved(before=S, after=S′)`, where the S′ commit's author is the App bot, its parent is S, and the diff from S is **exactly** the removal of `.mutations/`;
  - integration settles `passed` on S′, with every requested id `passed`;
  - `required_check` settles `passed` on S′;
  - finalize marks the PR ready: `isDraft == false` and PR head == S′, and `gh api repos/syntropic137/syntropic137/contents/.mutations?ref=<S′>` returns 404.
- **AC3, competing push.** A push to the branch after mutation settles and before cleanup gives a refused compare-and-swap, `void: head moved`, no force, and the PR stays a draft.
- **AC4, executor loss (B2).** Kill the executor while integration runs on S′. The execution goes `INTERRUPTED`. A person runs `syn execution resume`. The fork adopts the existing run: exactly one run carries that `dispatch_id`. It settles, and finalize marks the PR ready.
- **AC5, zero orchestrator actions.** Every `workflow_dispatch` run for the PR in the window has actor == the App bot, and the orchestrator's session log has no `gh workflow run`, `gh pr ready`, `just mutation-evidence`, or push. This is an observation alongside AC1-AC4, not a substitute for them.
- **Negative.** One surviving patch gives a draft, `.mutations/` still present, and SURVIVED in the manifest and the PR comment.

## Out of scope

- Layer B implementation.
- Handed-off commands other than `mutation` and `integration`.
- Integration on every PR into `main`.
- `FLAKE/INFRA` reruns by the platform.
- Cancelling GitHub runs when an execution is cancelled.
- Webhook acceleration of the watcher.
- Fork PRs, which the evidence workflows refuse.
- Merging.
- Renumbering the duplicate ADR-072.

## Needs a human decision

1. **Grant the GitHub App `Actions: Read and write`** (PR 7). Every installation owner re-approves. This is the security trade the layer rests on, and the first host-side write on a phase's behalf.
2. **Auto-ready.** Today marking ready "is a person's decision, not this run's" (`workflows/sdlc/implement-v4-precheck/phases/finalize_pr.md:113-114`). This plan makes it the run's when the manifest is all `passed`. The alternative is to keep ready human: the gate is identical, and only the finalize prompt differs.
3. **The platform commits to an agent's PR branch** to remove `.mutations/`, by compare-and-swap with provenance recorded.
4. **Which workflow adopts it.** v4 is a frozen A/B arm (`scripts/tests/test_implement_v4_precheck_variant.py`). Recommendation: wait for v4's verdict, then cut `sdlc-implement-v5` as v4 plus evidence declarations. The platform gate is workflow-agnostic and ships first, behind the flag.
5. **Integration on every PR into `main`** (`.github/workflows/ci.yml:250-254`). That would make the integration step unnecessary for this repository, but the tiering was chosen for speed.
6. **Accept the v1 capacity cost** of gates holding executor slots (§A.9), with the 10% trigger for an ADR-072 parked-slot amendment.
7. **Measure first.** Query `/api/v1/executions` for v3/v4 to get the baseline rate before PR 8, so that the acceptance has something to be compared against.
8. **Publication policy:** READY requires evidence produced outside the agent's workspace (Layer B, point 2). Proposed, not yet decided.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1 Cleanup before review breaks the reviewer checkout | **accepted** | Cleanup only at the gate in front of the final phase, after `CERTIFIED` (§A.3 step 3). Author-to-review gates never move the head, so `verify.md:58-67`/`:101-102` stay valid unchanged. Reviewer prompts read the manifest and treat a red `Mutation Patches Not Merged` as expected (§A.11). Finalize accepts S′ only through manifest provenance. New R8. AC1 runs the real reviewer checkout against an author gate |
| B2 Executor restart does not restart the handler | **accepted** | The "handler runs again after restart" claim is removed. Interruption follows ADR-014 §7/§9. A person-started resume inherits the open gate: resume point = held next phase with held skips, first to-do `RUN_EVIDENCE_STEP`, adopt the parent's run, inherited provenance and report ids, and no acknowledgement for idempotent gate effects (§A.7). R10 records that automatic continuation is rejected. AC4 and unit tests 5 exercise the real resume path |
| B3 No durable pre-dispatch identity or progress interface | **accepted** | `EvidenceAttemptStarted` (dispatch_id, not_after) is saved before the POST. `EvidenceRunAdopted` records progress. The port is split into dispatch / find_run / await_run / fetch_report. `Ambiguous` means look up first, with a visibility window before a new attempt. Attempt identity, budget and deadline are all on the stream (§A.4, §A.5). Crash tests run from persisted state (unit 3) |
| B4 The request cannot reach the aggregate; no observation boundary | **accepted** | Full hop table: verdict → handler → command → event → replayed state (§A.2). A host-side `EvidenceHeadObserver` reports `ObservedHead` on `ArtifactsCollectedCommand`, and the aggregate does no I/O. PR and head come from declaration checked against the forge, branches from `PhaseCommitPushed`. Per-hop tests through production plumbing (unit 2) |
| B5 Artifact ids do not reach the next workspace | **accepted** | Reports are filed as non-primary artifacts of P and injected by the existing validated sink at `artifacts/input/<P>/platform-evidence/<gate-id>/`. `PhaseOutputCache.append` for the live path, inherited artifact ids for resume. An event-built `manifest.json` lists every expected step, so a missing report cannot read as passed. A store outage fails closed. The reserved phase id is dropped (§A.6, §A.12). Unit 4 checks real file writes, live and after resume |
| I1 An idle wait consumes execution capacity | **accepted** | §A.9 states the slot cost, the drain effect and a Lane 2 metric, with a 10% trigger for an ADR-072 parked state. R7 was reconsidered on those grounds and rejected for v1 with reasons. Decision 6 added |
| I2 Webhooks as acceleration; pagination | **accepted** | The batched host poll is the mechanism. Webhook acceleration through `add_observer` is a deferred follow-up, because observers are best-effort and arrive in the API process, not the executor. The look-up paginates by time bound, not `--limit 20`. A test for a waiter on page 3 (§A.8, unit 7) |
| I3 Integration success needs per-test coverage | **accepted** | Integration requests require `tests`. A new `scripts/integration_evidence.py` runs the full suite without `-x`, with JUnit. A requested id that is not collected, skipped or xfailed voids; an unrelated skip is reported, not voided (§A.1, unit 8) |
| I4 Normalize mutation requests | **accepted** | One mutation step per (repository, head) with unioned tests, plus reuse of passed evidence for the same head and tests (§A.3 steps 1-2) |
| I5 Acceptance order and vacuous negatives | **accepted** | The order is mutation on S → removal S→S′ (author, parent, exact diff) → integration on S′ → required check, plus an injected competing push (AC2, AC3). "Commits after finalize are the App's" is replaced. The zero-actions observation is kept as a supplement only (AC5) |
| I6 Citations and facts | **accepted** | Every citation is now a repo-root path. The `PollerState` cadence is no longer cited: defaults are 60/300 (`packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/poller_state.py:34-38`), and the evidence watcher has its own setting. The ADR-029 claim is softened to a proposed publication policy (decision 8). The token-cap and App-grant separation is kept, with repository scoping untouched |

## Readiness

Ready to implement PRs 1-6 now, behind `SYN_EVIDENCE_GATE_ENABLED=false`. PRs 7-8 are blocked on one human decision: the owner granting the GitHub App `Actions: Read and write` (decision 1). Decisions 2-6 shape PR 8's prompts and adoption, not the platform work.

