# Agent: Emergency direct-to-main push for a tiny fix

## Purpose

Push a trivial follow-up commit straight to `main` without opening a new PR, when the round-trip cost outweighs the review value. Matches SKILL.md "When to invoke" trigger: "Any decision about whether to push directly to `main` vs open a PR". Authorized by `feedback_push_to_main` for small fixes on already-merged PRs.

## Workflow

1. Confirm the change qualifies for direct-to-main. Allowed:
   - Formatting / lint nits
   - Copilot review nits on an already-merged PR
   - Comment-only changes
   - Typo fixes in docs / strings
   Not allowed (open a normal PR via `agent_pr.md`):
   - Anything that touches runtime behavior
   - Anything that warrants a second pair of eyes
   - Anything that changes public API, schemas, or migrations
2. Work in a worktree on `main` (use `/sdlc:git_worktree`). Never switch branches in the main checkout.
3. Pull latest `main` without rebasing.
   ```
   git pull --no-rebase origin main
   ```
4. Make the change. Run the pre-PR checklist locally - direct-to-main does not skip checks.
   ```
   just fitness-check
   uv run ruff check .
   uv run ruff format --check .
   ```
5. Stage explicit files by name. Never `git add -A`.
6. Commit with a clear, conventional message indicating it's a follow-up.
   ```
   git commit -m "fix: <one line> (follow-up to #<merged-PR>)"
   ```
7. Gotcha: untracked sibling dirs (e.g. `markdown-explorer/`) can cause `just fitness-check` violations on files you never touched. If so, move them outside the repo, push, then restore.
8. Push. Never force-push, never `--no-verify`.
   ```
   git push origin main
   ```

## References

- `agent_pr.md` - the standard flow if the change does not qualify.
- `agent_review_pass.md` - for open (not yet merged) PRs.
- `SKILL.md` "Hard rules" - force-push / rebase / hook prohibitions.
- Memory: `feedback_push_to_main` - the operator preference authorizing this flow.

## Hard rules to honor

- Never force-push to `main` (memory: `feedback_no_force_push`).
- Never `--no-verify`; pre-push hooks fail for real reasons.
- Never use this flow for behavior changes.
- `git pull --no-rebase` only; never rebase.
- No em dashes; pre-push hook blocks them.

## Health check

If this file is out of date with the repository (workflow names changed, file paths moved, hard rules contradicted by current behavior), STOP and:
1. Note the drift in the response to the user.
2. Either fix this file inline (preferred for small drift) or escalate to the user with a one-line summary of what needs updating.

Keeping these skill files healthy is a higher priority than completing the immediate task with a stale recipe.
