# Session start: orient before changing anything

A fresh workflow manager knows nothing about what has run since the skill was
last edited. Spend the first part of a session measuring, because every
decision after it is only as good as the picture it starts from.

## 1. Read the current state of the suite

The main checkout is often a stale branch. Read `origin/main`:
`git fetch origin && git show origin/main:<path>`, or use a worktree at
`origin/main`.

- `docs/experiments/CURRENT-BESTS.md`: the declared default per task class.
  Check its "Last updated" date first. If it predates the newest finding in
  the ledger or in open experiment PRs, the defaults it names are stale, and
  refreshing it is your first job.
- `docs/experiments/FINDINGS-LEDGER.md`: the most recent findings.
- `workflows/sdlc/README.md`: the families and the rules they follow.
- Any `EXPERIMENT.md` under `workflows/sdlc/*/`: open A/B arms and their
  preregistered success criteria.
- `evals/*/README.md` and `suite.yaml`: which suites exist and their current
  version.
- The newest file in `docs/retrospectives/`: its scorecard is the baseline.

## 2. Measure what actually ran

Use the pinned helpers in `/Users/neural/Code/Syntropic137/orchestrator-bin`
(`syn137`, `syn137-api`), not ad-hoc curl. Pull the last two weeks and state
the window in every number you report:

- executions per workflow id and their outcome mix;
- failure classes: vendor or quota, harness, timeout, agent refusal, verify
  blocked (`execution-control` for classification);
- cost and wall-clock per execution and per phase (`observing-sessions`);
- for implement-v3: verify blocked rate, fix rounds used, ready vs left draft,
  and how many of those PRs merged (`gh pr list`);
- trigger history: fired, blocked, and by which guard (`github-triggers`).

## 3. Compare installed with defined

`syn137 workflow list` against `workflows/` on `origin/main`. Drift means
the deployment runs a definition nobody can review. Note it, and fix it
through a reinstall in a PR, never by hand on the VPS.

## 4. Write the picture down

Append a dated status to the working log
(`/Users/neural/Code/Syntropic137/dogfood-scratchpad.md`): top quality gaps,
top cost and time sinks, open experiments, decisions needed from the owner.
Owner decisions go under HUMAN REVIEW with your default and never block work.

## 5. Pick one thing

From the picture, pick the highest-value gap by the priority order: quality,
then time, then cost. Run `improving-a-workflow.md` on it. One variable at a
time.
