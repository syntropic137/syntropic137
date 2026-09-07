# Open the pull request

$ARGUMENTS

The verification report is at `artifacts/input/verify.md`.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

**If verification failed, or found a defect, do not open a PR.** Report what
happened and stop. A PR that carries a known defect costs a reviewer more than an
honest failure does.

## If verification passed

The implement phase already pushed the branch; this workspace has no checkout at
all, so nothing is on disk here. Open a PR from the **existing remote branch**
named in the artifacts - you do not need to push anything.

Confirm first that the branch exists on origin and that its head SHA matches the
one verification reported. If they differ, something pushed over it; stop and say
so rather than opening a PR for code nobody verified.

Do not merge. Never force push, never rebase.

The description must contain:

- what the change does, and the premise check that justified doing it
- the real command output from verification, not a summary of it
- each mutation that was run and what it killed
- what was deliberately not done, and why
- anything that could not be verified

Write it for a reviewer who will not read the diff first. Lead with what the
change claims, then the evidence for that claim.

## Output

The PR URL, the branch, and the commit. If no PR was opened, say why in one
sentence at the top.
