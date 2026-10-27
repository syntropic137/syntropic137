# ADR-077: Hotfix Release Path

- **Status**: Accepted
- **Date**: 2026-10-27
- **Issue**: #2111 (cloudflared 2026.2.0 -> 2026.10.3 after the Cloudflare eMudhra intermediate-key compromise)
- **Related**: docs/release-process.md ("Hotfix Release"), `.claude/skills/devops/agent_hotfix_release.md`

## Context

Every release goes `main -> release`, and `main` is only released after a beta:
a pit stop on the self-host VPS and a live run. That is the right bar for
`main`, which carries weeks of agent PRs at a time (30 on 2026-10-27, none of
them deployed yet).

It is the wrong bar for a security patch. Cloudflare required cloudflared
>= 2026.10.2 after the eMudhra compromise
(<https://blog.cloudflare.com/emudhra-certificate-compromise/>). The fix was a
one-line image pin, but shipping it to self-hosters meant releasing all 30
untested PRs with it, or waiting for beta.2, which was blocked on unrelated
host work. A one-line fix should not wait on, or carry, everything else on `main`.

## Decision

A second head may open a PR into `release`: `hotfix/vX.Y.Z`, cut from the
latest release tag, carrying only the fix.

### What qualifies

| | Hotfix | Beta-gated release |
|---|---|---|
| Security: a CVE, advisory or compromise affecting a shipped image, dependency or pin | yes | |
| Production outage or data-loss bug in the released version, with a small, already-merged fix | yes | |
| A quick bug patch: small, already merged to `main`, cherry-picks cleanly onto the release tag | yes | |
| Anything touching an event schema, a projection `VERSION`, a migration or the event store | | yes |
| Features, refactors, dependency upgrades with no advisory | | yes |
| A fix that does not cherry-pick cleanly onto the release tag | | yes |
| Several unrelated fixes | | yes |

A projection `VERSION` change opens a read-path rebuild window that only a
rehearsal measures, which is why it is never a hotfix however small the diff.

### The shape, enforced by `_check-release-source.yml`

`scripts/workflows/check_release_source.py` (tests beside it) refuses the PR
unless every one of these holds:

1. **The head is `main` or `hotfix/vX.Y.Z`.** Any other branch is refused.
2. **Cut from the latest release.** The `release` head is the commit tagged
   `v<release version>`, and the branch's merge-base with `release` is that commit.
3. **Exactly the next patch.** `X.Y.Z` is the release's patch + 1, and the
   branch's version files say so.
4. **Only cherry-picks of `main`.** Every non-merge commit is either a
   `git cherry-pick -x` of a non-merge commit on `origin/main` with the same
   `git patch-id`, or the one `chore: bump version to vX.Y.Z` commit. Merge
   commits are allowed so each fix can arrive through its own PR into the
   hotfix branch, which is what puts it in `CHANGELOG.md`.
5. **Nothing else in the tree.** The checker replays the cherry-picks onto the
   tag in a scratch worktree. The branch may differ from that only in the files
   `just bump-version` rewrites, and outside `CHANGELOG.md` only on lines that
   carry the old or new version. An extra edit, a hand-adapted conflict or an
   evil merge fails here.
6. **Secret scan of the added commits** (gitleaks, pinned by digest, range
   `release..head` only).

The rule's first half: a fix lands on `main` first, always, through the normal
PR and review. A hotfix never carries code `main` has not merged.

### The gate is reduced, not removed

What a hotfix skips: the beta (pit stop, live run) and the release rehearsal.
What it keeps: the ruleset's required checks (`CI Success`, `Release Gate`,
`Compose Stack Smoke Test`), so full CI, codegen sync, the six-image docker
build, OSV, pip-audit, dependency review and the selfhost stack smoke test all
run on the hotfix head. That is roughly 30 minutes. The fix itself was already
reviewed and tested on `main`; what is new on the hotfix branch is only its
combination with the last release, and CI exercises exactly that.
`smoke-test.yml` fires on pushes to `hotfix/**`, because it has no PR trigger
and its check is required.

The `release-publish` environment approval is unchanged: the owner approves
every release, hotfix or not.

### Nothing is lost: the forward merge

After the release, `hotfix/vX.Y.Z` is merged into `main` with a merge commit
(a PR, `gh pr merge --merge`). The checker enforces it: a `main -> release` PR
is refused while `release` carries any non-merge commit `main` lacks. A hotfix
cannot be released over.

The forward merge is a follow-up PR, not automatic: a PR opened by
`GITHUB_TOKEN` triggers no workflows, so its required checks would never run.

## Consequences

- A security pin reaches self-hosters in about an hour instead of the next beta.
- The beta in flight renumbers: it becomes the next patch's beta (beta.2 of
  1.0.5 became 1.0.6-beta.x).
- `main`'s next release section in `CHANGELOG.md` lists the fix again (its
  `main` merge is not an ancestor of the hotfix tag). The duplicate is harmless
  and keeps the changelog purely git-derived.
- A fix that needs adapting to the release tag cannot be hotfixed; it goes
  through the beta. Adding a reviewed backport form is future work, not a
  loophole to open by hand.
