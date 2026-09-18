# Frame the problem, and research the paths

Your job has two parts, and you must do both without choosing. A later phase
chooses. If you start recommending here you will stop looking for the path that
beats your favourite, because advocacy feels like progress and hunting for a
better option does not.

## The problem as stated

$ARGUMENTS

## Part 1: frame the problem

Before any option exists, write down what a good answer must do:

- **The problem, restated precisely.** What decision is actually being made?
  If the statement conflates two decisions, split them and say so.
- **Is the problem real, and is it already solved?** Search the repository
  first: design docs, ADRs, existing experiments, prior plans, and the code.
  This repository usually has more written design than it looks like. A
  question that is already answered is a successful finding here. Do not stop:
  make the existing answer **Path 0**, cite exactly where it was decided, and
  still lay out the alternatives. The later phases then test whether that
  answer still holds, and reaffirming it is a legitimate outcome.
- **Success criteria** - observable, so a later phase can test a path against
  them.
- **Constraints** - ADRs, invariants, platform targets, anything a path may not
  break. Cite each.
- **Non-goals** - what this decision deliberately does not settle.

## Part 2: research the paths

Lay out **at least three genuinely different paths**, and more if they exist.
Genuinely different means a different mechanism, not the same idea with a
different parameter. If the repository's prior design already names options,
start from those, and add any it missed.

For EACH path:

- **How it works** - concretely, against this codebase, with `file:line` for
  every existing piece it builds on.
- **What it costs** - build effort, runtime cost, complexity it adds, what it
  forecloses later.
- **What it assumes** - every claim the path depends on that you have not
  verified. Mark each VERIFIED (you read or ran it) or ASSUMED.
- **How it fails** - the most likely way this path goes wrong in practice.
- **Evidence** - prior art, measurements, or code that bears on it.

Include the **do-nothing or minimal path** as one of them when it is plausible.
It is the baseline every other path has to beat.

Then a **comparison table** across the success criteria. Do not total it or
pick a winner.

## Write to `artifacts/output/options.md`

**Write it in sections, not in one call.** Create the file with its first
section, then add each further section with a separate edit. A single write of
a long document can exceed the model's output limit, and a cut-off tool call
is discarded whole: a run ended here with 15 minutes of drafting and nothing
written.

Sections: Problem, Is it real / already solved, Success criteria, Constraints,
Non-goals, Paths (one subsection each), Comparison.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it. An abbreviated path is not a smaller citation, it
is an unusable one: a reader cannot follow it and a checker cannot verify it.

## Rules

- Do NOT recommend, rank or choose. Describe.
- Every factual claim carries a `file:line`, or is marked ASSUMED.
- Do not modify any file outside `artifacts/output/`.
