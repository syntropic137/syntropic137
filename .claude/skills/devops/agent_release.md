# Agent: version bump, release PR, approval, verification

## Purpose

Take `main` to a published stable release, or bump the version for a test
deploy. Cutting a release is the owner's call: when asked only to clear
blockers, stop at "main is releasable", report what it would carry, and leave
the bump and the release PR alone. Drafting release notes for the owner is
fine. The canonical steps are in `docs/release-process.md`; this file is the
checklist plus the lessons that doc does not carry.

## Test deploy vs release (decide first)

| | Test deploy (beta) | Stable release |
|---|---|---|
| Produces | images on the VPS; optional plain git tag | tag, GitHub Release, GHCR images, npm CLI, docs |
| How | `just pit-stop <version>` per `docs/deployment/test-deploy.md` | `main -> release` PR, below |
| GitHub Release | none | yes |

The owner does not want GitHub prereleases: they are public release-list noise.
`docs/release-process.md` still documents a "Published beta" via `gh release
create --prerelease` (which `release-beta.yaml` serves); use it only if the
owner explicitly asks for a beta with an outside audience. For a validation
build without a pit stop: merge the bump, push a plain tag (no workflow fires
on a tag push), `just release-local <version>`. That path does not cosign-sign,
so it never exercises signing. When to deploy a beta is `orchestrating`'s call.

## Workflow (stable release)

1. Read `docs/release-process.md` in full, including any release-specific constraint section near the top.
2. Preconditions:
   - `main` is green: `gh run list --workflow ci.yml --branch main --limit 1`.
   - If the `lib/event-sourcing-platform` gitlink moved since the last release, ESP has released that version and `just check-event-store-pin` passes. ESP releases before syn137, always.
   - Projection `VERSION` bumps in the range are listed; they open a read-path rebuild window that goes in Upgrade Notes.
   - Rehearsal done: a fresh install from the to-be-published compose AND an in-place upgrade from the last release, with images built from `main`, isolated from the live stack (prefer a disposable VM). Until `just rehearse-release` exists (#1865), this is manual.
   - Base-image bumps built locally once to catch upstream rot, with the same Dockerfile and build context `just/release.just` uses for that image (`token-injector` and `sidecar-proxy` build from their own directory, the rest from the repo root): `docker build -f <Dockerfile> <context>`.
3. Bump on a branch, through a normal PR into `main` (`agent_pr.md`):
   ```
   just bump-version X.Y.Z     # every version file, uv.lock, codegen, CHANGELOG.md section
   just check-version
   git add <each file the bump changed>   # list them with git status; not -A
   git commit -m "chore: bump version to vX.Y.Z"
   ```
   The bump touches CODEOWNERS paths, so the bump PR needs the owner.
4. Write the release notes body to a file BEFORE opening the release PR. It becomes the GitHub Release description verbatim, and the notes check reads the frozen event payload: an edit after opening never clears a red check (the "40-minute release").
   ```
   gh pr create --base release --head main --title "Release vX.Y.Z" --body-file notes.md
   ```
   Sections: What's Changed (user-facing), Upgrade Notes (rebuild windows, config changes, rollback limits).
5. Wait for `release-gate.yml` and `ci.yml` green. Triage with `agent_ci_triage.md`.
6. The owner merges or asks you to, with a merge commit. The merge is the trigger: `release-create.yml` starts and `create-release` waits on the `release-publish` environment. Tell the owner it is waiting; do not approve it yourself.
7. After approval: tag + Release, codegen re-check, `release-containers.yaml` (multi-arch build, cosign, GHCR, compose + SHA256SUMS assets) and `release-cli.yaml` (npm, provenance). About 6 minutes.
8. Verify the artifact, not the pipeline:
   ```
   gh release download vX.Y.Z --pattern 'docker-compose.syntropic137.yaml' --pattern 'SHA256SUMS'
   sha256sum -c SHA256SUMS --ignore-missing
   # each pinned image ref in the compose:
   # must be an index (OCI or Docker manifest list) carrying BOTH linux/amd64 and linux/arm64; exits non-zero otherwise
   docker buildx imagetools inspect <ref> --raw | jq -e '(.mediaType == "application/vnd.oci.image.index.v1+json" or .mediaType == "application/vnd.docker.distribution.manifest.list.v2+json") and ([.manifests[].platform | select(. != null) | "\(.os)/\(.architecture)"] | (index("linux/amd64") != null and index("linux/arm64") != null))'
   npm view @syntropic137/cli version
   ```
   SHA256SUMS attests the bytes, not that the digests resolve. v0.33.0 pinned an arm64 child manifest and broke every amd64 self-host.
9. npx setup chain (`syntropic137-setup`): the sync PR opens itself, then three human gates stop it: its CI lands `action_required` (bot author), the ruleset requires owner approval for unattributed changes, and `publish.yml` is dispatch-only. Do not self-approve gate 2 even though the `gh` identity can. Verify with `npm view @syntropic137/setup version`.

## Recovery

- A released version cannot be republished: every downstream job gates on `created == 'true'`, so re-merging is a silent no-op, and dispatching `release-containers.yaml` re-pushes new digests under a tag users already pulled. Fix forward with a patch bump and a new release PR.
- A publish step failed after the Release was created: re-run per `docs/release-process.md` "How to safely re-trigger" (`--ref release`, `dry_run=false`), only when nothing was pushed under that tag yet.
- Do not create Releases by hand to "trigger" publishing; stable publishing only flows through `release-create.yml`.

## Health check

Depends on: `just bump-version`, `just check-version`, `just check-event-store-pin`, `just pit-stop`, `just release-local` recipes; `release-create.yml` firing on push to `release` with `environment: release-publish` and the `created == 'true'` gates; `_check-changelog.yml` reading `github.event.pull_request.body`; `release-beta.yaml` firing on prereleases; release asset names `docker-compose.syntropic137.yaml` and `SHA256SUMS`. Check `#1865` for a `just rehearse-release` target and use it once it lands. Fix this file on drift.
