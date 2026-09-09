# Write the verdict

$ARGUMENTS

The verification findings are at `artifacts/input/verify.md`. This phase composes
what already exists; it does not investigate further. If something needed is
missing, say it is missing rather than filling the gap with reasoning.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## Structure

**Verdict.** One of: the claim holds; the claim holds with caveats; the claim does
not hold. Then one sentence saying why. Put this first - a reader who stops after
the first line should still have the answer.

**Findings**, most severe first. For each:

- what is wrong, stated as a fact about the code
- the hop it lives at, with file and line
- the evidence, quoted from the verification phase, including the command output
- a specific fix, not a direction. "Pass the field at both construction sites"
  rather than "improve field handling"
- how to verify the fix, and the verification must be able to fail. A test that
  exercises the happy path does not confirm a defect is gone

**What was not verified.** Everything the previous phases labelled as
undetermined, carried forward. This section existing is what makes the rest
trustworthy: a review with no limits stated is claiming an omniscience it does not
have.

## Calibration

Do not manufacture findings to look thorough. If the claim holds, say it holds -
a clean review that was genuinely attempted is a real result, and padding it with
style notes buries the fact that the substantive checks passed.

Do not soften a blocker into a suggestion. If a change ships a field that will be
empty on every real run, that is a blocker, and phrasing it as a nice-to-have
misleads whoever merges it.

Mark confidence where it is not total. A finding you are 60% sure of is worth
reporting AS a 60% finding.

You are read-only. Do not edit files, do not commit, do not push, and do not
post to the pull request. This phase is granted `Read`, `Grep`, `Glob` and
`Write` - no `Bash` - and that grant is the boundary, not this sentence.

## Your deliverable is the verdict, not its delivery

Write the verdict to `artifacts/output/deliverable.md` and stop there. Posting
it to the pull request is not this phase's job and is not something this phase
can do.

That is a deliberate decision, recorded here because it is the exact place
someone will next be tempted to reverse it. #1110 added a `gh pr comment` step
to this prompt; the phase had no `Bash`, so three reviews (#1113, #1115, #1117)
each wrote "this needs a tool this phase does not have" and no verdict reached
a PR (#1122). The obvious repair - grant `Bash` - was written, reviewed and
closed unmerged (#1123): `Bash` arrives under `--dangerously-skip-permissions`
with no per-command filter, so granting it at the publication boundary, to a
phase composing text derived from a PR-controlled repository while
write-capable credentials sit in the workspace, buys delivery with an injection
surface.

So the instruction was removed rather than the restriction relaxed. Delivering
the verdict belongs to the platform, after artifact collection, with repository,
PR number and head SHA taken from trusted workflow metadata instead of from an
agent-composed shell command. Until that exists, a human or a later phase
carries the artifact across.

**Do not work around this.** If you find yourself reaching for a tool you were
not granted, the answer is that the phase is scoped correctly and the delivery
step is missing from the platform - say so in your deliverable.

### Two things the verdict must carry

These belong in the artifact whatever eventually delivers it.

**1. The head SHA you reviewed.** A verdict against an old head is how a
reviewer ends up acting on findings that are already fixed - that happened here
and cost a full run. State it explicitly:

```
Reviewed at head `<sha>`.
```

**2. Which model ran each phase.** A verdict is only a cross-model check if the
`verify` phase actually ran on a different harness. A deployed workflow silently
drifted to all-sonnet once (#1107), and the resulting same-model verdict was
indistinguishable from a real gate until someone checked. State it plainly:

```
Gate: investigate <provider>/<model>, verify <provider>/<model>, report <provider>/<model>.
```

Nothing injects per-phase models into this workspace, so you may only be able to
determine them from what the earlier phases wrote in their own artifacts. If you
cannot, say so rather than omitting the line - absence reads as "nobody
checked", which is the correct impression in that case.
