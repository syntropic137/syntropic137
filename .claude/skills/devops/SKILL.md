---
name: devops
description: Use for ANY pull-request flow, version management, release cutting, or CI/release-pipeline troubleshooting in this repo. Covers trunk-based development on `main`, the `release` branch as deployment trigger, gate behavior, and what each release artifact is. Routes to focused agent files for each task (`agent_pr.md`, `agent_release.md`, etc.).
---

# Skill: DevOps — Syntropic137 PR + Release Process

Trunk-based, two-branch model. `main` is the trunk (all work merges here). `release` is the deployment branch (merges from `main` only; merging triggers the publish pipeline). Don't reinvent — read the canonical doc, then apply the relevant agent flow.

## Canonical sources (do not duplicate)

- **`docs/release-process.md`** — release process, branch model, version-bump procedure, npm/GHCR setup, recovery for failed releases. **Read this before any release work.**
- **`docs/runbooks/001-system-experimentation-runbook.md`** — dogfood / experimentation runbook (separate concern, but referenced when release work intersects with experiment runs).
- **`AGENTS.md`** + **`CLAUDE.md`** — repo-wide rules. Hard rules around hooks, force-push, rebase, merging are enforced; do not work around them.
- **`.github/workflows/release-create.yml`** — the actual release orchestration. Read this when reasoning about ordering or gate behavior.
- **`.github/workflows/release-gate.yml`** + **`_check-*.yml`** — pre-merge gate. Read this when reasoning about what blocks a release PR from merging.

## Mental model in one paragraph

Code lands on `main` via merged PRs. CI runs on every `main` push. Periodically (whenever a release window opens), bump the version with `just bump-version <X.Y.Z>` and open a `main → release` PR. The release-gate workflow fires on that PR — version-consistency check, codegen-sync check, multi-arch docker dry-run on native AMD64 + ARM64 runners, security scans. When all pass and a human approves the deployment environment gate, merge the release PR. Merging triggers `release-create.yml` which creates the GitHub Release tag, builds + signs + pushes containers to GHCR, then (gated on containers success) publishes the npm CLI. **The merged release PR's body becomes the GitHub Release notes verbatim** — write it like release notes from the start.

## Commit hygiene (this matters)

Operator preference: **commits should be logical and cherry-pickable**. Clean them up locally before pushing — rebase-into-shape, rewrite messy intermediate commits, separate concerns. The goal is that each commit on the branch is a self-contained logical unit that could be cherry-picked or reverted without taking unrelated work with it.

**On merge to `main`:** prefer regular merge (preserves the logical commits) when the branch already has a clean history. **Squash only when necessary** — typically when the branch accumulated messy fixup commits that local cleanup couldn't sort out, or when the operator explicitly requests squash. Default to regular merge; squash is a fallback.

**On merge to `release`:** always merge commits (per the documented release process) — preserves the merge boundary so each release is one cleanly-identifiable commit on `release`.

**Note on the no-rebase memory rule:** `feedback_no_rebase` is specifically about NOT rebasing your branch onto a moving `main` (use `git merge main` instead). It does NOT prohibit `git rebase -i HEAD~N` on your own un-pushed local commits to clean them up. Local rewriting of un-pushed commits is encouraged; rewriting public history is forbidden.

## Review hygiene (this also matters)

Default behavior on every PR: wait for CI green AND at least one review pass (Copilot at minimum, ideally a human glance) before flagging it ready to merge. If a PR had to merge early, fetch reviews retroactively (`gh api repos/<o>/<r>/pulls/<N>/comments`, `gh pr view <N> --json reviews,comments`) and address them in a small follow-up. Do not let late comments silently rot.

**Why this is non-optional:** maintenance cost dominates implementation cost. A two-minute Copilot pass that surfaces a stale comment, a dead branch, or a missing edge case saves hours of future debugging. Skipping reviews to ship faster trades a small now-saving for a much larger future-tax. High quality is the multiplier on continued velocity. See `feedback_review_pass_before_merge`.

## When to invoke this skill

Any of:
- "Open a PR" / "create a pull request" / "submit my changes"
- "Cut a release" / "publish v0.X.Y" / "ship this"
- "Address Copilot review comments"
- "What's blocking the release?"
- "CI failed on the release PR" / "smoke test broke"
- "Bump the version"
- "Why didn't [issue] auto-close on merge?"
- Any decision about whether to push directly to `main` vs open a PR

## How to use this skill

This SKILL.md is a router, not a workflow. For any task in the table below:

