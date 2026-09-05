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

#### 2. @syntropic137/cli (main repo - `apps/syn-cli-node`)

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
   - Add Trusted Publisher: repo=`syntropic137/syntropic137`, workflow=`release-create.yml`, environment=`npm-publish-cli`
   - **Important:** The workflow must be the **caller** (`release-create.yml`), not the callee (`release-cli.yaml`). GitHub mints the OIDC token with the caller's workflow name.
4. Create the `npm-publish-cli` GitHub environment: repo Settings > Environments > New > `npm-publish-cli`
5. After Trusted Publishing is configured, the `CLI_PUBLISH_NPM_TOKEN` secret is no longer needed and can be deleted.

#### 3. @syntropic137/setup (npx repo - `syntropic137-npx`)

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
- Do NOT set `NODE_AUTH_TOKEN` - it overrides OIDC
- Do NOT set `registry-url` in `setup-node` - it creates `.npmrc` that interferes with OIDC
- The `--provenance` flag is still recommended even though docs say it is automatic
- npm returns E404 (not 401/403) for auth failures on scoped packages - this is misleading but means "not authenticated"

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
2. Branch ruleset: PR required, merge commits only (no squash, no rebase), Release Gate + CI Success checks, admin bypass.
3. Vercel: set production branch to `release` in project settings.

### Docker / Container Setup

- **GHCR authentication** uses the built-in `GITHUB_TOKEN` - no additional setup needed.
- **Cosign keyless signing** uses Sigstore OIDC - no additional setup needed.
- **Multi-arch builds** (amd64 + arm64) use QEMU emulation via `docker/setup-qemu-action`.

## v0.28.0 Rollout Constraints

> **Read this before starting the Production Release steps below.** Two
> constraints came out of the cross-model release-risk review of #1057. Both are
> specific to v0.28.0: one is a read-path window that opens the moment a stack
> with existing data upgrades, the other removes the assumption that a binary
> rollback is available. Neither is visible from the release pipeline, and
> neither shows up in a validation run - the
> [Release Validation Runbook](testing/release-validation.md) tears the stack
> down with `docker compose down -v` before upgrading, so it always runs against
> an empty event store, where neither constraint can manifest.
>
> **Delete this section once v0.28.0 has shipped and the decision below is
> recorded.** It documents one release, not the process.

### The projection rebuild window

v0.28.0 bumps three projection versions:

| Projection (`PROJECTION_NAME`) | v0.27.0 | v0.28.0 |
|---|---|---|
| `session_summaries` | 3 | 4 |
| `workflow_execution_details` | 6 | 9 |
| `workflow_phase_metrics` | 2 | 5 |

When a deploy changes any projection's version, the coordinator **clears that
projection, deletes its checkpoint, and restarts the ONE shared subscription
from global nonce 0**. There is a single subscription, so while it replays, **no
projection advances** - not only the three that were bumped.

**How this lies to you.** During the replay the platform is up, accepting
writes, and dispatching executions normally. The containers run. But the read
models are behind, so `GET /api/v1/executions/{id}` returns **404 for an
execution that was just dispatched and is running fine**. From outside, that is
indistinguishable from the platform having lost the execution.

**This has already caused a near-miss.** On a beta deploy an operator came close
to rolling back a healthy stack because freshly dispatched executions were
404ing. Nothing was wrong; the rebuild was in progress. **Do not diagnose
execution 404s as data loss until catch-up completes.** Checkpoint position is
what distinguishes the two: a 404 while projections are short of the store head
is a rebuild, a 404 once they have reached it is a real problem.

**How long it takes is not known in advance.** One rebuild, on the
v0.28.0-beta.6 deploy, was **measured at 8m46s**. That is a single measurement,
not a bound. The replay is proportional to the number of events in the store,
and the production event-store size was not available to the reviewer who
recorded it, so the production window has not been measured at all. Do not
quote 8m46s as an expected duration, and do not use it to set a timeout or an
alerting threshold.

#### Procedure

**1. Announce the read-path window before deploying.** Do this before the
upgrade, not after someone reports a 404. State that for the duration of the
rebuild, newly dispatched executions may return 404 from the API and the
dashboard may show stale or missing data; that this is expected; and that no
action is required. For a public release, this belongs in the **Upgrade Notes**
of the release PR body (step 3 below), which is what becomes the GitHub Release
notes users read.

