# Agent: push a tiny follow-up straight to `main`

## Purpose

Land a trivial follow-up to an already-merged PR (format or lint nit, a late
Copilot comment, a typo, a comment fix) without a PR round-trip. This is an
owner-authorized admin bypass of branch protection; it is not a hotfix
release (that is a patch bump through `agent_release.md`).

## Workflow

1. Qualify the change. In: formatting, lint, comments, doc typos, a late review nit with no behavior change. Out (use `agent_pr.md`): anything that changes runtime behavior, a schema, an event, a public API, a migration, or a CODEOWNERS path (`.github/CODEOWNERS`). A fix for a red `main` qualifies only if it also meets every condition above; otherwise it goes through `agent_pr.md` like any other change. A qualifying red-`main` fix goes first.
2. Worktree from `origin/main` on a short branch; never the main checkout.
   ```
   git fetch origin main
   git worktree add -b fix/<slug> ../syntropic137_worktrees/<slug> origin/main
   ```
3. Make the change, stage by path, commit with a pointer to the origin PR: `fix: <summary> (follow-up to #N)`.
4. `just preflight` (the pre-push hook runs it anyway). Confirm `git status --porcelain` is empty.
5. If `origin/main` moved, `git merge origin/main` (no rebase), re-run preflight.
6. Push to `main`: `git push origin fix/<slug>:main`. GitHub warns about the bypass and accepts it. Never force.
7. Watch the `main` run once: `gh run list --branch main --limit 3`. If it goes red, fix forward immediately.

## Health check

Depends on: admin bypass still enabled on `main`; `.githooks/pre-push` running `just preflight`; CODEOWNERS paths in `.github/CODEOWNERS`. If direct pushes to `main` are rejected or the policy changed, stop and report rather than opening a workaround.
