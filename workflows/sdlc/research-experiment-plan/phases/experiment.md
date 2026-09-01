# Reduce the unknowns by experiment

The revised spec is at `artifacts/input/revise-spec/spec.md`. It ends with a
numbered table of unknowns. Your only job is to settle them by RUNNING things
and recording what happened. You are not revising the spec and you are not
planning; a later phase does both, and it needs measurements from you, not
conclusions.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## First, check each unknown's premise. Do not skip this.

An unknown usually asserts a fact on the way to asking a question. "No workflow
besides `foo.yaml:94` declares X" contains a claim about `foo.yaml:94`. Before
any subagent tests the question, verify the claim it rests on.

This step exists because of a measured failure in this workflow's own first run
(`exec-8d5b14716096`). An unknown asserted that a named file at a named line
declared a particular value. It did not; that value appeared nowhere in the
repository. The experiment phase then reported the unknown "confirmed exactly as
stated, verified with a passing detection-method control". A control was claimed
on a fact that was false. Nothing downstream caught it, because the spec's final
unknowns list is written after the only review phase.

So for each unknown, before dispatching:

- open every file and line it cites and confirm the cited text is actually there
- if a premise is false, the verdict for that unknown is **PREMISE FALSE**. Write
  the verdict file, state what the unknown claimed, show what is actually at that
  location, and do NOT proceed to test the question as posed
- a false premise is a finding, not an obstacle. It is more valuable than a
  resolved unknown, because it means a decision was about to be made on
  something untrue

Report the premise check in the summary as its own line: how many unknowns were
checked, and how many premises failed.

## Dispatch one subagent per unknown, in parallel

Send them in a single message so they run concurrently. Give each one exactly
one numbered unknown, the claim as written, and the settling command the spec
proposed.

**Each subagent writes a verdict FILE to
`artifacts/output/experiments/<n>-<slug>.md`, and replies to you with one line:
the unknown number and its verdict.** Nothing more. You do not re-ingest the
subagent's reasoning, its transcript, or its output. Two reasons: context spent
re-reading findings is context the summary cannot use, and subagent sessions do
not currently land as child sessions (#792), so a finding that lives only in a
reply is a finding that leaves no record. The file IS the record.

## What every verdict file must contain

1. **The unknown, restated** as the falsifiable claim it was.
2. **The exact command run** - copy-pasteable, not described.
3. **Its verbatim output.** Not a summary. A summary of output is a claim about
   output, and the two are not interchangeable.
4. **The verdict**, exactly one of: `RESOLVED`, `STILL UNKNOWN`,
   `UNKNOWN WAS WRONG` (the claim was ill-posed, or its premise was false).
5. **What this changes** in one or two sentences, for whoever revises the spec.

## What counts as evidence

**The evidence must be an artifact that only exists if the thing happened.** A
file that would have been created. A row that would have been written. An exit
code, a log line, a directory that appears.

Asking a model whether something is true, and believing the answer, is not
evidence. In this repository a capability claim was wrong four times in one day
because it was sourced from a model describing itself rather than from an
observable side effect. The form that worked was checking whether a file the
command would have created actually existed.

So: prefer "this path exists now and did not before" over "the run reported
success", and prefer either over "the tool says it supports this".

## Isolate one variable, and always run a control

Change one thing per test. Then run the control: the same test with the change
absent, or with the input the claim says should fail.

A test whose control ALSO passes is measuring the instrument, not the subject,
and it is the exact shape of a test that passes with the change reverted. Report
the control result in the verdict file every time. If you did not run a control,
say that you did not, and say why.

## No silent partial coverage

**Every numbered unknown must produce a verdict file.** Before you write the
summary, list the directory and check the count against the table.

If a subagent failed, timed out, or returned nothing, say so LOUDLY at the top
of the summary and name the unknown by number. Do not quietly proceed with
fewer. A missing verdict must never be readable as a resolved one - that is how
a plan comes to rest on something nobody ever tested while appearing to rest on
measurement.

An unknown that is UNANSWERABLE in this workspace is a legitimate verdict. Write
the file, mark it `STILL UNKNOWN`, and say exactly what blocked it: no
credentials, no network, needs an integration run, needs a rebuilt image. That
is a real finding and the plan phase must be told which decisions rest on it.

## Write to `artifacts/output/experiments.md`

- A table: unknown number, one-line claim, verdict, path to its verdict file.
- **Coverage**: unknowns in the spec, verdict files produced. If those numbers
  differ, that difference is the first line of this document.
- **Contradictions**: every case where the measurement disagrees with what the
  spec asserted. The next phase must correct those, so list them explicitly.
- **Still unknown**: what remains open and what would settle it.

## Rules

- Experiment only. Do not revise the spec, do not write a plan, do not fix code.
- Leave the tree as you found it. If you had to change something to run a test,
  restore it and confirm with `git status --porcelain`.
- The goal is to know, not to finish. A verdict that reports no findings has
  usually not looked, and three honest `STILL UNKNOWN` results beat eight
  confident ones sourced from what a model already believed.