**2. Watch the read path from the moment the new images start.** The field to
watch is `subscription.status`, which reports `catching_up` during the rebuild
and `healthy` once it is done:

```bash
curl -s http://localhost:8137/api/v1/health \
  | jq '{status, subscription: {status: .subscription.status, is_catching_up: .subscription.is_catching_up, lag: .subscription.lag, lagging: [.subscription.lagging_projections[] | {projection, position, lag}]}}'
```

During the rebuild, expect `subscription.status` to be `catching_up` with the
three bumped projections in `lagging_projections`:

```json
{
  "status": "healthy",
  "subscription": {
    "status": "catching_up",
    "is_catching_up": true,
    "lag": 41822,
    "lagging": [
      {
        "projection": "session_summaries",
        "position": 0,
        "lag": 41822
      },
      {
        "projection": "workflow_execution_details",
        "position": 0,
        "lag": 41822
      },
      {
        "projection": "workflow_phase_metrics",
        "position": 0,
        "lag": 41822
      }
    ]
  }
}
```

> Top-level `status` stays `healthy` throughout, deliberately: the process is
> alive and accepting writes, and taking it out of rotation would turn a stale
> read path into an outage. `subscription.status` is the field that describes
> the read path. **Reading only the top-level `status` tells you nothing about
> the rebuild** - that is precisely how the near-miss above happened.
>
> `position: 0` means the projection has no checkpoint row at all, which is what
> a projection looks like immediately after a version bump clears it. The `lag`
> values are illustrative; they scale with your store.
>
> Use `/api/v1/health`, **not** `/health`. Against the selfhost stack `/health`
> returns the dashboard SPA's HTML with a 200, which looks like a passing check
> and is not one. Substitute your own host and port for `localhost:8137`.

**3. The window is over when all three projections reach the store head.** That
is the done condition, and it is met when **both** of these hold in the same
response:

- `subscription.status` is `"healthy"`, and
- `subscription.lagging_projections` is `[]`

`lagging_projections` lists every projection short of the head, so an empty list
is the assertion that all three have reached it. Equivalently, `subscription.lag`
is `0`.

**Both conditions, not just the first.** `subscription.status` can read `healthy`
while `lagging_projections` is still non-empty: `is_catching_up` requires the
coordinator to be replaying AND some projection to be behind, so once the
coordinator goes live with a projection still short of the head (and not yet past
the stall threshold), the status returns to `healthy` before the rebuild has
finished. Poll on both:

```bash
while true; do
  read -r st behind < <(curl -s http://localhost:8137/api/v1/health \
    | jq -r '"\(.subscription.status) \(.subscription.lagging_projections | length)"')
  echo "status=$st behind=$behind"
  [ "$st" = "healthy" ] && [ "$behind" = "0" ] && { echo "read path caught up"; break; }
  [ "$st" = "stalled" ] && { echo "STALLED - waiting will not help"; break; }
  sleep 15
done
```

Expected final line, and the only output that means done:

```
read path caught up
```

The loop terminates two other ways, and **neither is done**: `STALLED - waiting
will not help`, or you interrupting it while it still prints
`status=catching_up`. Treat both as the window still being open.

- [ ] Read-path window announced **before** the upgrade
- [ ] `subscription.status` polled after the new images started
- [ ] `subscription.status` is `healthy` **and** `lagging_projections` is `[]`
- [ ] No execution 404 observed during the window was reported as data loss

> **If `subscription.status` is `stalled` rather than `catching_up`,** this
> procedure does not apply and waiting will not help. `catching_up` ends by
> itself; `stalled` means a projection is behind and its checkpoint has stopped
> moving, and it needs intervention. They are independent signals, so a replay
> that wedges partway through reports both.

