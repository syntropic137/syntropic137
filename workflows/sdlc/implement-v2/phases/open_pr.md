# Open the pull request

$ARGUMENTS

The final verification report is at `artifacts/input/reverify.md`. It is the
SECOND verification pass - the first pass's findings were handed to a `fix`
phase, and `reverify` says whether that fix closed them.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

**Open a PR if and only if `reverify.md` certifies.** Its first line is one
word: `CERTIFIED` or `BLOCKED`.

If it says BLOCKED, do not open a PR. Report what it found and stop - a PR
carrying a known defect costs a reviewer more than an honest failure does. The
branch stays pushed, and `reverify.md` is written to tell a future pass what
would close it, so say in your report that the branch is available and name the
blocking finding rather than only that verification failed.

Read `reverify.md`, not `verify.md`. The first pass's findings may well describe
defects that the `fix` phase has since closed; treating them as current is how a
good branch gets abandoned.

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

## Write to `artifacts/output/open_pr.md`

**This phase declares a markdown output artifact, so a run that writes
nothing under `artifacts/output/` FAILS - after the work is done, and the
work is lost with the workspace.** Write the file before you finish, even
if the outcome was a refusal: a refusal is a deliverable and is often the
most valuable one.

The PR URL, or - if no PR was opened - why not, and the branch and commit that were left.
The PR URL, the branch, and the commit. If no PR was opened, say why in one
sentence at the top.
