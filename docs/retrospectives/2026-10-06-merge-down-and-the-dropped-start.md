# 2026-10-06 The merge-down, and the start that was dropped

## What happened

The two days after the 2026-10-04 dogfood retro were spent landing what that day
had opened. The count of open PRs reached 24 on the morning of 10-05, so new
feature work was frozen and the queue was merged down. Six PRs went in on a batch
approval ("assume the other 6 are good"), merged with `--admin` once their CI was
green. One of them, #1574, keyed a new `ExecutionRequest` aggregate by the
execution's own id. The ESP event store keys a stream by aggregate id alone, so the
request occupied the execution's stream and every direct start after it was dropped
as a duplicate. Beta.8 and beta.9 both shipped that bug and passed every pit-stop
check, because no check started a real run. The orchestrator's manual "dispatch one
real workflow" step caught it on beta.9; #1641 fixed it, and beta.10 restored
starts 55 minutes after the first stuck dispatch; starts had been broken on the
deployment for about 3.5 hours, since beta.8. The rest of the window followed
the same shape four more times: a PR certified green by its own verification, then
a second, independent verifier found a blocking bug that only a real backend shows.
Codex capacity, then the Codex quota, took out the verify phase on 32 runs. Work
stopped on the owner's call with Claude usage at about 6%.

## Timeline

- 10-05 morning - 24 open PRs. Feature freeze. CODEOWNERS narrowed to trust
  boundaries (#1595), approvals given in chat, landing subagents run in parallel.
- 10-05 23:19 - #1574 merged in the batch (df7a99db1). Every direct start from here
  on is dropped.
- 10-06 01:41 - beta.8 live. No run dispatched on it.
- 10-06 04:20 - beta.9 live. Two dispatches at 04:21 sit at "queued 0/4" forever.
- 10-06 04:45 - Logs show `Concurrency conflict on stream 'WorkflowExecution-<id>'
  (expected=0, actual=1)` followed by `Duplicate dispatch detected, skipping`. A debug
  subagent finds the `ExecutionRequested` event at version 1 of each execution's
  stream.
- 10-06 05:10 - #1641 merged. Beta.10 is live at 05:13; a phase reaches running at
  05:16.
- 10-06 06:50 - Codex quota exhausted until 10-09. A stopgap workflow puts verify on
  Claude Opus, and local Opus subagents act as verifier for the stranded PRs.
- 10-06 07:00 to 14:30 - Second verifiers find blocking bugs in #1649, #1651, #1652
  and #1654, and each is fixed before merge.
- 10-06 12:46 - Beta.11's new start probe fails as designed (its probe workflow was
  archived). A real dispatch proves starts work.
- 10-06 14:10 - A workspace is OOM-killed at #1607's 4 GB cap. The VPS compose has
  drifted from the repo and never received the limit's passthrough.
- 10-06 ~15:00 - Development stopped. Retrospective.

## Root cause

**One property, four times: a test double that does not behave like the backend it
stands in for.**

| PR | The double | The real backend | What it hid |
|---|---|---|---|
| #1574, fixed by #1641 | `MemoryEventStoreClient` keys a stream by `Type-id` | ESP keys by aggregate id alone | every start dropped (P0) |
| #1649 | same | same | an execution id accepted as an eval id; archive wrote into the execution's stream |
| #1652 | in-memory artifact storage keys by artifact id | MinIO keys by workflow, execution and artifact | every binary artifact read returned 404 |
| #1654 | Codex test fixtures | `codex exec` reports usage once, after the run | the cost limit could never stop a Codex phase |

Three gates that existed to catch this did not run before merge:

- **Integration tests run only on `main`, never on PRs (#1625).** The one test that
  would have failed against the real store never ran before merge.
- **The pit stop declared success without starting a run.** Two betas shipped
  with starts broken; the check was a line of text telling the operator to do it.
- **The batch approval was approval of a process, not of the change.**
  "Assume the other 6 are good, assuming they've had the review passes" trusted
  verify phases that run read-only and cannot exercise a real store.

Second-order causes:

- **The verify phase depends on one vendor.** Codex capacity (29) and quota (3)
  were 32 of 66 failures: the largest single cause. The retries added by #1611 do
  not help with a quota.
- **Limits were enforced before they were sized.** #1607 applied a 4 GB
  workspace cap that a full test suite exceeds.
- **The deployed compose drifts.** The pit stop repoints image pins but never
  syncs the compose template, so passthroughs added in the repo never reach the VPS.

## What went well

- **Agents refused instead of shipping partial fixes.** Of the 66 failures, 20 are
  agents reporting failure. They refused a false premise or a branch with nothing
  to do, or stopped at a platform gap rather than ship part of a fix. Two of
  those stops became fixes the platform needed:
  - the pit-stop probe could not cancel a queued run, which became #1650 and #1651;
  - UI screenshots arrived corrupted, which became #990 and #1652.
- **An independent second verifier paid for itself every time.** It found a
  blocking bug in all four PRs it reviewed, each one invisible to the first verify.
  Each verifier mutation-tested its critical tests: revert a line, watch the test
  fail, restore it.
- **Diagnosis was fast:** about 25 minutes from noticing the P0 to a root cause
  backed by the stored events, and 55 minutes from the first stuck dispatch to a phase running in production.
- **Verify can now check UI changes itself:**
  - a workspace can drive a headless browser (#1642);
  - PNG artifacts survive collection byte-for-byte (#1652, checked live with
    matching sha256);
  - verify phases screenshot UI changes (#1648).

## Scorecard

Window: 2026-10-05 00:00Z to 2026-10-06 15:00Z, so it overlaps the 10-04 retro's
window by two hours. Compare against [2026-10-04](2026-10-04-dogfood-orchestrator-day.md).

| Measure | 10-04 retro | This window |
|---|---|---|
| Executions started | 96 | 116 (47 completed, 66 failed, 2 cancelled, 1 running) |
| Spend (sum of execution cost) | not recorded | USD 525 |
| Failures: Codex capacity / quota | 2 / 0 | 29 / 3 |
| Failures: agent refused or stopped at a platform gap | 9 | 20 |
| Failures: phase deadline (exit 124) | 17 | 8 |
| Failures: OOM at the workspace cap (exit 137) | 0 | 2 |
| Failures: orphaned by an API restart | 8 | 1 |
| PRs merged in syn137 | 26 | 39 |
| Peak open PRs | not recorded | 24 |
| Issues filed in syn137 | 26 | 27 |
| Production incidents | 0 | 1 (P0: starts broken ~3.5 h from beta.8 to beta.10; 55 min after the first dispatch) |
| Betas deployed | 2 | 6 (beta.6 to beta.11) |
| PRs whose second verifier found a blocking bug | not measured | 4 of 4 |

## What we changed

- PR #1641 - an execution request gets its own stream id (`request-<execution_id>`),
  with a test against a store keyed by aggregate id alone.
- PR #1644, and b33320750 on main - the pit stop dispatches a probe and only prints
  DONE once a phase is running and the probe is proven terminal. The direct fix
  closes an unset-variable crash on slow hosts.
- PR #1651 - a queued execution can be cancelled (withdrawn), including the race
  with an admission grant that is already in flight.
- PR #1645 - the unapplied-starts check pages by what gRPC accepts (#1640).
- PR #1652 - binary artifacts stay byte-for-byte; reads use the stored key.
- PR #1649 - an eval exists only if its stream recorded `EvalCreated`.
- PR #1654 - per-phase cost limit. It is refused on Codex phases, where usage
  arrives too late to stop anything.
- PR #1653 - `sdlc-reverify-pr-v1` re-verifies an existing PR head, so a run that
  dies in verify no longer means re-running implement.
- PR #1646 - 757 unit tests that CI never selected now run, and the marker
  ratchet is zero-tolerance.
- PR #1642, PR #1648 - workspaces screenshot UI changes, and verify must look at
  the screenshots.
- PR #1638 - security patch for katex, source-map-js and sprintf-js.
- syntropic137/event-sourcing-platform#344 - the in-memory store's keyspace does
  not match the server's.
- VPS - the workspace memory limit is raised to 8 GB and its passthrough added to
  the deployed compose (backups `.bak-pre-ws-limits`, `.env.bak-pre-ws-mem`).

## Open follow-ups

- [ ] **Contract tests for every in-memory adapter.** Run the same assertions
  against the fake and the real backend, and fix ESP #344. Draft #1655 exists;
  its run was OOM-killed before the limit was raised.
- [ ] **Integration tests on PRs (#1625).** The P0's test existed and never ran
  before merge.
- [ ] **No batch approval of PRs whose verify cannot touch a real backend.** The
  test is a second, independent verifier with mutation-checked tests, and today
  it caught four blocking bugs.
- [ ] **Pit-stop hardening.** Draft #1656 is cancelled and resumable. It adds:
  - a precheck that the probe workflow exists and isn't archived (PC-87);
  - credentials kept out of `curl -u`, where they are visible in `ps` (PC-85);
  - a check that the deployed compose matches the repo template (PC-88).
- [ ] **A fallback verifier.** Fail fast on a quota error (PC-83). Stop using the
  `*-claude-verify` stopgap workflows now that Codex is back.
- [ ] **Size the workspace limits, and report OOM as OOM** (PC-89). Exit 137 with
  null resource usage is all the record shows today.
- [ ] **A rollback hazard from #1654.** A build older than it, replaying a start that
  carries `max_cost_usd`, loses the pinned phases. Add the key to
  `REMOVED_EXECUTABLE_PHASE_KEYS` before rolling back past it.
- [ ] **Finish evals step 6:** `PATCH /evals/{id}`, `syn eval update`,
  `POST /evals/{id}/runs`.
- [ ] **Merge throughput.** 24 open PRs cost a full day of landing. Keep at most
  about 8 open before dispatching more; the owner's merge-queue question is H14.