> **If `/api/v1/health` is unreachable or has no `subscription` block,** read the
> checkpoint table directly - it is the source these fields are computed from.
> The store head must be read in the *same* query: a checkpoint position means
> nothing on its own, only relative to the head it is chasing.
>
> ```bash
> docker exec syn137-timescaledb psql -U syn -d syn -c \
>   "WITH head AS (
>        SELECT COALESCE(MAX(global_nonce), 0) AS position
>          FROM events
>         WHERE tenant_id = 'syn'
>    ),
>    expected (projection_name, version) AS (
>        VALUES ('session_summaries', 4),
>               ('workflow_execution_details', 9),
>               ('workflow_phase_metrics', 5)
>    )
>    SELECT e.projection_name,
>           COALESCE(c.global_position, 0) AS position,
>           head.position                  AS head,
>           COALESCE(c.version, 0)         AS version,
>           e.version                      AS want_version,
>           c.updated_at,
>           COALESCE(c.global_position, 0) >= head.position
>             AND COALESCE(c.version, 0) = e.version AS done
>      FROM expected e
>      CROSS JOIN head
>      LEFT JOIN projection_checkpoints c USING (projection_name)
>     ORDER BY e.projection_name;"
> ```
>
> **Done is the `done` column reading `t` on all three rows.** Nothing less.
> The query always returns exactly three rows, so a projection that is missing,
> behind, or still on its old version shows up as `f` rather than vanishing from
> the output.
>
> **Equal, stable positions are NOT done, and must not be read as done.** Three
> checkpoints agreeing with each other and not advancing between two reads is
> exactly what a replay wedged partway through looks like: with the head at 500,
> three rows stuck at 400 are equal and perfectly stable while the read path is
> 100 events behind and executions are still 404ing. That is why the comparison
> above is against `head`, not against the other rows. Position equality across
> rows is not a completion signal in either direction - discard it.
>
> The three parts of the `done` condition each rule out a different way of being
> behind, which is why all three are required:
>
> | Term | Rules out |
> |---|---|
> | `position >= head` | The wedged replay above, and any projection still catching up |
> | `COALESCE(c.global_position, 0)` | A **missing** checkpoint row. A version bump deletes the row before replaying, so during this very window a not-yet-started projection has no row at all. `IN (...)` would have returned two rows that look finished; the `LEFT JOIN` from the literal list returns three, and the absent one reads `position 0`, `done f`. |
> | `version = want_version` | A projection fully caught up to head on its **old** schema - it never rebuilt, so its checkpoint is at head and its data is still v0.27 shaped |
>
> Because `head` and the checkpoints are read in one statement, they come from a
> single snapshot and cannot skew. On a stack still taking writes the head keeps
> advancing, so a healthy projection may briefly read `f` and then `t` on the
> next run; a wedged one never reaches `t`. Repeat the query rather than
> relaxing the condition.
>
> Container name, user, database and `tenant_id` are whatever your deployment
> sets - the values above are the compose defaults (`POSTGRES_USER`,
> `POSTGRES_DB` and `EVENT_STORE_TENANT_ID`, all defaulting to `syn`). Confirm
> them with `docker ps` and `~/.syntropic137/.env` rather than assuming these.
> Both tables live in the same database, which is what lets one query join them:
> the event store and the API's checkpoint store are pointed at the same
> Postgres by `DATABASE_URL` and `SYN_OBSERVABILITY_DB_URL` respectively. If a
> deployment ever separates them, this fallback cannot establish done at all and
> `/api/v1/health` is the only source that can.

### The rollback asymmetry

Forward replay is fine. Rollback is not symmetric with it.

v0.28 keeps the event type and version identifiers unchanged - both are still
`("SessionCompleted", "v1")` and `("WorkflowFailed", "v1")` - while **adding**
two fields:

| Event | Field added | Default |
|---|---|---|
| `SessionCompleted` | `agent_launch` | `unknown` |
| `WorkflowFailed` | `failed_phase_duration_seconds` | `None` |

Both are defaulted, so **every v0.27 event reads forward correctly under
v0.28**. Schema introspection at the reviewed head confirmed neither new field
is required:

```
SessionCompletedEvent required: session_id, status, completed_at, total_input_tokens,
                                total_output_tokens, total_tokens, operation_count
agent_launch default: unknown

WorkflowFailedEvent required: workflow_id, execution_id, failed_at, error_message,
                              completed_phases, total_phases
failed_phase_duration_seconds default: None
```

