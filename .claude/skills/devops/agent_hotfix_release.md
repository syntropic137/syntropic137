# Agent: hotfix release (one fix off the last release tag, no beta)

## Purpose

Ship a security fix or a quick bug patch to self-hosters without the beta:
`hotfix/vX.Y.Z` cut from the last release tag, carrying only cherry-picks of
fixes already merged to `main`, through a PR into `release`, then merged
forward into `main`. Rules and rationale: ADR-077. Commands:
`docs/release-process.md` "Hotfix Release". This file is the checklist and
the lessons. Not to be confused with `agent_hotfix.md`, which pushes a nit
straight to `main` and releases nothing.

## Qualify first

| Hotfix | Beta-gated release (`agent_release.md`) |
|---|---|
| Security: CVE, advisory, compromise in a shipped image, dependency or pin | Event schema, projection `VERSION`, migration, event store |
| Prod outage or data-loss bug with a small, merged fix | Features, refactors, upgrades with no advisory |
| Quick bug patch that is merged and cherry-picks cleanly onto the tag | A fix that conflicts on the tag; several unrelated fixes |

When in doubt it is a beta. The operator decides what ships; a security
advisory relayed by opsec or the orchestrator with operator approval counts.

## Workflow

1. The fix is merged on `main` (`agent_pr.md`). Record the fix commit SHA, not the PR merge SHA.
2. `git fetch origin --tags`; confirm `git rev-parse v<last>^{commit}` equals `git rev-parse origin/release`. If not, stop: `release` moved without a tag.
3. Cut and push `hotfix/vX.Y.Z` (patch + 1) from the tag, in a worktree.
4. For each fix: branch `hotfix/vX.Y.Z-<slug>` from the tag, `git cherry-pick -x <sha>` (unmodified; a conflict means it is not a hotfix), PR into `hotfix/vX.Y.Z` titled with the main PR's title, `gh pr merge --merge`. That PR gets no CI (ci.yml only gates PRs into `main`/`release`); the PR into `release` is where CI runs.
5. On `hotfix/vX.Y.Z`: `just bump-version X.Y.Z`, stage by path, commit exactly `chore: bump version to vX.Y.Z`, push. The push fires `smoke-test.yml` on the head.
6. Write `notes.md` FIRST (`## Security` or `## Fixed`: what, the advisory link, the self-host one-liner), then `gh pr create --base release --head hotfix/vX.Y.Z --body-file notes.md`.
7. Wait for `Release Source` (prints each pick's main SHA and `tree = vX + N cherry-pick(s) + version bump`), `Release Gate`, `CI Success`, `Compose Stack Smoke Test`. Until `Release Source` is a required check on the `release` ruleset (owner setting), also run the checker yourself from a detached worktree of `origin/main` against the PR's exact head and base SHAs and paste the output into the PR.
8. Merge with `--merge`. `create-release` waits on `release-publish`: **page the operator** (below) and wait; never approve it yourself.
9. Verify the published artifact (`agent_release.md` step 8), the npx chain (step 9), and that the changed service is what the release compose pins.
10. Forward-merge: PR `hotfix/vX.Y.Z -> main`, merge commit. Version files take the hotfix version; regenerate `uv.lock` and `CHANGELOG.md`, do not hand-merge them. Until it lands every `main -> release` PR fails `release-source`.
11. Tell the orchestrator any in-flight beta renumbers to the next patch.

## Paging the operator

Any step that needs them (the `release-publish` approval, a `!` script, a
workflow only they can dispatch): page at once, one page per ask, no secrets:
```
~/Code/dev-tools/herdr-atc/skills/agent-pager/scripts/page -t "syn137_devops: <what>" -p high "<the exact action>"
```
Read `~/Code/dev-tools/herdr-atc/skills/agent-pager/SKILL.md` first. Never wait silently.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `release-source`: neither a git cherry-pick -x | picked without `-x`, or an extra commit | redo the pick with `-x` on a new branch; no edits |
| `patch-id differs` | the pick was edited or conflict-resolved | not a hotfix; use the beta |
| `changes more than the version` | the bump commit carries a non-version edit | new bump commit, only `just bump-version` output |
| `not cut from vX` | branched from `main` or an old tag | recut from the latest tag |
| `Compose Stack Smoke Test` never reports | head pushed before `smoke-test.yml` fired on `hotfix/**` | push again, or `gh workflow run smoke-test.yml --ref hotfix/vX.Y.Z` |
| next `main -> release`: `not forward-merged` | step 10 skipped | do step 10 |

## Health check

Depends on: `.github/workflows/release-source.yml` (`pull_request_target`, checkout at `github.workflow_sha`) and `scripts/workflows/check_release_source.py` (rules and messages above), `smoke-test.yml` firing on `hotfix/**`, the `release` ruleset's required checks (plus `Release Source` once added), `release-create.yml` reading the most recently merged PR into `release` for notes, the `chore: bump version to vX.Y.Z` subject, and the agent-pager script path. Fix this file on drift.
