---
name: workflow-experimentation
description: Use when designing, running, or judging an experiment on a Syntropic137 workflow - comparing prompt variants, fan-out vs single agent, adversarial cross-model review, model selection (can Haiku do this job), phase splits, or tool grants. Trigger phrases include "run a workflow experiment", "A/B the workflow", "does fan-out help", "which model for this phase", "is this prompt better", "measure review quality", "why did the workflow do that". Do NOT use for a one-off workflow run that is just doing work, for authoring a workflow that is not being compared against anything, or for debugging a single failed execution (that is ordinary debugging).
---

# Workflow Experimentation

Workflows are how this platform does its own engineering, so a better workflow
compounds across every future task. That makes workflow design worth measuring
rather than guessing at - and measuring it is harder than it looks, because
almost every cheap signal here is a lie. A green check does not mean the effect
occurred. A declared capability does not mean it was granted. A capability that
was granted does not mean it was used.

## Outcomes we are looking for

### Outcome 1: quality first, and quality means less rework

The goal is not a review that sounds thorough. It is a change that does not come
back. Rework is the cost that dominates everything else, because a defect that
reaches main is paid for again in a later review, a later execution, and a later
context window.

- *Signal:* a PR that a workflow certified does not later acquire findings from a
  human or a second reviewer.
- *Signal:* the share of executions whose work is discarded (failed after the
  expensive phases) trends down.

### Outcome 2: security and correctness are not traded for speed

A faster workflow that publishes unverified work is not faster; it moved the
cost somewhere less visible.

- *Signal:* no experiment ships a variant that removes a verification phase
  without an explicit, recorded owner decision.
- *Signal:* capability changes (tool grants, publication rights) are measured for
  what they actually enable, not what they appear to declare.

### Outcome 3: cost and latency fall only AFTER quality holds

Model downgrades, phase merges and budget cuts are optimisations, and an
optimisation applied before quality is established just locks in the defect rate.

- *Signal:* every cost reduction cites the quality measurement that stayed flat.
- *Signal:* "what is Haiku good enough for" is answered per phase with evidence,
  not adopted wholesale.

### Outcome 4: each experiment moves exactly one variable

- *Signal:* the arms differ in one phase, one prompt, or one model - and the
  write-up names what was held constant.

### Outcome 5: rough edges become filed features, not folklore

An experiment that hits a platform limitation and works around it silently
leaves the next experimenter to rediscover it.

- *Signal:* every limitation hit during an experiment leaves an issue with a
  reproduction.

## Principles