**The failure is one-directional.** The v0.27 models use `extra="forbid"`,
inherited from `DomainEvent`, so once v0.28 has written either field a v0.27
build can **reject that event during replay**:

```
1 validation error for WorkflowFailedEvent
failed_phase_duration_seconds
  Extra inputs are not permitted [type=extra_forbidden, input_value=None, input_type=NoneType]
```

**Binary rollback stops being safe at the moment the first v0.28 event is
appended - not at deploy time.** The gap between "we deployed" and "rollback is
no longer free" is however long it takes for one session to complete or one
workflow to fail.

**How this lies to you.** A rollback rehearsed against a freshly deployed v0.28
stack that has not yet completed a session will pass, because the events that
break it do not exist yet. The rehearsal proves nothing about the state you
would actually be rolling back from.

Note also that the field is present even at its default value. The write path
serializes with `model_dump(mode="json")`, which does not drop `None`, so a
`WorkflowFailed` carrying `failed_phase_duration_seconds: null` still contains
the key - that null payload is what produces the error quoted above. Do not
assume that "no phase was in flight", or an `agent_launch` of `unknown`, leaves
the v0.27 shape intact. It does not.

#### DECISION REQUIRED - the owner must choose one before rollout

**Not decided. Neither option below has been chosen, and nothing else in this
document assumes one.**

- [ ] **(a) Forward-fix-only once the first v0.28 event is written.**
      Cheapest: nothing to build before rollout. **Cost:** removes binary
      rollback as an option for this release. Any regression found after the
      first `SessionCompleted` or `WorkflowFailed` is written must be fixed by
      rolling forward.

- [ ] **(b) Backport tolerant parsing of those two fields to the rollback build,
      before rollout.** Preserves binary rollback. **Cost:** a backport plus a
      build, both finished and published *before* v0.28 ships - a backport that
      lands afterwards does not help, because the build that needs it is the one
      already sitting there as the rollback target.

**Owner decision:** _(unfilled - record the option, the date, and who decided,
here, before rollout)_

#### Verifying whichever option is chosen

The test is the same for both; only the pass condition differs. Do not
substitute a rehearsal on an empty store: the whole constraint is about events
v0.28 has already written.

1. **Append representative v0.28 `SessionCompleted` and `WorkflowFailed` events
   to a disposable event store.** Representative means at least one of each,
   produced by a real v0.28 run rather than hand-written JSON - the point is to
   test what v0.28 actually serializes. Disposable means a store you can destroy,
   not a copy of production.
2. **Boot the exact rollback image against that store** - the published digest
   you would actually roll back to, resolved from the registry with
   `docker buildx imagetools inspect <ref>`, not a local tag and not a rebuild
   from the v0.27 source tree.
3. **Force aggregate and projection replay**, so those events are parsed rather
   than skipped. Bumping a projection version on the rollback build is one way to
   force it. The requirement is that replay actually reaches the v0.28 events -
   a process that merely starts proves nothing.

Pass conditions:

- **Under option (b):** the rollback build consumes every one of those events.
  Replay completes, and `subscription.status` reaches `healthy` with
  `lagging_projections` empty. A single `extra_forbidden` in the logs is a
  failure even if the process stays up.
- **Under option (a):** this test is expected to fail, and the runbook must then
  **explicitly prohibit binary rollback for this release** rather than leaving it
  unstated. An unstated prohibition fails the same way the rebuild window did:
  the operator discovers it during the incident.

> **What was not checked.** The facts above come from a review pinned to one
> commit range. The pinned rollback image was not inspected, and no production
> event store was examined. This section records that the constraint exists and
> how to verify it. It does not report that the verification has been run.

## Production Release

### 1. Bump Version

```bash
just bump-version 0.20.0
```

This updates all 11 version files atomically (8 `pyproject.toml` + 3 `package.json`). Validate with `just check-version`.

### 2. Commit and Push

```bash
git add -A
git commit -m "chore: bump version to v0.20.0"
git push origin main
```

### 3. Open Release PR

Open a PR from `main` to `release`. **The PR body becomes the GitHub Release notes** - write meaningful release notes here. The release-gate check enforces a minimum of 20 characters. Use this format as a guide:

```markdown
## What's Changed

- Brief description of each notable change
- Bug fixes, new features, breaking changes

## Upgrade Notes

Any migration steps or config changes required.
```

