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

You are read-only. Do not edit files, do not commit, do not push.

## Post the verdict to the pull request

Writing the verdict to an artifact is not delivering it. A review nobody reads
is indistinguishable from no review, and costs the same. Until this step
existed, every verdict this workflow produced had to be copied to the PR by
hand, and several were nearly missed (#1097).

After writing your deliverable, post it as a comment on the PR you reviewed:

```bash
gh pr comment <PR-NUMBER> --repo <OWNER>/<REPO> --body-file <your-deliverable>
```

The GitHub App credential in this workspace can comment on pull requests -
verified, `syntropic137-swe-mini` has existing PR comments. If the command
fails, report the exact error and the fact that the verdict was not delivered.
Do NOT treat a failed post as a completed phase: the artifact existing is not
delivery.

### Two things the comment must carry

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

If you cannot determine the models, say so rather than omitting the line -
absence reads as "nobody checked", which is the correct impression in that case.

### Do not duplicate

If a comment from a previous run of this workflow already stands on this PR for
the SAME head SHA, do not post a second one. Say so in your deliverable instead.
Repeated identical verdicts train a reader to skip them.
