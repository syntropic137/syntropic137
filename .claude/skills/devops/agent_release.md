# Agent: Cut a release (bump -> release PR -> approve gate)

## Purpose

Drive a version bump through the `main -> release` PR, the release gate, and the post-merge publish pipeline. Matches SKILL.md "When to invoke" triggers: "Cut a release", "publish v0.X.Y", "ship this", "Bump the version". The canonical procedure lives in `docs/release-process.md`; this file is the operational checklist that points at it.

## Workflow

1. Read `docs/release-process.md` end-to-end before doing anything. It is the source of truth for ordering, recovery, and gate behavior.
2. If this release bumps any base image tag in `docker/` or `infra/docker/` (envoy, sidecar-proxy, token-injector, etc.), build the affected images locally first to catch upstream apt rot before CI does. This is the v0.25.3 -> v0.25.4 lesson (`feedback_local_build_before_base_bump`).
   ```
   docker build -f infra/docker/<image>/Dockerfile .
   ```
3. Bump the version (updates all 11 files) and verify consistency.
   ```
   just bump-version <X.Y.Z>
   just check-version
   ```
4. Open a PR from `main` to `release`. Write the PR body as the GitHub Release notes verbatim - it becomes the release notes when the pipeline runs.
   ```
   gh pr create --base release --head main --title "Release vX.Y.Z" --body "$(cat <<'EOF'
   ## Highlights
   - <user-facing changes>

   ## Fixes
   - <...>

   ## Notes
   - <upgrade caveats, if any>
   EOF
   )"
   ```
5. Wait for the release gate (`release-gate.yml`) to go green: version-consistency, codegen-sync, multi-arch docker dry-run on native AMD64 + ARM64 runners, OSV scan, pip-audit. Use `agent_ci_triage.md` if anything fails.
6. Wait for at least one review pass before asking the operator to approve. Releases especially benefit from a Copilot/human read of the diff and the release notes - typos and stale comments shipped here are public-facing. If the release was already merged early, fetch reviews retroactively and address via a follow-up PR (`feedback_review_pass_before_merge`).
7. Ask the operator to approve the deployment environment gate. NEVER approve it yourself (`feedback_release_approval`).
8. Operator merges with a merge commit (preserves the release boundary). Merging fires `release-create.yml`: GitHub Release + tag, container build/sign/push to GHCR, then the npm CLI publish (gated on container success per the v0.25.4 fix).
9. If the pipeline partially failed (e.g. containers landed but CLI publish broke), do NOT re-cut the release. Follow the recovery flow in `docs/release-process.md`.

## References

- `docs/release-process.md` - canonical procedure, recovery, and failure modes.
- `.github/workflows/release-create.yml` - publish pipeline ordering.
- `.github/workflows/release-gate.yml` and `_check-*.yml` - what blocks the release PR.

## Hard rules to honor

- Never approve the deployment gate yourself; human only.
- Release PRs use merge commits (not squash); preserves the release boundary.
- Never force-push, never rebase, never `--no-verify`.
- Build base-image-bump containers locally first.
- No em dashes; pre-push hook blocks them.

## Health check

If this file is out of date with the repository (workflow names changed, file paths moved, hard rules contradicted by current behavior), STOP and:
1. Note the drift in the response to the user.
2. Either fix this file inline (preferred for small drift) or escalate to the user with a one-line summary of what needs updating.

Keeping these skill files healthy is a higher priority than completing the immediate task with a stale recipe.