The `release-create.yml` workflow reads the merged PR body verbatim and sets it as the GitHub Release description. Write it for end users, not for internal tracking.

### 4. Release Gate Checks

The following checks run automatically on the PR:

- **Version consistency** - all 11 files match, version > current release
- **Release notes** - PR body has content (minimum 20 characters)
- **Docker dry-run** - all 6 container images build successfully (single-arch, no push)
- **Full CI** - tests, lint, typecheck, security scans (same as any PR)

### 5. Merge

Merge the PR as a merge commit (not squash, not rebase). This triggers `release-create.yml` which:

1. Reads version from `pyproject.toml`
2. Creates git tag `v0.20.0`
3. Creates GitHub Release with the PR body as release notes
4. Calls `release-containers.yaml` → builds 6 multi-arch Docker images, signs with cosign, pushes to GHCR, attaches release assets (digest-pinned compose, SHA256SUMS)
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

**Two different things share this name. Pick one before you start.** They differ
in whether anyone other than you is meant to install the result.

| | Test deploy | Published beta |
|---|---|---|
| **Question** | "Can I look at the current code running on a host?" | "Can these people install and try this?" |
| **Audience** | You | Someone else |
| **Produces** | Container images | Git tag, GitHub Release, images, npm CLI on `next` |
| **`gh release create`** | **No** | Yes |

Seven `v0.28.0-beta.*` prereleases were created in roughly 48 hours, one per test
deploy, because only the published-beta path was written down. A release entry
should mark something worth marking, not every image move.

### Test deploy (images only, no GitHub release)

