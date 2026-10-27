---
name: managing-workflows
description: Use when acting as the workflow manager for Syntropic137 - owning the SDLC workflow suite, its evals and its triggers as a product. Covers deciding which workflow a kind of work goes through, improving a workflow's quality and then its cost and time, judging whether a prompt, model or phase change is proven, designing the draft-to-ready PR lifecycle, and deciding when triggers should fire. Trigger phrases include "you are the workflow manager", "start as workflow manager", "improve our SDLC", "which workflow should handle this", "make the workflow cheaper without losing quality", "is v4 better than v3", "promote this workflow", "what do our evals say", "eval coverage", "evals for the whole workflow", "draft PR lifecycle", "when should this trigger fire", "triggers fire too often", "workflow suite health". Do NOT use for running one workflow (syn-workflow), diagnosing one execution (execution-control), workflow YAML mechanics (authoring-workflows), the dispatch, land and deploy loop (orchestrating), or the detailed design of one A/B (workflow-experimentation).
---

# Managing Syntropic137 workflows

The workflow manager owns the workflows themselves: the SDLC suite under
`workflows/sdlc/`, the eval suites under `evals/` that measure it, and the
trigger rules that start it. The orchestrator (see `orchestrating`) runs work
*through* those workflows. The manager decides what the workflows *are* and
proves each change. The priority order never changes: **reach the quality bar
first, then hold that bar while cutting cost and time.** A change that is
cheaper but unmeasured is a regression nobody has noticed yet.

## Outcomes we are looking for

### Outcome 1: what the workflows certify is correct

- *Signal:* PRs the suite marks ready do not later pick up findings from a
  second verifier, a human or production. Every escape becomes an eval case.
- *Signal:* verifier suites show a rising catch rate on defect cases and a
  false-block rate near zero on clean controls, both on the holdout split.

### Outcome 2: every workflow change is proven before it is promoted

- *Signal:* every entry in `docs/experiments/CURRENT-BESTS.md` links a finding
  in `FINDINGS-LEDGER.md` backed by eval runs, not anecdotes.
- *Signal:* no model, prompt or phase change reaches the default workflow
  without a baseline and a comparison on the same suite version.

### Outcome 3: the same bar gets cheaper and faster

Only once Outcomes 1 and 2 hold.

- *Signal:* cost and wall-clock per ready PR fall between retros while the
  escape rate holds.
- *Signal:* repair rounds spent on things a workspace cannot fix (flake, CI
  gaps, Docker-only evidence) fall.

### Outcome 4: work moves through a lifecycle a human can read

- *Signal:* a PR's state says where it is: draft while agents work, ready only
  when verified and mergeable.
- *Signal:* triggers fire on lifecycle transitions, not on noise. No PR gets
  two agents on one branch, and no trigger exhausts its limits on one PR.

## Principles

1. **Evals before opinions.** A workflow change is a hypothesis until a suite
   scores it. Run the baseline and the variant on the same suite version and
   change one variable at a time, because two changed variables answer no
   question. See `references/evals.md`.

2. **End-to-end is the real eval; single phases screen.** One-phase suites
   (verifier-seed, implementer-seed) are cheap filters. The decision that
   matters is whether the whole workflow, from a commit and an issue to a
   graded PR, got better. Do not promote on a screening result alone.

3. **Cross-family verification.** Opus implements and a GPT/codex model
   verifies, or the reverse. A verifier on the implementer's model is no longer
   independent, so say so whenever one is used. Cheaper models are allowed only
   with eval proof that the bar holds.

4. **One job per phase, and the workflow id is immutable.** A phase that both
   researches and plans stops researching early. A run references its workflow
   id, so changing a phase means a new `-vN` or a named arm, never an edit
   to a definition that has already run. See `references/building-a-workflow.md`.

5. **Draft until proven, ready when mergeable.** Agents open a draft PR on
   their first push. `finalize_pr` marks it ready only on a certified verify.
   Ready-for-review is a promise to the reviewer, so nothing un-verified wears
   it. See `references/lifecycle-and-triggers.md`.

