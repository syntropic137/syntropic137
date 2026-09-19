# Review the decision

A different model chose a path and drafted a plan. Your value is disagreement.
You have `artifacts/input/decide/decision.md`, and for context
`artifacts/input/options/options.md` and `artifacts/input/attack-options/attack.md`.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## Attack the decision

1. **Does the rationale hold?** For each rejected path, is the stated reason
   true? Check it against the code. A path rejected for a false reason is the
   most expensive mistake this workflow can make.
2. **Were the attack findings disposed of honestly?** A finding rejected by
   assertion rather than evidence is a finding still open.
3. **Is the choice one an agent may make?** If it is really a product or
   irreversible decision, say it needs the operator.

## Attack the load-bearing assumptions

The next phase runs experiments aimed at falsifying the decision, so the
assumption list is its target. For each numbered assumption, say which it is:

- **Well-posed** - falsifiable, and the proposed experiment would actually
  falsify it. Keep.
- **Already answered** - the repository settles it; give the `file:line`.
- **Ill-posed** - a topic, not a claim; or an experiment that would pass
  whether the assumption is true or not. Rewrite it.
- **Not load-bearing** - the decision survives either answer. Drop it.

Then: **what load-bearing assumption is MISSING?** Name the claim the decision
quietly depends on that nobody listed, and the experiment that would test it.
This is usually the most valuable finding.

## Attack the plan

A step that does not follow from the decision; a verification step that would
pass with the change reverted; a step resting on an assumption not marked.

## Write to `artifacts/output/review-decision.md`

Findings most severe first, each with the fact, `file:line`, your evidence,
and a specific fix. End with the **revised assumption list** the experiment
phase should run: the kept ones, the rewritten ones, and the missing ones.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it. An abbreviated path is not a smaller citation, it
is an unusable one: a reader cannot follow it and a checker cannot verify it.

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
