# Handoff: platform robustness priorities, from two days of DreamShip dogfooding

**Date:** 2026-09-19
**Repo:** syntropic137/syntropic137
**Branch:** main (the workflow fixes below are merged)
**Deployment:** v0.29.1-beta.2 on the VPS
**From:** the DreamShip project-management session (`dream-ship-v0-81`)
**To:** the Syntropic137 project manager, to set the next priorities
**Status:** evidence gathered and ranked. Nothing here is implemented except where it says so.

## Purpose

After seeing the numbers, the operator's words were: *"there is a lot of failures here and lots of wasted money ... prioritize fixes to make the system more robust ... seems like we need a review step and ... a resume step actually seems like what we need."*

This document gives you the evidence behind that, ranked by the money each fix would recover. It is written so you can set the order of work without re-running the analysis. Every number below comes from `GET /api/v1/executions` and the phase records on the deployment. The execution IDs are listed so you can check any of them.

## The numbers

**DreamShip on the self-hosted deployment, 2026-09-17 to 09-18:**
- 51 executions; 14 completed (27%).
- USD 525 spent; USD 140 of it on executions that completed.
- 31 failed, costing USD 354.
- **19 of those 31 (USD 287, 81% of the lost spend) failed after at least one phase had completed.** Their earlier work was kept as artifacts, thanks to #1321, but the execution could not continue.

**Loss by cause** (a classifier over `error_message`; runs I cancelled myself are excluded):

| Cause | Runs | USD lost | Issue |
|---|---:|---:|---|
| Phase timeout (exit 124), mostly implement phases | 12 | 155.91 | #1231, #1262 (closed) |
| Unreadable `TASK_RESULT` block on a phase that finished its work | 4 | 46.12 | #1324 |
| Phase declared an output and wrote none | 4 | 39.41 | #1300 (closed) |
| Unpushed-work guard (correct; the work was quarantined) | 3 | 38.79 | #1308 |
| Guard could not inspect the workspace (`git for-each-ref` failed) | 2 | 30.79 | none found |
| Codex stream ended without `turn.completed` | 3 | 25.15 | #1335 |
| Credential-removal probe | 2 | 17.45 | #1293 |

**`sdlc-decision-record-v1`, the newest workflow:**
- 8 executions; 1 completed unaided (`exec-99abc392f541`, the canary run).
- 3 more were finished locally from their kept artifacts.
- syntropic137-5c measured it as the costliest workflow on the VPS: USD 127 per delivery.
- Four of its eight failures were defects in the workflow's own prompts. All are now fixed: #1363, #1365, #1368, #1370, #1374.
- The other failures were platform classes that are still open: #1324, and the one #1376 now names.
- Another queue saw the same `TASK_RESULT` class on `sdlc-implement-v2`: a finished USD 10.76 phase wrote `{"status": "completed", ...}`.

## Priorities

They are ranked by recovered spend per unit of effort. The first item changes every row below it: with it, a single-phase failure costs one phase, not the run.

### P0-1. Resume a failed execution from the phase that failed (#1369, which is filed under #1335)

- **Why first:** it turns every failure class in the table from losing the run into losing one phase. A six-phase workflow at 95% reliability per phase completes 74% of the time without resume. With one retry per phase, it completes about 100% of the time at 1.05× the cost or less.
- **Two implementations already exist:** PR #1347 (retry one phase in place) and the branch `fix/1335-retry-failed-phase-in-place` (resume from a failed phase, with no PR yet). Which of the two lands is the owner's call. **Do not start a third.**
- **Prerequisite:** #1307. The execution must record its task and inputs, or a retry has nothing to retry with.
- **Acceptance:**
  - An execution that failed in phase *k* can be continued from *k*.
  - Phases before *k* are not billed again.
  - The new attempt is linked to the original.
  - It is proven on a real failure that has kept artifacts, e.g. `exec-e4a12b683e6f`, which failed in phase 5 of 6.

### P0-2. Do not fail a phase that did its work because its status block is malformed (#1324)

- If the declared output exists and the only defect is an absent or unreadable `TASK_RESULT`, either complete the phase with a warning, or re-prompt once for the block and fail only if that also fails.
- Three decision-record phases and one implement-v2 phase failed this way today with their deliverable complete. Every failing block used `status` where the parser needs `success`.
- Two further fixes would help: show the exact block again at the end of the injected prompt, since agents summarise whatever the prompt ends on; and make the parser's error name the missing key.

### P0-3. A cost limit per phase, not only a time limit (#1376, new)

