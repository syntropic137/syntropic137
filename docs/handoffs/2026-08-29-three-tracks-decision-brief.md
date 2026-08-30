# Three tracks, one bottleneck — decision brief

**Date:** 2026-08-29
**Artifact:** https://claude.ai/code/artifact/2569caf5-8972-4ce9-8408-9a08bd057ba3
**Source:** live GitHub state, the self-host API at `100.112.178.5:8137`, and two real workflow executions. Costs are measured, not estimated.

## Snapshot

| | |
|---|---|
| Merged today | 14 PRs into main |
| Main ahead of `release` | 78 commits |
| Issues filed today | 10 (#985–#994) |
| Live runs | 2, $4.42 total |
| Released version | v0.26.0 (what the Mini runs) |

---

## Track 1 — Dogfooding

**Status: working. It found its own limits faster than reading code did.**

`exec-e9ad44461d1f` ran on the Mac Mini against this repo, planned, built, and
opened [PR #992](https://github.com/syntropic137/syntropic137/pull/992) fixing
#989. **$1.09, 18 tool calls, zero tool errors.**

Then it shipped with red CI. The transcript settles why:

| Time | Event | Result |
|---|---|---|
| 22:29:32 | `uv run ruff check .` | exit 2 — submodule packages missing |
| 22:29:41 | `uv run ruff check .` | exit 1 — real lint errors |
| 22:32:00 | PR #992 opened | shipped anyway |

**It could run the checks. It ran them. It ignored the result.** This is not the
#949 workspace gap — it is a single build phase both writing code and judging
whether it is done. That is the argument for phase isolation: separate review,
QA and validation phases do not share the sunk cost.

### Experiment 1 — the planning workflow

`sdlc-research-plan-v1`, three phases, run against #990.

| Measure | Value | Read |
|---|---|---|
| Cost | **$3.32** | 3× the build run, for a document |
| Citations resolving | **13 / 21 (62%)** | mechanically verifiable |
| Hallucinated files | **0** | all 8 failures are real files |
| Cause | abbreviated paths | `routes/artifacts.py` vs the full path |

A good result badly presented: the model invented nothing, it was inconsistent
about path format. One prompt line requiring repo-root-relative paths should
move this toward 100% — cheap and measurable.

**$3.32 is the number to watch.** A plan costing 3× an implementation pays for
itself only by preventing rework, which the scorer now lets us test.

---

## Track 2 — Release

**Status: 78 commits of unreleased work; one PR blocking a clean cut.**

| Item | State |
|---|---|
| PR #992 | red CI — needs the lint fix, then merge |
| Image pins | gated (#984: channel + revision + gitlink) |
| Mini workspace image | `edge` — deliberate test leftover (#987) |

Notable in the 78: delegate double-billing (#940), the pinned-image gate (#984),
cosign on read-only containers (#947), duration rollup (#979 — why the Mini
still reports `duration 0.0`).

Nothing blocks the release except finishing #992. **The version bump and release
PR are the owner's call, not the agent's.**

---

## Track 3 — Bug backlog

| # | Issue | Blocks | Priority |
|---|---|---|---|
| 988 | Phase handoff passes one file, renamed | every multi-phase workflow | **now** |
| 964 | `allowed_tools` + `max_tokens` dead config | per-phase tool focus | **now** |
| 993 | Phase count 0/1 vs 0/3 | trusting the dashboard | soon |
| 991 | Tool counts doubled | reading any tool metric | soon |
| 987 | Deployment image unchecked | knowing what production runs | soon |
| 990 | Binary artifacts corrupted | — | later |
| 989 | Hardcoded workspace paths | — | PR open |
| 994 | Topology visual on a PR | — | experiment |

**#990 downgraded on owner instruction.** Visuals should be posted straight to
the PR rather than growing the database with MP4s and GIFs. Direct-to-PR is the
design, not a workaround. #990 stays open for correctness — silent corruption is
still wrong — but is off the critical path.

---

## Captured, not yet built

| Idea | Where | State |
|---|---|---|
| Four isolated phases, one job each | `sdlc-research-plan-v2` | built |
| SLP skills in research + planning | same, pinned to a commit | built |
| Boundary hardening as a lens | `architecture` skill, 3 phases | built |
| Workflow organisation scheme | `workflows/sdlc/README.md` | built |
| Objective plan scoring | `scripts/score_plan_citations.py` | built |
| Draft PRs → ready fires triggers | compound key already works | design ready |
| Agent reads its own `allowed_tools` | prompt injection | next |
| Tech debt / architecture / devops workflows | README roadmap | planned |
| Topology visual on a PR | #994 | planned |

**Draft PRs — better than expected.** The trigger pipeline builds a compound key
`f"{event_type}.{action}"` and matches it as a plain string with **no
allowlist**, so a rule on `pull_request.ready_for_review` should already fire.
Missing only: workflows opening drafts, and a final phase promoting to ready.

---

## Update — both blockers merged

| | |
|---|---|
| #988 | MERGED (PR #995). A phase hands the next phase its whole output directory. |
| #964 | MERGED (PR #996). `--tools` restricts availability, verified against the live CLI. |
| #992 | CLOSED — see below. |
| #989 | CLOSED as invalid — the premise was wrong. |

**#964 carried a correction.** `max_tokens` is not merely un-forwarded, it is
UNFORWARDABLE: `claude 2.1.251` has no token flag (nearest is
`--max-budget-usd`, in dollars) and `codex 0.147.0` has neither. Declaring it is
now a validation error pointing at `timeout_seconds`.

**#988 carried a pre-existing path traversal.** `PhaseYamlDefinition.id` was
`min_length=1`, so `../../../tmp/owned` validated — and injection joins that to
the HOST-side workspace directory. Reachable by a marketplace workflow author,
who is not necessarily the operator. Fixed with an allowlist grammar plus
independent containment at the sink. Not filed publicly: the repo is public and
the hole was live.

### The dogfooding lesson from #992

Syntropic wrote #992 on the self-host to fix #989. It did exactly what the issue
said. The issue was wrong: all six "hardcoded literals" were inside DOCSTRINGS,
including a `>>>` doctest. The result was three unused imports and documentation
made worse.

**The agent was not wrong; the plan was.** A confident, file-and-line-accurate
instruction that nobody checked against what those lines actually were. CI
caught it only as "unused import" — the shallowest possible symptom of "this
change should not exist."

This is the argument for the research phase being separate and for cross-model
review: both exist to catch a wrong premise before it becomes a PR.

## Release

Nothing blocks it. 80+ commits unreleased. The version bump and release PR are
the owner's call.

**The Mini runs v0.26.0**, which predates #988/#964 — so self-host runs do NOT
yet exercise directory handoff or tool restriction. Any comparison run there
measures phase isolation only.

## Priorities

1. **#988 — directory handoff.** Until a phase can pass its whole output
   directory, every multi-phase workflow is capped at one file per phase. That
   caps the entire dogfooding track.
2. **#964 — make `allowed_tools` real.** Per-phase tool focus is half the value
   of the four-phase design. Interim win: inject the declared tool list into each
   prompt so the agent self-restricts before enforcement lands.
3. **Finish #992, then cut the release.** One lint fix stands between here and a
   clean cut of 78 commits.
4. **Run v1 vs v2 on one task.** Same problem, 3-phase vs 4-phase, with and
   without skills. First real data on whether phase isolation earns its overhead.
5. **Then #993 and #991.** The dashboard currently lies in ways that send you
   debugging things that are fine. Cheap, high trust return.

---

## Caveat worth keeping

Two confident claims were wrong today, both caught only by looking at evidence:

- #988 was reported as "verified" when it had only been read, not executed.
- The dogfood run was said to be unable to run preflight; the transcript shows it
  ran it twice and ignored the result.

Treat confident claims as hypotheses until something executes.
