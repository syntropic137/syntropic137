# Agent: Address Copilot / human review comments on an open PR

## Purpose

Fetch all review feedback on a PR (inline suggestions, summary reviews, PR-level comments), apply fixes, and re-trigger the gate without losing history. Matches SKILL.md "When to invoke" trigger: "Address Copilot review comments". For already-merged PRs route to `agent_hotfix.md` (small follow-ups go direct to `main` per `feedback_push_to_main`).

## Workflow

1. Determine PR state. If already merged, stop and switch to `agent_hotfix.md`.
   ```
   gh pr view <N> --json state,mergedAt,headRefName,baseRefName
   ```
2. Fetch all three comment types in parallel.
   ```
   gh api repos/<owner>/<repo>/pulls/<N>/comments        # inline review comments
   gh pr view <N> --json reviews,comments                # summary reviews + PR-level comments
   ```
3. Triage each item into one of three buckets:
   - Inline suggestion with a code block: apply or explicitly reject with a reply.
   - Summary-only review (approval, request-changes, comment): respond if it raises a concern; otherwise note as acknowledged.
   - PR-level comment: usually a question or context request; respond inline before pushing fixes.
4. Switch into the PR's worktree (use `/sdlc:git_worktree` if not already there). Never switch branches in the main checkout.
5. If `main` has moved since the branch was opened, merge it in (do NOT rebase).
   ```
   git pull --no-rebase origin main
   ```
6. Apply fixes as logical commits. Run the pre-PR checklist before pushing (see `agent_pr.md` step 3).
7. Push to the existing branch. Never force-push, never rebase published history (`feedback_no_force_push`, `feedback_no_rebase`).
   ```
   git push origin <branch>
   ```
8. Reply to each addressed comment so the reviewer sees the trail. Wait for CI green before re-requesting review.

## References

- `agent_pr.md` - pre-PR checklist reused here.
- `agent_hotfix.md` - for already-merged PRs.
- `SKILL.md` "Hard rules" - force-push / rebase / merge prohibitions.
- `.githooks/pre-push` - hook enforcement.

## Hard rules to honor

- Never force-push; if a commit must change, open a new branch + new PR.
- Never rebase onto a moving `main`; merge `main` in instead.
- Never `--no-verify` to bypass hooks.
- No em dashes; pre-push hook blocks them.

## Health check

If this file is out of date with the repository (workflow names changed, file paths moved, hard rules contradicted by current behavior), STOP and:
1. Note the drift in the response to the user.
2. Either fix this file inline (preferred for small drift) or escalate to the user with a one-line summary of what needs updating.

Keeping these skill files healthy is a higher priority than completing the immediate task with a stale recipe.
