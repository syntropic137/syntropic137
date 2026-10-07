# Lessons from orchestrating Syntropic137

Distilled from the paper cuts and the 2026-10-04 and 2026-10-06 retros. Each
entry says what to do differently and why. When a fix lands, replace the entry
with a pointer to the change.

## Verification

- **An eval measures its environment as much as its subject.** The first verify-prompt A/B scored 1/6 vs 0/4 because the eval sandbox had no package-index network, so the verifier blocked on failed installs (#1726). The eval environment must match production for the thing being measured; environment failures score ERROR, not FAIL.
- **A verifier suite needs clean controls.** Without bug-free cases, a verifier that blocks everything scores 100% (research #1725).

- **Test doubles diverge from real backends.** The in-memory event store keys
  streams by `Type-id`; the ESP server keys them by aggregate id alone (ESP
  #344). In-memory artifact storage keys objects by id; MinIO keys them by path.
  So any new aggregate id, or any stored key, needs a test against the real
  backend.
- **Read-only reviews never run tests.** Run the targeted tests yourself before
  merging on a review.
- **Two PRs that are each under a cap can merge to over it.** Two 750-line PRs
  merged into a 752-line file. Re-run fitness after merging a sibling PR.
- **Run the gates on the commit, not the worktree.** Uncommitted auto-fixes give
  a fake green.
- **A stale green proves nothing.** Re-merge main and re-run the gates before
  merging.

## Dispatch and prompts

- **Read the existing epics, ADRs and plans before briefing a design.** Three briefs on 2026-10-07 (token retry, two-host spike, executor Step 3) contradicted designs already written (#1593, #1612, #1310) and were refused at premise. The premise phase is cheap insurance; the miss was the orchestrator's.
- **Give a run every repo a fix may touch (`-R`).** The workspace token is scoped to the declared repos; a #1696 fix that needed an ESP change dead-ended (PC-121).
- **A run that needs platform data cannot get it from inside a workspace** (no API route or credentials, PC-127). Measure first and paste the data into the brief, or do that part locally.

- **Name the trap.** A run that is told "the last attempt failed because X;
  prove with Y that you did not" avoids X.
- **Premise phases correctly refuse false premises.** A refusal is the system
  working. Check your premise with `git grep origin/main` before you dispatch.
- **Agents invoke skills only when the prompt names them.** Name the skills you
  want used.
- **Fix-ups on a stale PR fail at implement** ("nothing to change"). Use
  `sdlc-reverify-pr-v1` instead (PC-76).
- **The task text is the brief** (every phase reads it as `$ARGUMENTS`). An
  empty task runs at full cost and does nothing; it is now refused at admission.

## Platform and deploy

- **Check what the deployment actually runs, including the event store.** Silent dropped events were the v0.15.1 event store (no commit-order lock) left pinned by hand while main used v0.16.0; pit stops never moved it (#1708).
- **A forced swap orphans every run, and a read-model rebuild hides orphans from startup reconciliation** (PC-123). Prefer the gated pit stop now that pause no longer deadlocks (#1688).
- **Disk is a hard stop.** At ~96% the API refuses new executions with 507. Check disk every tick; this host also carries other projects.
- **Concurrency is CPU-bound on this host.** At 10 runs load is ~27 on 16 cores and provision steps start timing out (PC-126); memory stays ~15%. Cut per-run CPU and tokens before raising the cap.

- **Prove a deploy with a real start.** The pit stop probe does this since #1644.
  Keep the probe workflow installed and unarchived.
- **One swapper at a time, and never kill a pit stop mid-swap.** If a verify
  aborts, wait for lag 0, then `PUT /maintenance active=false`.
- **The deployed compose drifts from the repo** (PC-88). After adding an env
  passthrough, check `docker exec syn137-api printenv <VAR>`.
- **Workspace limits:** 8 GB is set on the VPS. 4 GB OOM-kills test suites
  (PC-89).
- **A projection VERSION bump replays about 58k events in about 5 minutes.** Plan
  the deploy around it.
- **The npm-installed `syn` has an old YAML parser** that collapses anchors.
  Install workflows with the CLI built from main and check the phase count
  (PC-78).

## Vendors

- **Codex capacity is the most common failure.** Resume the run.
- **Codex or Claude quota cannot be retried.** Page the owner and use a fallback
  verifier (PC-83).
- **A Claude verifier checking Claude's implementation is not a cross-model
  review.** Say so when you rely on one.

## Orchestrator mechanics

- **Merge watchers use `if ...; then merge; fi`, never `cmd ; merge`.** A `;` merges on red CI (PC-118).
- **Never install an eval workflow by hand.** `eval_suite.py launch` owns install and provenance; a manual install stamped 0.0.0 and blocked the launch (PC-119).
- **Grep exec ids from the execution list, not from command output** that echoes the task text (PC-84 repeated).

- **Use the pinned helpers.** Ad-hoc `curl` with `$(...)`, `git add -A` and
  heredocs containing secrets trip the security hook.
- **Never print `.env` or secrets.** Extract values into variables.
- **Push to `gh pr view N --json headRefName`, never to the current local
  branch name.** Worktree branch names differ from PR head refs (PC-77).
- **A new worktree needs `git submodule update --init --recursive`** before `uv`
  or the pre-push hook will work.
- **`gh run list` can lag a push by seconds.** Resolve the run id before chaining
  on it.
- **No `sleep` polling.** Use a background command or a Monitor that exits on the
  condition.

## Working with the owner

- **Never block on a question.** Put it under HUMAN REVIEW with your default.
- **The owner cannot approve their own PRs on GitHub.** Chat approval plus
  `--admin` is the path, and only for the PRs they named.
- **A version bump and the main to release PR belong to the owner.** Betas are
  pit-stop builds and need no bump PR.
- **Report PRs as merged, not as opened.** "Certified" is not "merged".