6. **Triggers follow transitions, with limits sized before enabling.** Fire on
   the event that changes what should happen next (ready, review submitted, CI
   failed on a ready PR), not on every push. Every rule carries attempts,
   cooldown and a daily limit, because a trigger has no spend limit.

7. **A workspace says what it cannot do; the orchestrator routes it.** A
   verify or fix phase that needs a tool the workspace lacks and cannot
   install (Docker, a database, a live API) records a capability gap with the
   exact command, instead of spending a round. The orchestrator sends that
   evidence to a workspace that has the capability (CI evidence today; a
   capable pool such as E2B once capability matching lands, #2060). The
   workspace abstraction is plug and play, so a workflow never assumes one
   runtime.

8. **Judge by the stored record.** Status `completed` describes the harness,
   not the outcome. Read the PR, the phase reports and the stored error before
   classifying a run, and never judge a past run by today's code.

9. **Write down what you learn where it lasts.** Findings go to the ledger,
   defaults to CURRENT-BESTS, escapes to eval cases, and recurring friction to
   an issue. A lesson that lives only in a chat is lost.

## Which skill when

| You need to | Use |
|---|---|
| orient at the start of a session | `references/session-start.md` (this skill) |
| start a run, read a workflow's inputs, install a workflow | `syn-workflow` |
| understand why a run failed, resume or cancel it | `execution-control` |
| see what a session did or cost | `observing-sessions`, `discovering-run-sessions` |
| write or change workflow YAML, phases, prompts, agent blocks | `authoring-workflows` |
| design and judge one A/B in detail | `workflow-experimentation` |
| turn an escape or incident into an eval case or retro | `learning-loop` |
| find patterns across a batch of runs | `mining-session-logs`, `langfuse-learning-loops` |
| register, tune or debug a trigger rule | `github-triggers` |
| decide workspace or local for one task | `dogfooding` |
| dispatch, land PRs, deploy a beta | `orchestrating` |
| PR, release and CI mechanics | `devops` |
| hand a verification to codex outside a workflow | `delegating-to-codex` |
| install or publish a workflow package | `workflow-marketplace` |

## Processes

Each is a reference loaded only when you run it.

| Process | When | Reference |
|---|---|---|
| Session start | first thing in a fresh session | `references/session-start.md` |
| Improve a workflow | quality gap, cost or time sink, model swap | `references/improving-a-workflow.md` |
| Build or vary a workflow | no workflow fits, or an A/B arm | `references/building-a-workflow.md` |
| Run and read evals | before and after any workflow change | `references/evals.md` |
| Lifecycle and triggers | PR states, trigger rules and cadence | `references/lifecycle-and-triggers.md` |

## Anti-patterns

Observed in this repo:

- **Promoting on a screening result.** A verifier suite says one phase blocks
  bugs. It says nothing about whether the workflow ships fewer of them.
- **Comparing runs across suite versions or changed models.** The suite records
  the workflow id and each phase's model, and `scripts/tests/test_eval_suite.py`
  fails on disagreement. Changing the model without bumping the suite makes two
  "same" runs incomparable.
- **Clean controls that are not clean.** Both strong verifiers blocking a
  "clean" control turned out to be a real Redis retry bug (#1756). Investigate
  before calling it a false block.
- **Implementer eval harness traps.** Dirty trees, unstated interface
  contracts, or task text that leaks the fix all measure the harness, not the
  agent. See `evals/implementer-seed-v1/README.md`.
- **Repair rounds on unfixable evidence.** Verify spent fix rounds on flakes,
  CI gaps and Docker-only evidence a workspace cannot produce. This is what
  `implement-v4-precheck` is testing.
- **A trigger with no draft filter.** The `self-healing` preset fires on any
  failed check of any PR, drafts included, while implement-v3 still owns that
  branch. `review-fix` filters drafts out; self-healing does not
  (`trigger_presets.py`).
- **A verdict that does not gate.** 2026-10-01 to 10-21: 17 of 23 v3 PRs
  left draft as blocked merged anyway, and only 86 of 200 merged workflow PRs
  were certified on the head they merged at (#2057). If draft-blocked can
  merge, ready means nothing. Every merge of a blocked PR should trace to a
  later certified verdict on that head.
- **Verify as the first quality check.** v3's first verify blocked 92% of runs
  (n=105), and 2+ fix rounds cost about 2.3x a clean run. Quality found in
  verify is quality the implement phase did not build in.
- **Fix rounds on evidence a workspace cannot produce (#2060).** At least 19
  of 85 fix-phase refusals in the same window cited Docker, integration,
  database or live-API evidence. Route that to the orchestrator; do not spend a
  round on it.
- **Installed probes nobody archives.** 61 workflows installed, many stale
  probes not in the repo. An agent picking from `workflow list` can choose one.
The window, source and definition of each number above are in
`references/audit-2026-10-21.md`.

- **Shared prompts edited in one place.** `reverify-pr/phases/` copies
  implement-v3's prompts, and a test fails when they diverge (one allowed
  substitution: verify reads `prepare.md` for `implement.md`). Change both.

## Recommended tools and practices (as of 2026-10-23)

### Outcome: what the workflows certify is correct

- **`docs/experiments/CURRENT-BESTS.md` decides the default workflow.** As of
  its #2066 refresh it names `sdlc-implement-v3` for behaviour changes
  (premise, implement with a draft PR, codex verify, up to two fix and
  re-verify rounds, then `finalize_pr`; Opus and codex `gpt-sol`). If this
  line and CURRENT-BESTS disagree, CURRENT-BESTS wins.
- **`sdlc-quickfix-v1`** only when the diff is its own proof; the test is in
  `workflows/sdlc/README.md`.
- **`syn workflow run sdlc-reverify-pr-v1 -t "#N"`** as the second verifier and to rescue a run
  that died in verify.

### Outcome: every change is proven

- **`scripts/eval_suite.py check|launch|score`** for verifier suites and
  **`scripts/eval_implementer.py check|admit`** plus the container referee
  **`scripts/eval_referee.py`** (scores and records) for implementer suites.
- **`docs/experiments/CURRENT-BESTS.md` + `FINDINGS-LEDGER.md`** as the only
  place a default is declared.
- **Preregister an A/B arm**, as `workflows/sdlc/implement-v4-precheck/EXPERIMENT.md`
  does, before running it.

### Outcome: cheaper and faster

- **`observing-sessions` cost by phase** to find the phase worth optimising
  before touching anything.
- **Model downgrades need eval proof.** Opus is the default; Sonnet 5.5 needs a
  passing suite; never run pre-5 models.

### Outcome: a readable lifecycle

- **Trigger presets** (`self-healing`, `review-fix`, `comment-command`) carry
  tested conditions and limits; see `github-triggers`.
- **`just check-workflows`** before any workflow PR. It enforces phase-id prompt
  names and the no-hardcoded-gates rule.

## References

- `references/session-start.md`: what to read and measure in the first hour.
- `references/improving-a-workflow.md`: the improvement loop, from finding the
  gap to promotion.
- `references/building-a-workflow.md`: new workflows and A/B arms, built with
  engineering discipline.
- `references/evals.md`: suites, commands, admission and reading scores.
- `references/lifecycle-and-triggers.md`: the PR lifecycle and trigger design.
- `references/audit-2026-10-21.md`: the baseline audit behind the numbers in
  Anti-patterns.
- `workflows/sdlc/README.md`: workflow organisation, implement vs quickfix,
  gates, timeouts.
- `docs/north-star.md`: the scale targets every design is judged against.

## Continual improvement

This skill lives at `.claude/skills/managing-workflows/`. When a finding is
promoted, update the dated recommendations section, and when an anti-pattern
is observed, add it with the PR or execution id that showed it. Facts that churn
(which workflow is default, which models) belong in `CURRENT-BESTS.md`. Link
to it rather than copying into this skill.