1. **Instrument the mechanism, not the outcome.** Before comparing arms, prove
   the treatment actually happened. Check the event stream for the tool you
   expect (`Skill`, `Task`/`Agent`), not the agent's prose claim that it used
   one. Declared skills went uninvoked for months because nobody checked the
   stream (#1269).

2. **Reuse control arms that already ran.** Stored executions are a free control
   group. If the current workflow already reviewed the target head, that IS the
   control - do not pay to re-run it. Read the stored record, not current code.

3. **Pre-register the honest outcomes, including "no difference".** State the
   possible results in the dispatch prompt, with "the treatment adds nothing" as
   a legitimate one. A treatment arm that knows it cost more than the control is
   under pressure to justify itself, and that pressure produces findings.

4. **Ground truth beats plausibility.** Score against known defects - a PR with
   documented review findings, a bug with a reproduction, a mutation you
   introduced. "The review reads better" is not a measurement.

5. **Adversarial means a different model, and blind means blind.** Cross-model
   review finds blind spots because the second model does not share the first's
   priors. That value evaporates if the second model is handed the first's
   conclusions as a starting point. Give it the artefact, not the verdict.

6. **State the window and the sample size in the conclusion.** Three executions
   are three executions. A trend across rolling windows on small samples is
   usually an artifact.

7. **Re-derive numbers a subagent reports before acting on them.** Analysis
   agents miscount. Verified example: an agent reported 55 `just: command not
   found` and 50 `uv: command not found` across a transcript corpus; the real
   count for both was **zero**, from loose pattern matching. Its tool-frequency
   table, checked the same way, reproduced exactly. Check the load-bearing
   numbers, not all of them.

8. **Prefer the existing instrument to a new one.** `software-leverage-review`
   already encodes a fan-out design with a coverage gate, deterministic dedup
   correction, and script-rendered output. Hand-rolling a fan-out prompt
   reproduces a worse version of it.

## Platform constraints that shape every experiment

These are measured, not assumed. Each one has invalidated an experiment design
here at least once.

| Constraint | Consequence for design |
|---|---|
| `allowed_tools` restricts **nothing** - the platform passes `--allowedTools` (which only waives permission prompts) alongside `--dangerously-skip-permissions`; `--tools` is the restricting flag and is never passed (#803) | You cannot create a restricted arm this way. But agents *believe* the list and self-censor, so the declaration is a strong prompt-level nudge - use it as one, and never as a security control |
| `execution_type: parallel` is **refused at authoring time** (#1039) | Fan-out happens inside one phase via the Agent tool, never across phases |
| Subagent dispatch is **one level deep** | An orchestrator that is itself a subagent cannot fan out. A syn137 phase is a top-level `claude -p`, so it can - verify this in the stream rather than assuming |
| `syn workflow install` reports success while **silently dropping** unrecognised phase fields (`can_open_pr` never reached the event store, #1285) | After installing a variant, confirm the field persisted before trusting the arm |
| A phase prompt that supplies a complete numbered procedure **suppresses skill routing** (#1269) | If the arm depends on a skill firing, name the skill explicitly; do not rely on description routing |
| Phases are separate processes; artifacts pass at `artifacts/input/<phase-id>.md` | Renaming a phase id silently breaks the phase after it |

## Designing an experiment

1. **Write the hypothesis as a falsifiable sentence.** "Fan-out across leverage
   points finds defects a single generalist reviewer misses" - not "fan-out is
   better".
2. **Pick the target for its ground truth**, not its convenience. A PR with
   documented findings, or a head a previous reviewer already judged.
3. **Build the treatment as a new workflow id.** Never edit the control; it is
   the baseline and it must stay comparable. Copy the untouched phases
   byte-for-byte so the diff is inspectable.
4. **Hold models and phase count constant** unless the model IS the variable.
5. **Name the instrumentation** you will read afterwards: which tool names in the
   stream, which stored fields, which artifact.
6. **Pre-register outcomes** in the dispatch prompt, as in principle 3.
7. **Run it**, then judge from stored records rather than the agent's summary.

## Judging an experiment

Ask in this order, and stop at the first failure:

1. **Did the treatment actually occur?** Tool present in the stream, skill
   installed at the right path, field persisted. If not, the experiment measured
   nothing and the result is void - say so rather than reporting the comparison.
2. **Was coverage complete?** If eight lenses were dispatched and six returned,
   the review certified two unexamined areas as clean. Partial coverage is a
   failed run, not a cheaper one.
3. **Do the findings survive verification?** Count only findings with a
   `file:line` and a failure path that a second pass confirms.
4. **What did it cost per real finding**, including the discarded arms?
5. **Only then**, is the quality difference worth the cost difference?

## Model selection, when quality is established

The question is never "is Haiku as good as Opus". It is "which phases have a
quality bar Haiku clears". Phases differ enormously: composing a verdict from
findings that already exist is not the same job as tracing a call path across
packages to find one.

Run model selection per phase, against a phase whose quality measure is already
defined, and only after the workflow's quality is stable. A cheaper model
adopted during a quality change confounds both.

## Rough edges are deliverables

When an experiment is blocked or distorted by a platform limitation, that
limitation is a finding of the experiment. File it with a reproduction, and say
in the write-up which part of the design it forced. The constraints table above
was built entirely from experiments that hit them.

## References

- `software-leverage-review` (in `syntropic137/software-leverage-points`) - the
  canonical fan-out orchestrator: coverage gate, deterministic dedup correction,
  action matrix, maturity calibration. Read it before designing any fan-out.
- `workflows/sdlc/pr-review/` - the control arm for review experiments.
- `docs/architecture/agent-recipe-architecture.html` - ARCH-001, the recipe
  standard (EXP-V1-0005); proposed, not normative.
