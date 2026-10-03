# Final plan and decision record

You have everything the workflow produced:

- `artifacts/input/options/options.md` - the framing and the paths
- `artifacts/input/attack-options/attack.md` - the attack on the paths
- `artifacts/input/decide/decision.md` - the decision and draft plan
- `artifacts/input/review-decision/review-decision.md` - the review of it
- `artifacts/input/experiment/experiment-summary.md` and
  `artifacts/input/experiment/experiments/` - the falsification attempts

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## First: did the decision survive?

Read the experiment verdict files yourself; do not trust any document's account
of them.

- If any load-bearing assumption was **FALSIFIED**, the decision does not stand
  as written. Either amend it so it no longer depends on the false claim, or
  switch to the path the decision named under "what would change this
  decision", and say which. Do not paper over a falsified assumption.
- If an assumption came back **ASSUMPTION WAS WRONG** because its premise was
  false, the decision rests on something untrue: treat it exactly like
  FALSIFIED. If it was only ill-posed, restate it as a falsifiable claim and
  mark it STILL UNKNOWN.
- If an assumption is **STILL UNKNOWN**, every step resting on it is marked as
  such, with what would settle it.
- An assumption whose summary row still says **PENDING**, or that has no verdict
  file at all, was never settled: the experiment phase stopped before it. Treat
  it as STILL UNKNOWN, and say in the record that it was not tested, not that
  it was tested and came back unknown.

## Dispose of every review finding

**Accept** (and say what changed) or **reject** (with `file:line` or a verdict
file). Where a finding and a measurement disagree, the measurement wins.

## Write `artifacts/output/decision-record.md` - the final artifact

**Write it in sections, not in one call.** Create the file with its first
section, then add each further section with a separate edit. A single write of
a long document can exceed the model's output limit, and a cut-off tool call
is discarded whole: a run ended here with 15 minutes of drafting and nothing
written.

A standalone document. Whoever reads it should not need the others, though
every risky claim still points at the evidence behind it. It contains:

- **Problem** - the decision being made, and its success criteria
- **Paths considered** - each, in two or three lines
- **Decision** - one sentence, and whether it needs operator ratification
- **Rationale** - why this path beats each alternative, criterion by criterion
- **Rejected paths** - each with its reason, so it is not re-litigated without
  new evidence
- **Evidence** - each load-bearing assumption, its verdict, and its verdict file
- **What would change this decision** - the evidence, and the path it points to
- **Plan** - steps, `file:line` targets, verification per step, out of scope;
  each step resting on an open assumption marked, with what happens if it goes
  the other way
- **Risks**

Then:

## Review disposition

| finding | accepted / rejected | what changed |

Every finding from both reviews gets a row. A finding silently dropped looks
identical to one that was considered and rejected, and only one of those is
honest work.

## Readiness

One line: ready to implement; ready once the operator ratifies the decision; or
blocked on a named, specific unknown. Saying it is blocked is a correct outcome.
**"Ready" is allowed only if no load-bearing assumption is still unknown,
untested or pending** - or if you have amended the decision and plan so that
they no longer depend on it, and said how. Otherwise the line is "blocked on",
naming each one and what would settle it.
This workflow exists to make a decision that holds up, not to manufacture the
appearance of one.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it. An abbreviated path is not a smaller citation, it
is an unusable one: a reader cannot follow it and a checker cannot verify it.

## Rules

- Plan only. No production code, no commits.
- A verification step that would pass with the change reverted is worse than
  none, because it will be believed.

## End with exactly this, and nothing after it

Your document is the deliverable; the status block only says whether you
produced it. End your final message with these two lines, verbatim in shape:
`"success"` and `"comments"` are the only keys, the comment is one short
sentence on one line with no double quotes inside it, and `TASK_RESULT_END` is
on its own line. Every detail belongs in the file you wrote, not here. Three
runs of this workflow completed their document and were still failed because
the block had no `"success"` key (they wrote `"status": "complete"`), which the
platform reads as an unreadable verdict.

```text
TASK_RESULT: {"success": true, "comments": "Wrote artifacts/output/<file> with <n> sections."}
TASK_RESULT_END
```

If you could not produce the document, use `"success": false` and say why in
the comment.
