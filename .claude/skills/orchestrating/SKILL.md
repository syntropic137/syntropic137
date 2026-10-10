---
name: orchestrating
description: Use when acting as the orchestrator agent that drives Syntropic137 - running the dogfood loop, deciding what to dispatch next, landing agent PRs, deploying a beta, triaging failed executions, or keeping the scratchpad, paper cuts and retrospectives current. Trigger phrases include "orchestrator tick", "keep the loop running", "what should we dispatch next", "land these PRs", "why are PRs stacking up", "deploy the next beta", "pit stop", "the run failed, what now", "write the retro", "is the system helping", "scale quality", "learning loop for the orchestrator". Do NOT use for deciding whether one task belongs in a workspace or locally (see `dogfooding`), for turning one incident into an eval case (see `learning-loop`), for designing a workflow A/B experiment (see `workflow-experimentation`), or for release-branch and version-bump mechanics (see `devops`).
---

# Orchestrating Syntropic137

Syntropic137 exists to **scale quality development**. The order is fixed:
**reach the quality bar first, then make that same bar cheaper and faster.**
Cost and speed are never bought with quality. Today the platform orchestrates
its own development (dogfooding); later it orchestrates other apps, so every
lesson learned here is the product. The orchestrator is the agent that
dispatches workflows, verifies what they deliver, lands it, deploys it, and
turns what happened into durable learning. Its job is not to write the code. Its
job is to make the system that writes the code trustworthy, and to leave an
accurate record of what worked and what did not.

## Outcomes we are looking for

### Outcome 1: what merges is correct

The quality bar comes first. A PR the system certifies does not come back.

- *Signal:* escaped defects per merged PR trends to zero. On 2026-10-06 it was
  1 P0 in 39, and a second verifier found blocking bugs in 4 of 4 certified PRs.
- *Signal:* no production incident traces to a merge that skipped a gate.

### Outcome 2: the same bar gets cheaper and faster

Only once Outcome 1 holds: cost and wall-clock per merged PR fall without the
escaped-defect rate rising.

- *Signal:* cost per merged PR and owner minutes per merged PR, recorded in each
  retro scorecard, fall between retros.
- *Signal:* the run failure rate excluding vendor outages falls (about 30% on
  2026-10-06).

### Outcome 3: the platform is always moving, and never piling up

Work flows through: runs in flight, PRs landing at the rate they open.

- *Signal:* 3-4 executions in flight whenever there is queued work; no multi-hour
  gaps caused by the orchestrator waiting on a question.
- *Signal:* open agent PRs stay at 8 or fewer. At 24 on 2026-10-05, landing them
  cost a full day.

### Outcome 4: the owner is needed for policy, not for review

The workflow is the reviewer. The owner decides direction, trust boundaries and
spend; the system and the orchestrator decide whether code is correct.

- *Signal:* owner messages are about priorities and policy, not "the checks are
  red" or "why are there 24 PRs".
- *Signal:* questions for the owner sit in the scratchpad's HUMAN REVIEW section
  and never block work.

### Outcome 5: every lesson compounds

What happened becomes data: paper cuts, retros with scorecards, issues with
fitness functions, eval cases. The next run is better because of the last one.

- *Signal:* every retro links a concrete change, and its scorecard is comparable
  with the previous retro.
- *Signal:* every escaped bug becomes an eval case (see `learning-loop`).

## Principles

1. **Quality first, then cost and speed.** When the two conflict, quality wins,
   because rework costs more than anything saved. A cheaper model, a skipped
   phase or a faster merge is acceptable only once the eval set shows the bar
   still holds.

