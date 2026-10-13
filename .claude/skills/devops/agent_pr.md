# Agent: take a change from a branch to a merged PR on `main`

## Purpose

Get a feature or fix from local work to a merged PR without spending CI
round-trips on what local gates catch. Not for `main -> release` PRs
(`agent_release.md`) or nits on an already-merged PR (`agent_hotfix.md`).

## Workflow

1. Work in a worktree on a new branch from `origin/main`; never switch branches in the main checkout.
   ```
   git fetch origin main
   git worktree add -b <type>/<slug> ../syntropic137_worktrees/<slug> origin/main
   cd ../syntropic137_worktrees/<slug>
   git submodule update --init --recursive && uv sync && pnpm install
   ```
   A fresh `uv sync` may rewrite `uv.lock`; if the change is not a dependency change, `git checkout -- uv.lock` before committing.
2. Make the change. Shape commits as logical, revertable units. Rebasing or reordering commits that were never pushed is fine.
3. Run the local gates against the tree you will push. Before the first push: `just qa-ci` (~3.5 min, the core PR-gating jobs), plus the path-specific mirror recipe from `scripts/check_ci_parity.py` for any path-filtered workflow the change touches (Skyline, landing, workspace image). After that, the pre-push hook runs `just preflight`. If generated files are involved, `just codegen` and commit what it rewrites.
4. Stage by explicit path and confirm the tree is clean afterwards; uncommitted auto-fixes make local gates green on a red commit.
   ```
   git add <file> <file>
   git commit -m "<type>(<scope>): <summary>"
   test -z "$(git status --porcelain)"
   ```
5. Push. If `main` moved, `git merge origin/main` (never rebase a pushed branch), re-run gates, push again. A pushed commit that must change goes on a new branch and PR.
6. Open the PR. `Closes #N` on its own line auto-closes the issue; a bare `#N` does not. If no issue exists and the change is not trivial, file one first (with milestone and priority).
   ```
   gh pr create --base main --title "<type>(<scope>): <summary>" --body "$(cat <<'EOF'
   Closes #N

   ## Summary
   - <why, not what>

   ## Release notes
   - <one user-facing line; `just changelog` uses the first bullet here>

   ## Test plan
   - [ ] <commands run and their result>
   EOF
   )"
   ```
7. Get the review the change needs (see `agent_review_pass.md`): a cross-family review (codex verifies Claude-authored code and vice versa), triaged; a second pass only if pass 1 found something severe; Copilot comments read and answered.
8. Before merging, re-verify if `main` moved since the last green run or review: merge `origin/main` in, re-run the PR's targeted tests and `just preflight`, and review commits added after the last review (`git log --oneline <reviewed-sha>..HEAD --no-merges`).
9. Merge when checks are green and the review bar is met: `gh pr merge N --merge`. Never `--squash`, `--rebase` or `--auto`. If `mergeStateStatus` is `BLOCKED` with checks green, the PR touches a CODEOWNERS path: page the owner with the PR link instead of waiting silently.
10. After merge, `gh issue view N` to confirm it closed. If not, the body was malformed: close it by hand and say why.

## References

- CLAUDE.md "Pre-PR Checklist" and "Verification gates" (in-workspace agents use `just preflight-agent` + `uv run pytest -m unit -q`).
- `.githooks/pre-push`, `scripts/check_ci_parity.py`, `.github/CODEOWNERS`.
- New Python test modules need the `unit` marker, or the unit gate collects zero tests and goes green.

## Health check

Depends on: `just qa-ci`, `just preflight`, `just codegen` recipes existing; `.githooks/pre-push` running preflight; `ci.yml` triggering on PRs to `main`; CODEOWNERS being the only owner-gated merge block; `## Release notes` being what `scripts/changelog.py` reads. If any of these changed, note the drift, fix this file in the same session or report it, then continue.
