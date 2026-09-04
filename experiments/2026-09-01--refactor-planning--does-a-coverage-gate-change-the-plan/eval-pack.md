# Eval pack (FROZEN at hypothesis commit)

Edits to this file after the first `runs/` artifact invalidate the probe. If it
is wrong, start a new probe rather than rewriting the spec to fit the data.

## The six runs

Each row is one execution. Task strings are identical within a target and vary
only by workflow.

| Run | Condition | Workflow | Target |
|---|---|---|---|
| A1 | baseline | `sdlc-research-plan-v3` | `_wiring.py` |
| A2 | baseline | `sdlc-research-plan-v3` | `WorkflowExecutionProcessor.py` |
| A3 | baseline | `sdlc-research-plan-v3` | `lifecycle.py` |
| B1 | gated | `sdlc-refactor-plan-v1` | `_wiring.py` |
| B2 | gated | `sdlc-refactor-plan-v1` | `WorkflowExecutionProcessor.py` |
| B3 | gated | `sdlc-refactor-plan-v1` | `lifecycle.py` |

## The task string

Identical across both arms for a given target. `<TARGET>` and `<LINES>` are
substituted; nothing else changes between conditions. Note it does NOT mention
coverage or tests - mentioning them would hand the baseline arm the answer and
destroy the comparison.

```
Plan a refactor of <TARGET> (<LINES> lines), which exceeds this repo's 750-line
fitness threshold. Produce a plan only - do not modify code. Cover what the
module owns, how it should be decomposed, and in what order the work should be
done so the build stays green throughout.
```

## Scoring rubric

Each prediction is scored from run artifacts, with an evidence path.

### P1 / P2 - did a coverage command actually run

- **Evidence:** the phase transcript plus `/api/v1/events/sessions/{id}/tools`.
- **Counts as YES** only if a coverage tool was INVOKED (`pytest --cov`,
  `coverage run`, or equivalent) and its output appears in the transcript.
- **Counts as NO** if coverage is discussed, estimated, or asserted without an
  invocation. Discussing coverage is not measuring it, and the distinction is
  the entire point of the probe.

### P3 - gate verdict

- **Evidence:** the `coverage-gate` phase artifact.
- Scored by which of the three verdict headings it emits. Absence of any
  verdict heading scores as a prompt failure, not as a verdict.

### P4 - what the plan leads with

- **Evidence:** the final artifact of each arm.
- **"Leads with test work"** = the first actionable section specifies tests to
  write before any extraction step.
- **"Leads with a split"** = the first actionable section proposes a module or
  file layout.
- Judged on the FIRST actionable section, not on whether tests are mentioned
  anywhere. Every plan mentions tests somewhere; that is why the ordering is
  the measurement.

### P5 - cost

- **Evidence:** `total_cost_usd` per execution from `/api/v1/executions/{id}`.
- Scored on the mean of the three runs per arm, against the pre-captured v3
  baseline mean of $5.83.

### P6 - which harness ran the review phase

- **Evidence:** the `cross-model-review` phase's session transcript.
- `cost_by_model` is NOT sufficient evidence: it records the DECLARED model and
  will report `gpt-5.6-sol` whichever binary ran. That is precisely the trap
  this prediction exists to expose, so the transcript's own shape - which
  harness emitted it - is the only admissible evidence.

## Out of scope

- Plan QUALITY as judged by a human. This probe measures structural properties
  that can be scored from artifacts. Whether the gated plan is *better* to
  execute is a separate question needing a human or an execution trial.
- The other seven oversized modules.
- `agentic-primitives` files: separate repo, image-rebuild delivery tax.
- `interactive_tmux.py` (2503 lines, the largest): it is a DELETE target per the
  excision decision, so planning its refactor would be actively wrong.

## What invalidates a run

- Execution fails before its final phase.
- The workspace cannot run the repo's test tooling at all.
- A task string differing between arms for the same target.