1. Read the matching `agent_*.md` file. Each is self-contained.
2. **Dispatch a sub-agent with that file's content as its prompt** rather than executing the workflow inline. Reasons: keeps the main thread's context lean, the agent file already encodes the steps and hard rules, and a fresh sub-agent isn't biased by the surrounding conversation. Use the `general-purpose` sub-agent type unless a more specific one fits.
3. Surface the sub-agent's result back to the operator. If the sub-agent flags drift between the agent file and the actual repo state (per the "Health check" section every agent file ends with), fix or escalate before continuing.

Inline execution is acceptable only for small, single-step tasks (one quick `gh` query, one comment fix) where the sub-agent overhead would dominate.

| Task | Read |
|---|---|
| Opening a normal feature/fix PR | `agent_pr.md` |
| Cutting a release (bump → release PR → approve gate) | `agent_release.md` |
| Handling Copilot / human review comments on an open PR | `agent_review_pass.md` |
| Investigating CI failure (smoke test, release pipeline, gate) | `agent_ci_triage.md` |
| Emergency hotfix (push direct to main for tiny fix; per memory `feedback_push_to_main`) | `agent_hotfix.md` |

## Hard rules (memory-derived; non-negotiable)

These come from operator preferences encoded in memory; honor them without re-discovering each session.

1. **Never `git add -A`** — the pre-commit hook blocks it (would include secrets). Add specific files by name.
2. **Never `--no-verify`** on commits or pushes. Pre-push hooks fail for real reasons.
3. **Never force-push** (`feedback_no_force_push`). New branch + new PR if a commit needs to change.
4. **Never rebase published history** (`feedback_no_rebase`). Merge `main` into the feature branch instead of rebasing onto it. Local `git rebase -i HEAD~N` on un-pushed commits to clean them up is fine and encouraged - see "Commit hygiene" above.
5. **Never `--auto` on `gh pr merge`** (`feedback_no_auto_merge`). Operator merges manually.
6. **Never approve a release deployment gate** (`feedback_release_approval`). Even if you believe everything passed; human only.
7. **Always use `/sdlc:git_worktree`** for parallel branch work (`feedback_worktree_active_branch`). Never switch branches in the main checkout.
8. **Regular merge (preserve commits) is the default for `main`**; squash only when necessary. Release PRs use merge commits. See "Commit hygiene" section above.
9. **Small fixes (formatting, Copilot nits) on already-merged PRs go directly to `main`** (`feedback_push_to_main`), NOT in a new PR. Faster than the round-trip.
10. **No em dashes in any file** (`feedback_no_em_dashes`). Plain hyphens only.

## What gates actually exist

(Confirm against `release-gate.yml` and `_check-*.yml` if uncertain — files of truth, not this list.)

| Gate | Fires on | What it checks |
|---|---|---|
| Standard CI (`ci.yml`) | every push, every PR | Lint, format, typecheck, unit tests, fitness checks, codegen drift |
| Smoke Test (`smoke-test.yml`) | push to main / release; PRs touching `docker/` or `infra/docker/` | Build full selfhost compose stack with locally-built images; verify health, Docker CLI presence, envoy reachability, workflow round-trip. **Single-arch (AMD64).** |
| Release Gate (`release-gate.yml`) | PR targeting `release` only | Version-consistency, changelog/PR-body sanity, codegen sync, **multi-arch docker dry-run on native runners** (AMD64 + ARM64), OSV scan, pip-audit |
| Release Pipeline (`release-create.yml`) | merge to `release` only | Create GitHub Release + tag, build/sign/push containers (multi-arch), publish CLI to npm. CLI is gated on containers success per the v0.25.4 fix |

## Common gotchas (battle-tested in this session)

- **`docs-sync` requires `vsa manifest --include-domain` to run first** in fresh worktrees. The pre-push hook fails with "Manifest not found" until you run `uv run vsa manifest --config vsa.yaml --output .topology/syn-manifest.json --include-domain`.
- **`pnpm install` is required in fresh worktrees** before docs-sync's codegen step works (`tsx` not found otherwise).
- **`uv.lock` regenerates on every install in fresh worktrees** and shows as modified — discard with `git checkout -- uv.lock` before committing if your change isn't dependency-related.
- **Architecture-doc regeneration drift** (`docs/architecture/event-flows/README.md`, `projection-subscriptions.md`) is preexisting and benign. Commit alongside any actual change as `docs: regenerate architecture docs (row-ordering drift)`.
- **`syn workflow run` returns Execution IDs in print order ≠ launch order** when used with `&` parallelism. Map cell→exec via `syn execution show <id>` to identify the workflow.
- **CI smoke tests can flake on transient network issues** (`apt-get` DNS failures, `corepack` pnpm fetch, `undici.UND_ERR_SOCKET`). Re-run before assuming a real bug. If it fails twice in a row on the same step, escalate.
- **Issue auto-close requires `Closes #N` (not just `#N`)** in the merged PR body. Verify after merge.
