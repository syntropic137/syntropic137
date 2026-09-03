# Revise the spec against what the experiments measured

You have:

- `artifacts/input/experiment/experiments.md` - the summary of what was run
- `artifacts/input/experiment/experiments/` - one verdict file per unknown

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

Read the verdict files, not only the summary. The summary is one model's
compression of them, and the command output that decided each verdict is in the
files.

## The problem as stated

$ARGUMENTS

## Check coverage first

Count the numbered unknowns in the spec against the verdict files that exist. If
any unknown has no verdict file, say so at the top of your output and mark it
`STILL UNKNOWN - NOT TESTED`. Do not infer a verdict from the summary's prose. A
missing measurement is not a passing one.

## Fold the measurements in

For each unknown, one of:

- **RESOLVED** - move the answer into the body of the spec as a stated fact,
  citing the verdict file and the command that established it. It is no longer
  an unknown; delete it from the list.
- **STILL UNKNOWN** - keep it in the list, and record what blocked it. The plan
  phase is required to say which decisions rest on these, so the blocker matters
  as much as the question.
- **UNKNOWN WAS WRONG** - remove the unknown and say why it was ill-posed.

## Contradictions get corrected, not softened

**Mark every spec claim an experiment CONTRADICTED, and then remove it or
replace it with what was measured.** Put them in one explicit list so a reader
can see what the experiments overturned.

Do not soften. Turning "X is supported" into "X may be supported" when a
measurement showed it is not preserves the wrong belief and hides the evidence
that killed it. Delete the claim, state the measured fact, cite the verdict file.
Anything downstream that depended on the removed claim must be revisited in the
same pass - if a constraint or a requirement only existed because of it, it goes
too.

## Write to `artifacts/output/spec.md`

The COMPLETE revised spec, standalone. Whoever plans from this should not need
the verdict files to act, though every measured fact should point at one. It
contains:

- the body, with measured facts now stated as facts and cited to their verdict
- **Overturned by experiment** - each contradicted claim, what replaced it
- **Still unknown** - the remaining numbered list, each with its blocker
- **Coverage** - unknowns, verdicts produced, and any gap named

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it - for example
`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/value_objects.py:85`,
never `_shared/value_objects.py:85`.

An abbreviated path is not a smaller version of a citation, it is an unusable
one. `_shared/value_objects.py` matches four bounded contexts in this
repository and identifies none of them, so a reader cannot follow it and a
checker cannot verify it. Measured across three runs: every cited file was
real, and up to 100% of citations were unusable purely because of this.

## Rules

- Read-only against the repository. Revise the document, not the code.
- Do not write a plan. The next phase does that, from this.
- A spec that quietly kept a refuted claim is worse than one that never made it,
  because the refutation was paid for and then discarded.
