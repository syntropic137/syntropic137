# Agent: Open a normal feature/fix PR against `main`

## Purpose

Get a feature/fix branch from local working state to a green, reviewable PR against `main` without burning CI round-trips on issues that should have been caught locally. Use this for any non-release PR. Matches SKILL.md "When to invoke" triggers: "Open a PR", "create a pull request", "submit my changes". For tiny follow-ups on already-merged PRs see `agent_hotfix.md`. For `main -> release` PRs see `agent_release.md`.

## Workflow

1. Create an isolated worktree (never switch branches in the main checkout).
   ```
   /sdlc:git_worktree
   ```
2. Initialize submodules and dependencies in the fresh worktree.
   ```
   git submodule update --init --recursive
   pnpm install
   uv sync
   ```
3. Run the pre-PR checklist locally.
   ```
   just fitness-check
   just docs-sync
   uv run ruff check .
   uv run ruff format --check .
   ```
   Or `just qa` for the full suite.
4. Clean up local commits into logical, cherry-pickable units before pushing.
   ```
   git rebase -i HEAD~N   # un-pushed local commits only
   ```
5. Stage explicit files by name. Never `git add -A` (pre-commit hook blocks it).
6. If untracked sibling dirs in the repo root (e.g. `markdown-explorer/`) cause spurious `just fitness-check` violations, move them outside the repo, push, then restore them after.
7. Push. Never `--no-verify` (pre-push hooks fail for real reasons).
8. Open the PR against `main` with the standard body.
   ```
   gh pr create --base main --title "<short title>" --body "$(cat <<'EOF'
   ## Summary
   - <1-3 bullets, "why" not "what">

   ## Test plan
   - [ ] <how to verify>
   EOF
   )"
   ```
9. Wait for CI green AND at least one review pass (Copilot at minimum, ideally a human glance) before flagging the PR as ready to merge. If CI was green and the PR had to merge early without a review pass, fetch comments retroactively (`gh api repos/<o>/<r>/pulls/<N>/comments`, `gh pr view <N> --json reviews,comments`) and address them via `agent_hotfix.md` or a small follow-up PR. See `feedback_review_pass_before_merge`: maintenance cost dominates implementation cost, so review-pass discipline is a velocity multiplier, not a tax.
10. Operator merges manually; never `--auto` on `gh pr merge`.

## References

- `AGENTS.md` "Pre-PR Checklist" - source of truth for required local checks.
- `docs/release-process.md` - canonical branch model.
- `.githooks/pre-push` - what's actually enforced on push.
- `SKILL.md` "Hard rules" - the full memory-derived ruleset.

## Hard rules to honor

- Never force-push; new branch + new PR if a commit must change.
- Never rebase onto a moving `main`; use `git merge main` instead. Local `git rebase -i HEAD~N` on un-pushed commits is fine.
- Never `git add -A`; stage by name.
- Never `--no-verify` on commit or push.
- Never `--auto` on `gh pr merge`; operator merges.
- No em dashes anywhere; pre-push hook blocks them.

## Health check

If this file is out of date with the repository (workflow names changed, file paths moved, hard rules contradicted by current behavior), STOP and:
1. Note the drift in the response to the user.
2. Either fix this file inline (preferred for small drift) or escalate to the user with a one-line summary of what needs updating.

Keeping these skill files healthy is a higher priority than completing the immediate task with a stale recipe.
