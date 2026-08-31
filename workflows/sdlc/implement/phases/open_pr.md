# Open the pull request

$ARGUMENTS

The verification report is at `artifacts/input/verify.md`.

**If verification failed, or found a defect, do not open a PR.** Report what
happened and stop. A PR that carries a known defect costs a reviewer more than an
honest failure does.

## If verification passed

Push the branch and open a PR against `main`. Do not merge it. Never force push,
never rebase.

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
