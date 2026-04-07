# Release Process

## Overview

Syntropic137 uses **trunk-based development** with a dedicated `release` branch for production deployments. Development happens on `main`, and releases are cut by merging `main` into `release`.

## Branch Strategy

| Branch | Purpose | Deploys |
|--------|---------|---------|
| `main` | Development trunk, all PRs target here | Nothing (CI only) |
| `release` | Production deployments | Docker images, CLI, docs |
| `feat/*` | Feature branches (short-lived) | Nothing (CI only) |

## First-Time Setup

These are the manual, one-time steps required before the automated release pipeline works. Based on the v0.19.0 release setup experience.

### NPM Organization and Packages

#### 1. Create the npm Organization

Create `@syntropic137` at https://www.npmjs.com/org/create (if not already done).

#### 2. @syntropic137/cli (main repo — `apps/syn-cli-node`)

1. Login to npm with org scope:
   ```bash
   npm login --scope=@syntropic137
   ```
2. Initial manual publish to claim the package name:
   ```bash
   cd apps/syn-cli-node
   pnpm install && pnpm build
   npm publish --access public
   ```
3. Configure Trusted Publisher on npmjs.com:
   - Go to https://www.npmjs.com/package/@syntropic137/cli/access
   - Add Trusted Publisher: repo=`syntropic137/syntropic137`, workflow=`release-cli.yaml`, environment=`npm-publish-cli`
4. Create the `npm-publish-cli` GitHub environment: repo Settings > Environments > New > `npm-publish-cli`
5. After Trusted Publishing is configured, the `CLI_PUBLISH_NPM_TOKEN` secret is no longer needed and can be deleted.

#### 3. @syntropic137/setup (npx repo — `syntropic137-npx`)

1. Login (same org scope as above):
   ```bash
   npm login --scope=@syntropic137
   ```
2. Initial manual publish to claim the package name:
   ```bash
   cd /path/to/syntropic137-npx
   npm install && npm run build
   npm publish --access public
   ```
3. Configure Trusted Publisher on npmjs.com:
   - Go to https://www.npmjs.com/package/@syntropic137/setup/access
   - Add Trusted Publisher: repo=`syntropic137/syntropic137-npx`, workflow=`publish.yml`, environment=`npm-publish`
4. Create the `npm-publish` GitHub environment on the `syntropic137-npx` repo.

### NPM Trusted Publishing Requirements

- npm >= 11.5.1 and Node >= 22.14.0 (for OIDC token exchange)
- Do NOT set `NODE_AUTH_TOKEN` — it overrides OIDC
- Do NOT set `registry-url` in `setup-node` — it creates `.npmrc` that interferes with OIDC
- The `--provenance` flag is still recommended even though docs say it is automatic
- npm returns E404 (not 401/403) for auth failures on scoped packages — this is misleading but means "not authenticated"

### GitHub Environments

Two environments are needed across the two repos:

| Environment | Repository | Purpose |
|-------------|------------|---------|
| `npm-publish-cli` | `syntropic137/syntropic137` | CLI publishes via `release-cli.yaml` |
| `npm-publish` | `syntropic137/syntropic137-npx` | npx setup publishes via `publish.yml` |

### NPX Template Sync Setup

1. Create a fine-grained PAT with these permissions, scoped to the `syntropic137-npx` repo only:
   - Actions: Read & Write
   - Contents: Read-only
   - Metadata: Read-only
2. Add as `NPX_DISPATCH_TOKEN` secret on the main `syntropic137/syntropic137` repo.
3. Enable "Allow GitHub Actions to create and approve pull requests" at BOTH org level AND repo level. The repo-level setting is grayed out if the org does not allow it.

### Release Branch Setup

1. Create `release` branch from main (already done for this project):
   ```bash
   gh api repos/syntropic137/syntropic137/git/refs --method POST \
     -f ref=refs/heads/release -f sha=$(git rev-parse main)
   ```
2. Branch ruleset: PR required, squash-only, Release Gate + CI Success checks, admin bypass.
3. Vercel: set production branch to `release` in project settings.

### Docker / Container Setup

- **GHCR authentication** uses the built-in `GITHUB_TOKEN` — no additional setup needed.
- **Cosign keyless signing** uses Sigstore OIDC — no additional setup needed.
- **Multi-arch builds** (amd64 + arm64) use QEMU emulation via `docker/setup-qemu-action`.

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

- **Version consistency** — all 11 files match, version > current release
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

The `scripts/bump_version.py` script updates exactly these 11 files:

**Python (pyproject.toml):**
1. `pyproject.toml` (root)
2. `apps/syn-api/pyproject.toml`
3. `packages/syn-adapters/pyproject.toml`
4. `packages/syn-collector/pyproject.toml`
5. `packages/syn-domain/pyproject.toml`
6. `packages/syn-perf/pyproject.toml`
7. `packages/syn-shared/pyproject.toml`
8. `packages/syn-tokens/pyproject.toml`

**Node.js (package.json):**
9. `apps/syn-cli-node/package.json`
10. `apps/syn-dashboard-ui/package.json`
11. `apps/syn-docs/package.json`

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

## Known Gotchas

- **npm E404 on scoped packages:** npm returns E404 on PUT for scoped packages when auth fails. This is misleading — it means "not authenticated", not "package not found".
- **npm Trusted Publishing version requirement:** OIDC-based registry auth requires npm >= 11.5.1. Older npm versions only use OIDC for Sigstore provenance signing, NOT for registry authentication.
- **Missing README on npmjs.com:** The `files` array in `package.json` must explicitly include `README.md` or it will not appear on the npm package page.
- **GITHUB_TOKEN loop prevention:** Releases and events created by `GITHUB_TOKEN` do NOT trigger other workflows (GitHub's anti-loop mechanism). That is why `release-create.yml` uses reusable workflow calls (`workflow_call`) instead of relying on `release.published` events.
- **Org-level Actions permission gates repo setting:** The GitHub org-level "Allow Actions to create and approve pull requests" setting gates the repo-level setting. If the checkbox is grayed out at repo level, check org settings first.
- **PAT permissions for `gh workflow run`:** A PAT used for `gh workflow run` needs Contents: Read-only in addition to Actions: Read & Write. The GraphQL `defaultBranchRef` resolution requires Contents access.
