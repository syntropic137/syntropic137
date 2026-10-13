---
name: devops
description: Use for pull-request, merge, version and release mechanics in the Syntropic137 repo, and for CI or release-pipeline failures. Trigger phrases include "open a PR", "submit my changes", "address the review comments", "Copilot left comments", "merge this PR", "push this nit straight to main", "CI is red", "the release gate failed", "smoke test broke", "why is this PR BLOCKED", "bump the version", "cut a release", "release v1.x", "write the release notes", "main -> release PR", "approve the release gate", "the release published a bad asset", "triage the open PRs", "PR backlog", "which PRs are ready to merge", "merge order", "DORA metrics", "deploy frequency", "lead time", "change failure rate", "time to restore", "why didn't the issue auto-close". Covers trunk-based `main`, the `release` branch, local gates (`just qa-ci`, `just preflight`), GitHub Actions gates, review and merge policy, and post-release verification. Do NOT use for deciding what to dispatch, running the orchestrator loop, or deciding when to deploy a beta or run a pit stop (see `orchestrating`); for whether a task belongs in a workspace or locally (see `dogfooding`); for using the `syn` CLI as an end user (see the syntropic137 plugin skills).
---

# DevOps: Syntropic137 PR, merge and release

## Overview

Trunk-based, two branches. Every PR targets `main`. `release` accepts PRs from
`main` only, and the merge itself is the release trigger (`release-create.yml`
fires on push to `release`). History is append-only: merge commits everywhere,
no squash, no rebase of anything pushed, no force-push. This file routes; each
`agent_*.md` holds one self-contained procedure. The canonical process lives in
[docs/release-process.md](../../../docs/release-process.md) and the CLAUDE.md
sections "Branching & Release Process", "Pre-PR Checklist" and "Verification
gates"; when this skill and those disagree, they win and this skill is stale.

## When to Use (and When NOT to Use)

Use when:
- Moving a change from a local branch to a merged PR on `main`, or answering a review on one.
- Diagnosing a red check on a PR, on `main`, on the release PR or in the release pipeline.
- Bumping the version, opening the `main -> release` PR, or verifying what a release published.
- Working down a stack of open PRs, or measuring delivery with the DORA four keys.

Do NOT use when:
- Deciding what to build or dispatch next, or when to deploy a beta (`orchestrating`).
- Running `just pit-stop` as part of the loop: `orchestrating` owns the when, [docs/deployment/test-deploy.md](../../../docs/deployment/test-deploy.md) owns the how. This skill only covers the version bump and the test-deploy vs release distinction.
- Deciding whether an agent workspace can do the work (`dogfooding`).

## Input

- A worktree under `../syntropic137_worktrees/` (`/sdlc:git_worktree`). The main checkout often holds the owner's uncommitted work; switching its branch destroys context.
- `gh` authenticated for `syntropic137/syntropic137`.
- For release work: an explicit ask from the owner. Clearing release blockers is not a request to cut the release.

## Workflow

1. Match the task to a row below and read that agent file in full.
2. Dispatch a sub-agent with the file content as its prompt for anything multi-step; it keeps the main thread lean and the file already carries the rules. Inline is fine for one `gh` query.
3. If the agent file's Health check finds drift against the repo, fix the file in the same session (preferred) or report the drift. A stale recipe is how the 2026-05-01 version of this skill came to recommend squash merges.
4. Relay the result. Report PRs as merged, not opened.

| Task | Read |
|---|---|
| Open a feature/fix PR against `main`, through to merge | `agent_pr.md` |
| Answer review comments on an open PR (Copilot, codex, human) | `agent_review_pass.md` |
| Tiny follow-up on an already-merged PR, straight to `main` | `agent_hotfix.md` |
| A red check: PR CI, `main`, release gate, release pipeline | `agent_ci_triage.md` |
| Version bump, release PR, approval gate, post-release verification | `agent_release.md` |
| Triage every open PR: merge main in, rerun flakes, ready/blocked table, merge order | `agent_pr_backlog.md` |
| DORA four-keys snapshot from merged PRs, releases and runs | `agent_dora_snapshot.md` |

## Output