- `exec-d9ec05de3174`'s experiment phase ran nine parallel subagents and spent **USD 77.35** before its timeout ended it.
- `timeout_seconds` bounds time. Once a phase fans out, it does not bound money.
- The ask is a per-phase `max_cost_usd` that ends the phase cleanly: artifacts collected, and the outcome recorded as distinct from both failure and timeout. Related: #85.

### P1-4. Timeouts should end cleanly (the largest dollar class: 12 runs, USD 156)

- #1347 retries a timed-out phase, but a retry that hits the same limit fails the same way. What helps is making the limit survivable:
  - **Warn the agent before the limit.** Inject a message like "10 minutes left: commit and write your deliverable now" at about 85% of `timeout_seconds`. `syn control inject` already exists as the mechanism.
  - **Collect the output at the limit, the way a finish does.** This covers #1231: a timeout currently destroys unpushed commits.
- On the DreamShip side, implement work has moved off the platform to local agents with Codex review until this lands.

### P1-5. Transient infrastructure failures should retry, not end the run

| Failure | Status |
|---|---|
| Codex capacity (#1303) | PR #1344 in review, planned for beta.3 |
| Codex stream without `turn.completed` (#1335) | 3 runs |
| Credential-removal probe (#1293) | 2 runs |
| Unpushed-work guard could not run `git for-each-ref` | 2 runs; no issue yet; the messages are on `exec-481b9739dc9d` and `exec-bc6152200eb8` |

Each of these currently ends the execution on one failed call.

### P1-6. A phase that ends its turn with subagents still running (#1364)

- The phase is killed with its subagents mid-work.
- Without the unpushed-work guard to catch it, it would have **completed** with nothing delivered.
- The ask: keep the session alive until they finish, within the phase budget, or fail the phase with an error that names the orphaned tasks.

### P2-7. The "review step": a changed workflow proves itself before real work (#1377, new)

This is the operator's review step. Every decision-record defect was found at full price on a real question. One USD 27 test run would have found them first. The four asks in #1377, in increasing order of effort:

1. Treat an unproven workflow version as unproven: warn, or require `--allow-unproven`.
2. Add `syn workflow canary`.
3. Make `syn workflow install` read its own definition back, with a retry. A read immediately after install returned the old prompts.
4. Add lint rules to `check_workflow_definitions.py` for the defects above.

### P2-8. Measure it

- Add completion rate and cost per delivered execution, per workflow, as first-class numbers: syntropic137-5c's USD 127-per-delivery figure should be on a dashboard, not rediscovered by hand.
- Set a target, for example 80% completion per workflow, and report each fix above against it.
- #1357 (failure classification) is closed. That makes these numbers trustworthy for the first time.

### Also open, noted without re-ranking

- #918: cancel does not cancel. In practice my cancels landed after one to two minutes.
- #1318: a projection rebuild blinds the read projections. The deployment plan already avoids it.

## What is already done (do not redo)

- **Workflow prompt fixes for `sdlc-decision-record-v1`,** each merged after a cross-model review with no blockers:

  | PR | Fix |
  |---|---|
  | #1363 | decide has no Bash, and names experiments without running them |
  | #1365 | experiment waits for its subagents; probe code goes in `/tmp` |
  | #1368 | long documents are written in sections |
  | #1370 | every phase ends with the exact `TASK_RESULT` block |
  | #1374 | experiment is capped at five probes and writes its summary first |

- **#1362:** the root `conftest.py` strips git's hook-exported variables. Under `pre-push`, a fitness test had been committing into the real repository.
- **Issues filed from this work:** #1364, #1369 (linked to #1335), #1376 and #1377, plus evidence on #1324 and #1335.

## Do's and Don'ts

- **Do prove each fix with one test run before trusting it.** One execution at a time on an unproven change.
- **Do read execution truth from the phase records and artifacts, not from `error_message`.** Most failures kept their artifacts. Check `GET /api/v1/artifacts?execution_id=<id>` and `refs/syn/lost/<exec>/<phase>` before calling anything lost.
- **Do remember that a running execution keeps the workflow definition it started with.** A reinstall affects only new executions.
- **Don't start a third resume implementation.** Link to #1335 instead.
- **Don't count a correct unpushed-work guard failure as a platform defect.** It did its job: the work was quarantined and recoverable. The defect is whatever left the work unpushed.

## References

- Operator-facing brief with the run ledger and the loss chart: the "Compartment Zero Decision Runs" artifact. It is private to the operator; ask them for the link.
- DreamShip decision records: branch `docs/decision-runs-2026-09-18` of `NeuralEmpowerment/dream-ship_v0`, `docs/research/2026-09-18-decision-runs/`.
- Earlier handoff: `docs/handoffs/20260917-handoff_running-dreamship-work-on-the-vps.md` (in the main checkout, not on `main`).
