# Current bests

**Living document.** For each common task it names the workflow, model or
setting to use today, and the evidence behind it. Skills and runbooks point
here instead of hardcoding workflow ids. A workflow being installed on a
deployment does not make it recommended: `syn workflow list` is what is
available, this file is what is best.

**Last updated:** 2026-10-21 (#2059). The previous edit was 2026-05-02, and
both workflows it recommended are absent from this repository.

## How to read and update this

Each entry names a default, its evidence, and when to override it. Evidence is
one of:

- **eval:** a scored experiment on an eval suite, linked.
- **production:** a preregistered A/B on real tasks, linked.
- **no eval evidence yet:** a default by design, not by measurement. Treat it
  as the next thing to measure.

To change an entry: link the finding that drove it, add a row to
`FINDINGS-LEDGER.md`, mark the old entry superseded, and add a changelog row.
Promote only on the priority order quality, then time, then cost. A result on
a one-phase suite screens; it does not promote a workflow by itself.

Two caveats apply to the 2026-10 experiments below:

- E1-E4 live on PR #2019, **not yet on `main`**. Their paths below are paths
  on that PR's branch. When it lands, add their ledger rows and link them here
  (#2059 acceptance).
- Every experiment so far ran 2-15 tasks per arm. At those sizes a result can
  rule out a large effect at best. Read "ADOPT" as "no evidence of harm", not
  "proven better".

---

## Workflow per kind of work

| Work | Default | Evidence | Override |
|---|---|---|---|
| Behaviour change from an issue | `sdlc-implement-v3` | **no eval evidence yet** against an alternative end to end. Design rationale: `workflows/sdlc/README.md`, and `workflows/sdlc/implement/workflow.yaml` (why implement and verify are separate phases) | `sdlc-implement-v4-precheck`, see Under experiment |
| Change whose diff is its own proof (pins, typos, dead links) | `sdlc-quickfix-v1` | **no eval evidence yet**; the routing test is in `workflows/sdlc/README.md` ("is there anything to prove?") | when in doubt, `implement` |
| Second verification of a ready PR, or rescue of a run that died in verify | `sdlc-reverify-pr-v1 -t "#N"` | **no eval evidence yet** as a workflow; its review prompts are implement-v3's, held identical by `scripts/tests/test_reverify_pr_workflow.py` | verifier on Opus while codex quota is out (README, "Switching the verifier model"); say it is no longer cross-family |
| Research and plan | `sdlc-research-plan-v3` | **no eval evidence yet** | `sdlc-research-experiment-plan-v1` when the plan needs an experiment first |
| PR review | `sdlc-pr-review-v1` | **no eval evidence yet** | `sdlc-pr-review-slp-v1`, unmeasured |
| Decision record, refactor plan, retrospective | `sdlc-decision-record-v1`, `sdlc-refactor-plan-v2`, `sdlc-retrospective-v1` | **no eval evidence yet** | none |

Superseded: `implement-from-plan-v1` and `plan-multiphase-routed-haiku-opus-v1`
(the 2026-05-02 entries). Neither is in this repository; the first existed
only as database state (`workflows/sdlc/implement/workflow.yaml`, "WHY THIS
EXISTS").

### Under experiment

- **`sdlc-implement-v4-precheck`: provisional ADOPT, not final.** Production,
  n=3 per arm: `workflows/sdlc/implement-v4-precheck/EXPERIMENT.md`, Results.
  4 `fix*` phases vs 6, median time to READY ~6.7h vs ~12h (one control
  censored, three slots confounded by incidents), 0 misclassified handoffs, no
  escaped findings so far. The escape window closes **2026-10-30**: re-score
  then, and if it holds, promote it over v3 here in a separate PR. The
  cross-arm finding matters more: in 3 of 6 slots verify certified a head
  whose real-service tests had never run, and orchestrator-run evidence found
  a real defect each time.
- **`sdlc-implement-v5`: built, never run.** Draft PR #2063 (#2060):
  v4-precheck plus declared evidence and structured capability gaps, per
  decision 4 of `docs/plans/20261015_platform-dispatched-evidence.md`. Not on
  `main`, not installed, no runs. **no eval evidence yet.**
- **End-to-end replay (E4):** preregistered on PR #2019
  (`docs/experiments/2026-10-20-end-to-end-replay.md`), not dispatched, blocked
  on the replay target (#2055). Until it runs, no workflow default here has
  end-to-end eval evidence.

## Model per phase

Aliases resolve in `packages/syn-shared/src/syn_shared/agents.py`
(`CLAUDE_MODEL_ALIAS_TARGETS`, `CODEX_MODEL_ALIAS_TARGETS`): `opus` is
`claude-opus-5-5`, `sonnet` is `claude-sonnet-5-5`, `gpt-sol` is
`gpt-6.1-sol`. Record a run's observed model, not the alias.

| Phase role | Default | Evidence | Override |
|---|---|---|---|
| Premise, implement, fix, finalize | `opus` | **no eval evidence yet** that Opus beats Sonnet 5.5 here. E2 (PR #2019, `docs/experiments/2026-10-17-implementer-sonnet-vs-opus.md`, `implementer-seed-v1`, n=10 per arm): Sonnet 5/10 vs Opus 6/10, verdict "proceed", meaning no evidence of a large drop, not equivalence | Sonnet 5.5 on `fix`/`fix_2` only as E3's arm, below |
| Verify, reverify, cross-model review | codex `gpt-sol`, fallback `opus` | **eval:** E1 (PR #2019, `docs/experiments/2026-10-17-verifier-gpt-6-luna-vs-sol.md`, `verifier-seed-v1` train): Sol blocked all 26 defect cases; `gpt-6-luna` REJECTED (b - c = 6, and a false block on a clean control Sol certified) | a run that fell back to Opus is not cross-family; report it as such |
| Fix phases on Sonnet 5.5 | experiment arm only (`sdlc-implement-v4-precheck-sonnet-fix`, on PR #2019) | **production, interim:** E3 (PR #2019, `docs/experiments/2026-10-17-fix-phase-sonnet.md`): provisional ADOPT, rounds and cost clauses met, 0 escapes so far, control n=2 of a planned 6. Final after **2026-11-02** | not a default before the final score |
| Mechanical phases (`quickfix`, `report`, `gather`, `file`) | `sonnet` | **no eval evidence yet** | `opus` when the phase needs judgement |

Not recommended: a verifier on the implementer's model family (it is not
independent), and any retired Claude model (`is_retired_claude_model` in the
same file refuses them).

## Eval suites

| Suite | Version | Measures |
|---|---|---|
| `evals/verifier-seed-v1` | v8 (40 cases, 11 holdout) | verify's catch rate on defects and false-block rate on clean controls, syntropic137 |
| `evals/verifier-seed-aw-v1` | v4 | the same for agentic-workspace |
| `evals/implementer-seed-v1` | v1 | whether an implementer's patch passes hidden tests. Leakage is **not prevented** (its README; #2056) |
| `evals/feedback-screening-v1` | v1 | which feedback screening port keeps injected feedback out (#1970) |

Compare only runs on the same suite version and the same judge: a changed
model, prompt or workflow bumps the version (`evals/verifier-seed-v1/suite.yaml`).
The verifier LLM judge is pinned to `claude-sonnet-4-6`
(`evals/verifier-seed-v1/README.md`); its replacement is #2036 / #2048. Every
suite here screens one phase; none is end-to-end.

## Still believed valid, not re-measured since 2026-05-02

- **Watch an execution with SSE** (`GET /api/v1/sse/executions/{execution_id}`,
  `GET /api/v1/sse/activity`) instead of polling `/executions/{id}`.
- **One phase per deliverable** when a workflow must produce several files.
  Whether a phase still captures only one primary artifact has not been
  re-checked.

The other 2026-05-02 entries (the `claude -p` orchestrator pattern, Playwright
system libraries, workspace cache redirection) depended on workspace image and
platform gaps that have since changed, and their evidence files (`cycle-003/`,
`cycle-004/tick-loop-shape/` and others) are not in this repository. They are
dropped rather than carried forward unverified; git history has the old text.

## Changelog

| Date | Change | Driving finding |
|---|---|---|
| 2026-05-02 | Initial population from cycle 3 + cycle 4 results | F8 (cycle 3), cycle 4 probes |
| 2026-10-21 | Rewritten for the SDLC suite: workflow per kind of work, model per phase, suite versions, each with its evidence or "no eval evidence yet". v4-precheck provisional ADOPT, v5 unrun. Cycle 3/4 workflow entries superseded. | #2059; `implement-v4-precheck/EXPERIMENT.md`; E1-E4 on PR #2019 |
