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
failed. Probe code goes under `experiments/` in the workspace and is never
committed; do not modify production code.