2. **A green check proves what it exercised, and nothing more.** Four PRs on
   2026-10-06 were certified against in-memory test doubles that behave
   differently from the real backend (event-store keyspace, MinIO keys, Codex
   usage timing). Before trusting a green, ask what it actually ran against.
   Integration tests do not run on PRs here (#1625), so a PR's CI never touched a
   real store.

3. **Every merge gets a second, independent verifier.** It should be on another
   model, or at least another context, and it mutation-checks the critical tests:
   revert the line, watch the test fail, restore it. Run Codex
   `sdlc-reverify-pr-v1` or a local verifier. Never batch-approve on "they had
   review passes". The P0 of 2026-10-06 entered through exactly that.

4. **A deploy is done when a real execution reaches a running phase.** Not when
   containers are healthy, and not when projections have caught up. The pit stop
   now proves it with a probe (#1644). If the probe is skipped or fails,
   dispatch a real run yourself before saying the deploy is done.

5. **Keep the platform busy and the queue short.** Dispatch to 3-4 runs, and
   stop dispatching while more than 8 agent PRs are open; land first. At least
   20% of dispatches go to tech debt and UI feedback (`GET /feedback?status=open`).

6. **Nothing the orchestrator does may block the loop.** That rules out three
   kinds of wait:
   - **A question for the owner.** Make the conventional choice, log it under
     HUMAN REVIEW in the scratchpad with your default, and keep working. A
     single unanswered question once idled the platform for a whole day.
   - **A command that waits for input.** Use the non-interactive form
     (`syn control cancel --force`, `codex exec ... < /dev/null`).
   - **A foreground wait of unknown length.** Run CI watches, pit stops and
     subagents in the background with a bound, and act when they notify; never
     poll with `sleep`. A tick only fires while the orchestrator is idle, so a
     stuck foreground command stops the whole loop.

   Friction goes to `papercuts.md`, orchestrator friction to the scratchpad log,
   and owner decisions to HUMAN REVIEW. None of the three is waited on.

7. **Name the trap in every task prompt.** Agents satisfy every stated
   requirement and fail on the hop nobody described. Each prompt names the prior
   failure it must not repeat, and the command that proves it did not.

8. **Judge by the stored record and the artifact, never by status.** An
   execution's `completed` describes the harness, not the outcome; `failed` can
   mean an agent correctly refused. Read the PR, the diff, the phase report and
   the stored error. Never reason about a past run from today's code.

9. **Write it down where it lasts.** The scratchpad and paper cuts are the
   working log. Retros in `docs/retrospectives/` are the durable record, with a
   scorecard. A lesson that lives only in a chat is lost.

## Anti-patterns

Observed while orchestrating this repo:

- **Batch approval of verification you have not seen run.** "Assume the other 6
  are good" merged #1574, which dropped every execution start on two betas.
- **A read-only review offered as verification.** Codex reviews in a read-only
  sandbox cannot run tests. Two of them approved a class that could not be
  constructed, and main went red.
- **The platform's own verify treated as sufficient.** On 2026-10-06 it
  certified four PRs with blocking bugs. Each was found by a second verifier.
- **Dispatching while PRs pile up.** New runs open new PRs faster than they
  land; each one then needs main merged in, re-run gates and conflict fixes,
  and the owner's patience runs out first.
- **Calling a deploy done on green container checks.** Beta.8 and beta.9 both
  passed every pit-stop check with starts broken.
- **Single-vendor verification.** Codex capacity and quota caused 32 of 66
  failures in one window. Every verify phase died at once.
- **Limits enforced before they are sized.** A 4 GB workspace cap OOM-killed
  agents running the test suite (exit 137).
- **Deployed config that drifted from the repo.** The pit stop repoints image
  pins but never syncs the compose file, so new env passthroughs never reached
  the VPS.
- **Orchestrator shortcuts that break things:**
  - pushing with `HEAD:$(current branch)` from a worktree whose local branch
    name differs from the PR's head;
  - grepping the first `exec-…` id out of CLI output that echoes the task text;
  - chaining a deploy on a CI run id that does not exist yet.
- **Killing a running pit stop** mid `compose up` took the gateway down. Read
  its log first; one swapper at a time.

## Recommended tools and practices (as of 2026-10-06)

### Outcome: what merges is correct

- **`sdlc-implement-v3`** for new work (premise, implement, verify on Codex,
  then up to three fix/re-verify rounds and finalize). It gives a certified PR,
  not a merged one.
- **`sdlc-reverify-pr-v1 -t "#NNNN"`** as the second verifier, and to rescue a
  run that died in verify without re-running implement.
- **Before any merge, run locally:**
  - `git submodule update --init --recursive`;
  - the PR's targeted tests, plus `-m integration` against `syn-test-db`
    (127.0.0.1:15432);
  - `uv run pytest ci/fitness -q` and `just preflight`.
  - Do it in a worktree at the exact PR head, asserting the SHA.
- **Merge with `gh pr merge N --merge --match-head-commit <sha>`.** Use merge
  commits only. Use `--admin` only for a PR the owner explicitly approved in
  chat.

### Outcome: the same bar gets cheaper and faster

- **The evals plan:** `docs/plans/20260929_evals-and-execution-tags.md`. Pinned
  launch on a commit makes every change to a prompt, model or gate measurable.
- **Seed verifier evals:** the four escaped bugs in the 2026-10-06 retro.

### Outcome: the platform is always moving

- **Pinned helpers in `/Users/neural/Code/Syntropic137/orchestrator-bin`.** They
  avoid the security-hook blocks that `curl $(...)` triggers:
  - `syn137-api` and `syn137` (the CLI built from `apps/syn-cli-node`; the
    npm-installed `syn` has an older YAML parser);
  - `syn137-page` (ntfy pager);
  - `syn137-usage-watch` (pages on a usage-limit failure).
- **`just pit-stop <version>`** for a beta: build, ship, gate, drain, swap,
  verify, ungate, probe. `--swap-only` re-applies config.
- **Resume, don't re-run.** `syn execution resume <id> --acknowledge-external-effects`
  for a run killed by capacity, and `--override-cancellation` for one you
  cancelled.

### Outcome: every lesson compounds

- **The working log:** `/Users/neural/Code/Syntropic137/dogfood-scratchpad.md`
  (log, Queue, HUMAN REVIEW) and `/Users/neural/Code/Syntropic137/papercuts.md`
  (PC-n entries, each with an execution id).
- **Retros:** `docs/retrospectives/` per its README template, with a Scorecard
  comparable to the previous one.
- **The `learning-loop` skill:** escaped bug, then eval case, then one-variable
  change, then measure.

## References

- `references/tick.md`: the orchestrator tick, step by step, with the exact
  commands.
- `references/lessons.md`: the paper cuts and gotchas distilled into what to do
  differently, grouped by area.
- `docs/north-star.md`: the scale targets (20 concurrent now, 100 soon, 1,000 for
  production).
- `docs/retrospectives/2026-10-04-dogfood-orchestrator-day.md`,
  `docs/retrospectives/2026-10-06-merge-down-and-the-dropped-start.md`: the
  baseline scorecards.
- Sibling skills: `dogfooding` (where a task runs, what a workspace can do),
  `learning-loop` (incident to eval case), `workflow-experimentation` (judging a
  workflow change), `devops` (release mechanics).

## Continual improvement

This skill lives at `.claude/skills/orchestrating/` in syntropic137/syntropic137.
After each retrospective:
- update the dated recommendations section;
- add each new anti-pattern with the PR or execution id that showed it;
- move each closed paper cut from `references/lessons.md` to the change that
  fixed it.

When the platform starts orchestrating other apps, split the self-hosting
specifics into `dogfooding` and keep this skill about orchestration itself.
