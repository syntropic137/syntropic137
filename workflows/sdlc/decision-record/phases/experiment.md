# Try to falsify the decision

A path was chosen (`artifacts/input/decide/decision.md`) and reviewed
(`artifacts/input/review-decision/review-decision.md`). The review ends with the
revised list of load-bearing assumptions. Your ONLY job is to try to prove the
decision wrong, by RUNNING things against those assumptions and recording what
happened. You are not revising the decision and you are not planning; the final
phase does both, and it needs measurements from you, not conclusions.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## Aim to break it

The decision is the hypothesis. An experiment designed to confirm it will
confirm it. For each assumption, design the test that would most likely expose
it as false, and run that. A decision that survives a genuine attempt to break
it is worth building on; one that was only ever confirmed is not.

## Check each assumption's premise first, against a named revision

Open every file and line an assumption cites, confirm the cited text is there,
and record `git rev-parse HEAD` for the tree you read. If a premise does not
hold, the verdict is **ASSUMPTION WAS WRONG** - quote what is actually there and
name the revision. A working tree moves while a workflow runs, so a check against the
wrong revision produces a confident false accusation.

## Dispatch one subagent per assumption, in parallel

Send them in a single message. Give each exactly one numbered assumption, the
claim, and the falsifying experiment the review settled on. **Each subagent
writes a verdict FILE to `artifacts/output/experiments/<n>-<slug>.md` and replies
with one line: the assumption number and its verdict.** Do not re-ingest its
reasoning: the file is the record.

**Wait for every one of them, in the foreground.** Do not start them in the
background, and do not end your turn while any is still running: in this
environment the end of your turn is the end of the phase, and it kills whatever
is still running. A run lost all seven of its verdicts exactly this way, ending
on "I'll report verdicts once they land". If a subagent comes back without
writing its file, write that assumption's verdict file yourself as
`STILL UNKNOWN`, saying why.

**Where probe code goes.** Under `/tmp/probes/<n>-<slug>/`, with its build
output (`CARGO_TARGET_DIR` and any other cache) under `/tmp` too. Not inside a
cloned repository's working tree: this phase delivers no repository changes,
and uncommitted files there fail the phase (the same run was also failed for
this). Not under `artifacts/output/` either: everything there is collected as
text with no size cap, so build trees flood it and binary files (images,
fonts) are silently corrupted. A probe crate may `path`-depend on the
repository's crates. The verdict file is the durable record, so put the
probe's essential source in it as a fenced block, and describe any image or
binary output by what you measured from it.

## Every verdict file contains

1. **The assumption**, restated as the falsifiable claim.
2. **The exact command run** - copy-pasteable, not described.
3. **Its verbatim output** - not a summary. A summary of output is a claim about
   output.
4. **The verdict**, exactly one of:
   - `HOLDS` - the attempt to falsify it failed
   - `FALSIFIED` - it is false, and the decision is exposed
   - `STILL UNKNOWN` - could not be settled here; say exactly what would settle
     it and where (for example, a step that needs a GPU)
   - `ASSUMPTION WAS WRONG` - ill-posed, or its premise was false
5. **What this means for the decision**, in one or two sentences.

## What counts as evidence

An artifact that only exists if the thing happened: a file created, a row
written, an exit code, a measured number, a log line. Reasoning about what would
happen is not evidence, and a probe that was not actually run must be reported
as STILL UNKNOWN, never as HOLDS.

## Write `artifacts/output/experiment-summary.md`

One table: assumption, verdict, verdict file, one-line consequence. Then a line
stating how many premises were checked, against which revision, and how many
failed. Write this file even if some probes did not finish; an unfinished
probe is a `STILL UNKNOWN` row, not a missing one. Do not modify production
code.

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