Build the images, move them to the host, recreate two containers. No tag, no
release entry, no npm publish. Follow the
[Test Deploy runbook](deployment/test-deploy.md) - it covers the drain check
that must precede any container recreation, the four version-carrying files
`just bump-version` does not touch, and the tag-prefix reconciliation
`release-local` needs. The `INCLUDE_DOCKER_CLI` build arg it once could not pass
is fixed and asserted at build time
([#1216](https://github.com/syntropic137/syntropic137/issues/1216)).

### Published beta (a release entry with an audience)

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

The `scripts/workflows/bump_version.py` script updates exactly these 11 files:

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
- `lib/agentic-primitives/` - separate project
- `lib/event-sourcing-platform/` - separate project
- `packages/openclaw-plugin/` - independent plugin

## Workflow Architecture

```
PR: main → release
  ├── ci.yml (full CI suite)
  └── release-gate.yml  (thin orchestrator - 4 reusable checks + 3 inline security scans)
        ├── checks/version-check.yml       - all 11 files consistent, version > release
        ├── checks/changelog-check.yml     - PR body >= 20 chars
        ├── checks/codegen-sync.yml        - CLI types, CLI docs, API docs all current
        ├── checks/docker-dry-run.yml      - all container images build (single-arch, cached)
        ├── osv-scan (inline)
        ├── pip-audit (inline)
        ├── dependency-review (inline)
        └── release-gate-success (aggregator)

Merge to release
  └── release-create.yml  (triggered by push to release)
        │
        ├── create-release job
        │     ⏸ environment: release-publish  ← MANUAL APPROVAL REQUIRED HERE
        │     ├── read version from pyproject.toml
        │     ├── create git tag
        │     └── create GitHub Release (PR body = release notes)
        │
        ├── pre-publish-validation job  (needs: create-release)
        │     └── checks/codegen-sync.yml  (workflow_call - reused from gate)
        │
        ├── release-containers.yaml  (workflow_call, needs: pre-publish-validation)
        │     ├── build-scan-push (multi-arch)
        │     └── release-assets (compose, SHA256SUMS, cosign sig, npx dispatch)
        │
        └── release-cli.yaml  (workflow_call, needs: pre-publish-validation)
              └── publish (npm OIDC, provenance)
```

### Workflow Files

| File | Purpose |
|------|---------|
| `.github/workflows/release-gate.yml` | Thin orchestrator - calls checks + inline security scans |
| `.github/workflows/release-create.yml` | Release pipeline - create tag/release, publish containers + CLI |
| `.github/workflows/_check-version.yml` | Version consistency: all 11 files match, bumped vs release |
| `.github/workflows/_check-changelog.yml` | PR body length validation (takes `pr_body` input) |
| `.github/workflows/_check-codegen-sync.yml` | Runs `just codegen`, checks for drift (CLI types, API docs, CLI docs) |
| `.github/workflows/_check-docker-dry-run.yml` | All container images build successfully (single-arch, GHA cache) |
| `.github/workflows/release-containers.yaml` | Multi-arch build, cosign sign, push to GHCR, release assets |
| `.github/workflows/release-cli.yaml` | Build + publish `@syntropic137/cli` to npm (OIDC, provenance) |
| `scripts/workflows/bump_version.py` | Version bump script; `--check` (consistency) and `--check-release` (semver vs release branch) |
| `scripts/workflows/check_drift.py` | Drift detection; called by `codegen-sync.yml` to check git diff + untracked files for generated paths |

## Branch Protection (release)

- Require PR (no direct push)
- Required status checks: `Release Gate` + `CI Success`
- Merge commits only (no squash, no rebase — squashing rewrites history and forces rebasing main on every release)
- No force pushes, no deletions
- Admin bypass for emergencies

## Poka-Yoke Rules

These rules exist to prevent out-of-order publishing. Do not work around them.

### The only valid release entry point is `release-create.yml`

`release-containers.yaml` and `release-cli.yaml` are **internal callees** - they must only be triggered by `release-create.yml` via `workflow_call`. Direct triggers are poka-yoke protected:

- **`release.published` is intentionally absent** from both publish workflows. A manually created GitHub Release (via UI, `gh release create`, or an AI agent) does not trigger publishing - it bypasses the approval gate.
- **`workflow_dispatch` is branch-guarded** - both workflows reject dispatch from any branch other than `release`.
- **`workflow_dispatch` dry_run defaults to `true`** on both workflows - dispatch with default inputs never pushes anything.

### The approval gate

The `create-release` job in `release-create.yml` uses `environment: release-publish`. GitHub pauses here and waits for a human to approve before creating the tag, the GitHub Release, or calling any publish workflow. **You must approve this manually every time.**

### How to safely re-trigger a failed publish step

If containers or CLI publish fails after the GitHub Release was already created:

```bash
# Re-trigger CLI publish (version must match package.json on the release branch)
gh workflow run release-cli.yaml \
  --repo syntropic137/syntropic137 \
  --ref release \
  -f version=vX.Y.Z \
  -f dry_run=false

# Re-trigger containers publish
gh workflow run release-containers.yaml \
  --repo syntropic137/syntropic137 \
  --ref release \
  -f version=vX.Y.Z \
  -f dry_run=false
```

Both commands must be run against `--ref release`. Any other ref will be rejected by the branch guard.

### Do not create GitHub Releases manually

Creating a release via the GitHub UI, `gh release create`, or any automated tool does NOT trigger publishing (by design). It will create the tag and GitHub Release but nothing will be built or published. The only way to publish is through the `release-create.yml` orchestrator.

## Known Gotchas

- **npm E404 on scoped packages:** npm returns E404 on PUT for scoped packages when auth fails. This is misleading - it means "not authenticated", not "package not found".
- **npm Trusted Publishing version requirement:** OIDC-based registry auth requires npm >= 11.5.1. Older npm versions only use OIDC for Sigstore provenance signing, NOT for registry authentication.
- **Missing README on npmjs.com:** The `files` array in `package.json` must explicitly include `README.md` or it will not appear on the npm package page.
- **GITHUB_TOKEN loop prevention:** Releases and events created by `GITHUB_TOKEN` do NOT trigger other workflows (GitHub's anti-loop mechanism). That is why `release-create.yml` uses reusable workflow calls (`workflow_call`) instead of relying on `release.published` events.
- **Org-level Actions permission gates repo setting:** The GitHub org-level "Allow Actions to create and approve pull requests" setting gates the repo-level setting. If the checkbox is grayed out at repo level, check org settings first.
- **PAT permissions for `gh workflow run`:** A PAT used for `gh workflow run` needs Contents: Read-only in addition to Actions: Read & Write. The GraphQL `defaultBranchRef` resolution requires Contents access.
