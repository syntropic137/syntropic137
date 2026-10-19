# Agent: answer review on an open PR

## Purpose

Collect every review signal on an open PR (inline comments, review summaries,
PR comments, cross-family verifier findings), decide on each, fix what earns a
fix, and leave a trail. If the PR is already merged, use `agent_hotfix.md` or a
small follow-up PR instead.

## Workflow

1. Confirm state: `gh pr view N --json state,mergedAt,headRefName,headRefOid,mergeStateStatus,reviewDecision`.
2. Fetch all three comment channels:
   ```
   gh api repos/syntropic137/syntropic137/pulls/N/comments --paginate   # inline
   gh pr view N --json reviews,comments                                 # summaries + PR-level
   ```
3. If no independent review exists yet, get one from the other model family than the author (Opus-authored -> codex/GPT verifies, and the reverse). Name the concrete risks of this change in the prompt (restart, replay, exit codes, false positives); a generic "check correctness" prompt certifies what it reads. Sonnet is not used as a verifier.
4. Triage, do not implement wholesale. For each finding: fix, or decline with a stated reason the reviewer can contest. Severity decides whether a second pass is earned, not count. Cap: two passes per unchanged scope; after that, escalate to execution (a real test, a real container) rather than another review.
5. Read-only reviews never ran the tests. Before merging on one, check out the head in a worktree and run the PR's targeted tests plus `uv run pytest ci/fitness -q`.
6. Apply fixes in the PR's worktree. If `main` moved, `git merge origin/main` (no rebase), re-run gates, push normally (no force).
7. Reply to each addressed inline comment. New commits after a review are unreviewed: material new code resets the pass count.
8. Hand back to `agent_pr.md` step 8 for the pre-merge re-verify and merge.

## References

- `agent_pr.md` for gates and merge policy.
- `docs/retrospectives/` for incidents where a review missed what execution caught.

## Health check

Depends on: the `gh api .../pulls/N/comments` endpoint shape; `mergeStateStatus`/`reviewDecision` fields in `gh pr view`; `ci/fitness` being the fitness test root; the cross-family verifier policy (owner rule 2026-10-07). If the policy or paths changed, fix this file or report the drift before continuing.
