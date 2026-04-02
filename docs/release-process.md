# Release Process

## Overview

Syntropic137 uses **trunk-based development** with a dedicated `release` branch for production deployments. Development happens on `main`, and releases are cut by merging `main` into `release`.

## Branch Strategy

| Branch | Purpose | Deploys |
|--------|---------|---------|
| `main` | Development trunk, all PRs target here | Nothing (CI only) |
| `release` | Production deployments | Docker images, CLI, docs |
| `feat/*` | Feature branches (short-lived) | Nothing (CI only) |

## Production Release

### 1. Bump Version

```bash
just bump-version 0.20.0
```

This updates all 13 version files atomically (9 `pyproject.toml` + 4 `package.json`). Validate with `just check-version`.

### 2. Commit and Push

```bash
git add -A
git commit -m "chore: bump version to v0.20.0"
git push origin main
```

### 3. Open Release PR

Open a PR from `main` to `release`. The PR body becomes the GitHub Release notes — write meaningful release notes here.

### 4. Release Gate Checks

The following checks run automatically on the PR:

- **Version consistency** — all 13 files match, version > current release
- **Release notes** — PR body has content (minimum 20 characters)
- **Docker dry-run** — all 7 container images build successfully (single-arch, no push)
- **Full CI** — tests, lint, typecheck, security scans (same as any PR)

### 5. Merge

Squash merge the PR. This triggers `release-create.yml` which:

1. Reads version from `pyproject.toml`
2. Creates git tag `v0.20.0`
3. Creates GitHub Release with the PR body as release notes
4. Calls `release-containers.yaml` → builds 8 multi-arch Docker images, signs with cosign, pushes to GHCR, attaches release assets (digest-pinned compose, SHA256SUMS)
5. Calls `release-cli.yaml` → builds and publishes `@syntropic137/cli` to npm with Sigstore provenance
6. Dispatches template sync to `syntropic137-npx`
7. Vercel deploys docs from `release` branch

### 6. Post-Release Verification

- [ ] GitHub Release exists with all assets
- [ ] Docker images tagged on GHCR (`v0.20.0`, `v0.20`, `latest`)
- [ ] `npm info @syntropic137/cli` shows new version
- [ ] Template sync PR opened on `syntropic137-npx`
- [ ] Docs site updated at production URL

## Beta Release

Betas bypass the `release` branch entirely:

```bash
just bump-version 0.20.0-beta.1
git add -A && git commit -m "chore: bump version to v0.20.0-beta.1"
git push origin main
gh release create v0.20.0-beta.1 --prerelease --target main --notes "Beta: <description>"
```

This fires `release.published` directly, triggering containers + CLI publish with pre-release handling:
- Docker images: tagged `v0.20.0-beta.1` only (no `latest`)
- npm CLI: tagged `next` (not `latest`)

## Hotfix Release

Same as production release, but bump the patch version:

```bash
# Fix the bug on main first
just bump-version 0.19.1
# Then follow the standard release PR flow
```

## Failure Recovery

| Failure Point | Recovery |
|---------------|----------|
| Release gate fails | Fix the issue on `main`, update the PR |
| `release-create.yml` fails | Investigate logs, re-run workflow manually |
| Container build fails | Fix Dockerfile on `main`, bump patch, new release PR |
| npm publish fails | Fix package issue, bump patch, new release PR |
| Template sync fails | Manually trigger on syntropic137-npx |

## Version Files Reference

The `scripts/bump_version.py` script updates exactly these 13 files:

**Python (pyproject.toml):**
1. `pyproject.toml` (root)
2. `apps/syn-api/pyproject.toml`
3. `apps/syn-cli/pyproject.toml`
4. `packages/syn-adapters/pyproject.toml`
5. `packages/syn-collector/pyproject.toml`
6. `packages/syn-domain/pyproject.toml`
7. `packages/syn-perf/pyproject.toml`
8. `packages/syn-shared/pyproject.toml`
9. `packages/syn-tokens/pyproject.toml`

**Node.js (package.json):**
10. `apps/syn-cli-node/package.json`
11. `apps/syn-dashboard-ui/package.json`
12. `apps/syn-docs/package.json`
13. `apps/syn-pulse-ui/package.json`

**Not included** (independent versioning):
- `lib/agentic-primitives/` — separate project
- `lib/event-sourcing-platform/` — separate project
- `packages/openclaw-plugin/` — independent plugin

## Workflow Architecture

```
PR: main → release
  ├── ci.yml (full CI suite)
  └── release-gate.yml
        ├── version-check
        ├── changelog-check
        ├── docker-dry-run (7 images)
        └── release-gate-success (aggregator)

Merge to release
  └── release-create.yml
        ├── create-release (tag + GitHub Release)
        ├── release-containers (reusable workflow call)
        │     ├── build-scan-push (8 images, multi-arch)
        │     └── release-assets (compose, SHA256SUMS, cosign sig, npx dispatch)
        └── release-cli (reusable workflow call)
              └── publish (npm, provenance)
```

## Branch Protection (release)

- Require PR (no direct push)
- Required status checks: `Release Gate` + `CI Success`
- Squash merge only
- No force pushes, no deletions
- Admin bypass for emergencies