- A PR URL with green checks and the review evidence it merged on, or a merge commit on `main`.
- For releases: a GitHub Release whose downloaded assets were verified, not just a green pipeline.
- For triage: a ready/blocked table and a merge order. For metrics: four numbers with the window and commands used.

## Outcomes we are looking for

Framed by the DORA four keys (Forsgren, Humble, Kim, *Accelerate*, 2018). The
first two measure throughput, the last two stability; the book's finding is
that high performers improve both together, so trading one for the other is the
failure. Each signal is a command; [agent_dora_snapshot.md](agent_dora_snapshot.md) computes all four.

### Deploy frequency: changes reach users often, in small batches
- *Signal:* stable releases in the last 30 days, `gh release list --limit 50 --json tagName,isPrerelease,publishedAt --jq '[.[]|select(.isPrerelease|not)|select(.publishedAt>="<since>")]|length'`. Test deploys (pit stops) do not create releases and are counted from the orchestrator scratchpad, not GitHub.

### Lead time for changes: a merged change is short-lived on a branch and on `main`
- *Signal:* median and p90 hours from PR open to merge, `gh pr list --state merged --base main --search "merged:>=<since>" --limit 500 --json createdAt,mergedAt` (jq in the snapshot file). Plus merge-to-release: hours from a PR's merge to the first stable release published after it.

### Change failure rate: few releases need a fix
- *Signal:* share of stable releases followed by a patch release of the same minor within 7 days, or by a `revert` PR: `gh pr list --state merged --search "revert in:title merged:>=<since>"`. v0.33.0 -> v0.33.1 is the reference case.

### Time to restore: a broken `main` or a bad release is fixed fast
- *Signal:* hours from a failed `ci.yml` run on a `main` push to the next success, `gh run list --workflow ci.yml --branch main --event push --limit 100 --json conclusion,createdAt`; and hours from a bad release to its patch release.

## Branch and merge model (as of 2026-10-13)

| Action | Policy | Why |
|---|---|---|
| Merge a PR into `main` | `gh pr merge N --merge` | Squash rewrote #824 and left the stacked #829 conflicting in nine files; merge commits keep stacks and cherry-picks intact |
| Merge `main -> release` | merge commit; the ruleset allows nothing else | squash permanently diverges `release` from `main` (v0.19.x) |
| Branch behind `main` | `git merge origin/main` into it, then push | rebasing a pushed branch needs a force-push |
| Tidy commits never pushed | rebase or reorder freely | the ban is on rewriting published history, not on rebase as an operation |
| A pushed commit must change | new branch, new PR, close the old one | no force-push, ever |
| `gh pr merge --auto` | not used | it merged before every check reported |
| Who merges | the agent, once the review bar in `agent_pr.md` is met; owner-gated PRs (CODEOWNERS) wait for the owner | parking a green, reviewed PR on the owner stalled seven PRs for a day |
| Approve the `release-publish` environment | owner only; ask, then wait | it is the last human checkpoint before tags, images and npm |

Staging is by explicit path (`git add <files>`), never `-A` or `.`: the main
checkout routinely carries untracked research docs and handoff folders, and the
commit hooks exist to stop secrets. Hooks are never skipped with
`--no-verify`; `.githooks/pre-push` runs `just preflight` because the old
hand-rolled list missed gates CI then failed on.

## Gates that exist (verify against `.github/workflows/` before relying on this)

