---
model: opus
timeout-seconds: 3600
---

# Address the review

$ARGUMENTS

The review is at `artifacts/input/review/deliverable.md`. The implement phase's
report, with the PR number and branch name, is at
`artifacts/input/implement/deliverable.md`.

**If the review says `VERDICT: MERGE` with no blockers, change nothing.** Say so
in your output and stop. Do not make cosmetic edits to look busy; an unnecessary
commit on a reviewed branch costs another review round.

Otherwise: this is a fresh container on a fresh clone, so start by getting the
branch from origin.

    git fetch origin <branch> && git checkout <branch>

**Never touch `.github/workflows/`.** The App pushing on your behalf has no
`workflows` permission, so any change under that path makes every push from this
phase fail, including the quarantine push that would otherwise rescue your work.
A run was already lost this way. Write `artifacts/output/deliverable.md` early
and keep updating it, for the same reason: the artifact is the contract, and a
phase that never writes one is failed and torn down.

Fix every BLOCKER. For each one, add or extend a test that FAILS before your fix
and passes after, so the fix is pinned rather than asserted.

Non-blocking findings: fix them only if the fix is small and safe. Otherwise file
a bead with `br create` and leave an inline comment pointing to it. Say which you
chose for each, and why.

If you believe a blocker is wrong, do not silently ignore it. Say which one, and
give the evidence that refutes it: a command and its output, not an argument.

Re-run the gates, then commit and push to the SAME branch so the PR updates. Do
not open a second PR. Then, BEST EFFORT ONLY, `gh pr comment` a short summary of
what changed since the review - and if that fails, note it in your deliverable and
REPORT SUCCESS ANYWAY. The push is the delivery; the comment is a convenience.

## Output

Write to `artifacts/output/deliverable.md`: each blocker and what you did about
it, the commands you ran with their results, the new commit SHA, and whether you
consider the PR ready to land. If it is not ready, say exactly what remains.
