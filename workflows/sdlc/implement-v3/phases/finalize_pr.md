# Mark the PR ready, or leave it draft with the blocker

$ARGUMENTS

The final verification report is **round 3's, and only round 3's**. The
engine runs every round before this phase, so round 3 always ran; a round-3
report that is missing or unreadable is a broken report, not a sign that an
earlier round was the last. Read exactly one file, the first of these that
exists:

1. `artifacts/input/reverify_3/reverify.md`
2. `artifacts/input/reverify_3.md` (the same round's flat alias, kept for one
   release - issue #988)

Never take the verdict from `reverify_2` or `reverify`, even when round 3's
report is absent. Each round handed the open findings to a fix phase and its
`reverify` says whether that fix closed them; round 3 carries a certification
forward when nothing changed, so an older verdict is history either way.
Below, `reverify.md` means round 3's report.

**The report is usable only if its first line is exactly `CERTIFIED` or
`BLOCKED` and its second line is exactly `Round: 3 of 3`.** Anything else -
neither file exists, the report was recovered from a transcript (its first
line is a recovery notice, not a verdict), or the lines do not match - is the
error `FINAL_REPORT_UNUSABLE`. Treat it as BLOCKED: follow "If BLOCKED" below,
name `FINAL_REPORT_UNUSABLE` and what you found instead in the comment, and
never mark the PR ready on it.

The implement phase opened a **draft** PR on its first push and recorded its
number and URL in its artifact. This phase decides what that draft becomes. It
is the only phase allowed to mark it ready (#1197).

Read `reverify.md`, not `verify.md`. The first pass's findings may describe defects the `fix` phase has
since closed; treating them as current is how a good branch gets abandoned.

This workspace has no checkout at all. Work from the remote branch and the PR.

## Find the PR

Use the PR number from the artifacts. If none was recorded, look it up:

```
gh pr list --head <branch> --state open --json number,url,isDraft
```

**If no PR exists** (implement could not open one), create it now from the
existing remote branch, as a draft: `gh pr create --draft --base main --head <branch> ...`.
The branch must never be left without a PR.

## Check the head

Confirm the branch head matches the full SHA `reverify.md` certified or blocked:

```
gh api repos/<owner>/<repo>/commits/<branch> --jq .sha
```

**That SHA, not the one the first pass verified.** Whenever the repair path ran,
the first-pass SHA is the pre-fix head. If they differ, something pushed over
the branch after verification: leave the PR as a draft, comment saying so with
both SHAs, and stop.

## If CERTIFIED

1. Rewrite the PR description (`gh pr edit <n> --body-file <file>`). It must
   contain:
   - what the change does, and the premise check that justified doing it
   - the real command output from verification, not a summary of it
   - each mutation that was run and what it killed
   - what was deliberately not done, and why
   - anything that could not be verified
   - a `## Release notes` section: user-facing, a few lines. The release gate
     uses the PR body as the release description, so this is the changelog.
   - the issue references the task names (`Closes #N` / `Refs #N`)

   Write it for a reviewer who will not read the diff first. Lead with what the
   change claims, then the evidence for that claim.
2. Mark it ready: `gh pr ready <n>`.

## If BLOCKED

Keep it a **draft**. Do not close it. Post one comment (`gh pr comment <n>`)
that names the blocking finding, quotes what `reverify.md` says would close it,
gives the head SHA it applies to, and says how many repair rounds ran (`3 of 3`
means the bound was reached; another round is a person's decision, not this
run's). A draft carrying a known defect with the
blocker written on it is recoverable; a branch nobody can find is not.

Do not merge. Never push, never force push, never rebase.

## Write to `artifacts/output/finalize_pr.md`

**This phase declares a markdown output artifact, so a run that writes
nothing under `artifacts/output/` FAILS - after the work is done, and the
work is lost with the workspace.** Write the file before you finish.

First line: `READY` or `DRAFT`. Then `Repair rounds: N of 3`, the PR URL, the
branch, the head SHA, and - if it stayed a draft - the blocking finding in one
sentence (or `FINAL_REPORT_UNUSABLE` and why).