| Workflow | Fires on | What it proves |
|---|---|---|
| `ci.yml` | push to `main`/`feat/*`; PRs to `main`/`release`; weekly | Python QA (format, lint, pyright, domain events, vsa, test debt, OpenAPI drift), architectural fitness, unit + integration tests, dashboard, docs site, CLI, submodule check, default workspace image, OSV, pip-audit, dependency review; `ci-success` aggregates |
| `docs-lint.yml` | every PR; push to `main`/`release` | docs content lint |
| `syn-ui.yml`, `syn-landing.yml` | PRs and `main` pushes touching Skyline / landing paths | UI build, tests, size budget, gateway serving |
| `smoke-test.yml` | push to `main`/`release` only (PR trigger disabled) | full selfhost compose stack comes up healthy; a red smoke on `main` is found after merge |
| `e2e-container.yml` | PRs and `main` pushes touching workspace code, the AW gitlink or image pins; `workflow_dispatch` | automatic runs build and probe the workspace image from source; a real agent run (live API calls) happens only on manual dispatch with `run_full_e2e=true` |
| `docs-drift.yml` | push to `main`/`release` | generated docs match source |
| `release-gate.yml` | PRs into `release` | `_check-version`, `_check-changelog` (PR body >= 20 chars, read from the frozen event payload), `_check-codegen-sync`, `_check-docker-dry-run`, OSV, pip-audit, dependency review |
| `release-create.yml` | push to `release` | `create-release` (waits on `release-publish` approval) -> tag + Release -> codegen re-check -> `release-containers.yaml` + `release-cli.yaml` |
| `release-beta.yaml` | a published GitHub prerelease | beta images + CLI on `next`; exists, but the owner does not want GitHub prereleases (see `agent_release.md`) |

`just qa-ci` runs the core PR-gating jobs locally (~3.5 min), not all of them:
`scripts/check_ci_parity.py` lists every job left out with its reason and its
own mirror recipe (workspace image build `just workspace-build`, Skyline
`just skyline-ci` and friends, landing `just landing-*`). When a PR touches
those paths, run the listed recipe too. Not local at all: osv-scan, pip-audit,
dependency-review, release-only gates.

## Recommended tools and practices (as of 2026-10-13)

### For: lead time stays short
- **`just qa-ci` before the first push**, `just preflight` on every later push. A CI round-trip is 8-10 minutes; most red PRs were catchable locally.
- **Merge as soon as the review bar is met.** Open PRs past ~8 is the signal to land or close, not to wait (`agent_pr_backlog.md`).
- **Page the owner the moment a PR is blocked only on them** (`mergeStateStatus == BLOCKED` with checks green), with a review package link. A TLDR line is invisible to someone not watching the terminal.

### For: change failure rate stays low
- **Cross-family review before merge.** Opus-authored code gets a GPT/codex verifier and vice versa; a workflow's own verify phase certifying its own head is not enough (it passed 3 of 3 heads a steered review rejected).
- **Re-verify stale PRs.** `MERGEABLE`/`CLEAN` describe a textual merge; merge `origin/main` in and re-run the suite (PR #871 hid three semantic conflicts).
- **Judge the commit, not the worktree.** Uncommitted auto-fixes make local gates green on a red commit; check `git status --porcelain` is empty before calling it green.
- **Release rehearsal on a fresh install AND an upgrade from the last release** before the release PR; it found five defects in v1.0.0 that CI, pit stops and the empty-store runbook could not (#1865 tracks codifying it).
- **ESP releases before syn137** when the ESP gitlink moved. `just check-event-store-pin` (in preflight) fails if the pinned event-store tag is not published.

### For: time to restore stays short
- **A released version cannot be republished.** Every downstream job gates on `created == 'true'`, so re-merging is a silent no-op; fix a bad release by bumping the patch.
- **Verify the artifact, never the pipeline.** Download the published compose and check every digest is a multi-arch index (v0.33.0 pinned an arm64 child and broke every amd64 self-host).
- **Fix a red `main` first.** Every open PR inherits it.

## References

- [docs/release-process.md](../../../docs/release-process.md): release procedure, workflow architecture, poka-yoke rules, failure recovery.
- [docs/deployment/test-deploy.md](../../../docs/deployment/test-deploy.md): test deploy and `just pit-stop`.
- [docs/north-star.md](../../../docs/north-star.md): 20 / 100 / 1,000 concurrent executions; delivery speed exists to serve it.
- [docs/retrospectives/](../../../docs/retrospectives/): prior incidents; search here before diagnosing a symptom from scratch.
- `.github/CODEOWNERS`: owner-gated trust-boundary paths (`.github/`, `.gitmodules`, `just/release.just`, image pins, compose, credentials, gateway).
- Sibling skills: `orchestrating`, `dogfooding`, `learning-loop`.

## Continual improvement

When a recipe here fails against the repo, fix the file in the same PR as the
work that found it. File larger gaps at
https://github.com/syntropic137/syntropic137/issues.
