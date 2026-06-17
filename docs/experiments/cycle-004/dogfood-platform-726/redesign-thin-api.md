# Redesign: thin API for claude plugin registration (#726)

## Why

Current shape (5 commits in `20260502_platform`, not pushed):
- `POST /claude-plugins/global` calls `RegisterClaudePluginHandler` which calls `GitClaudePluginFetcher.fetch()` which `subprocess`-shells to `git clone`. Inside the API request handler. Inside the API container.

This violates ADR-066: the API is not allowed to spawn subprocesses, do long-running I/O during a request, or talk to the public internet for git operations. The retro (`retro-git-in-api.md`) explains how this slipped through.

## Reference pattern: `POST /workflows/from-yaml`

Read that flow before reading the redesign:

1. CLI side (`apps/syn-cli-node/src/commands/workflow/install.ts`): user invokes `syn workflow install <source>`. The CLI does `gitClone(url, ref, tmpdir)` (using `apps/syn-cli-node/src/packages/git.ts`), reads the resulting workflow YAML, and uploads the bytes via `postYaml()` (`apps/syn-cli-node/src/client/yaml-upload.ts`).
2. API side (`apps/syn-api/src/syn_api/routes/workflows/commands.py`): receives YAML bytes, parses, validates, dispatches a domain command. No git, no clone, no subprocess.
3. The CLI owns the local work; the API owns the persistence.

Plugin install will mirror this exactly.

## Endpoint shape (after redesign)

| Method + path | Replaces | Body | What it does |
|---|---|---|---|
| `POST /claude-plugins/trees` | (new; replaces server-side fetch) | tarball bytes (`application/x-tar`) of the plugin tree | Computes sha256 of the normalized tree, stores in MinIO under `claude-plugins/sha256-<hash>/`, returns `{sha256, file_count, size_bytes}` |
| `POST /claude-plugins/registrations` | (renamed; was implicit inside `POST /global`) | `{source_url, version, sha256, name, manifest}` | Registers a `ClaudePluginRegistrationAggregate` in the lock projection. Idempotent on existing `(source_url, version)` |
| `POST /claude-plugins/global` | (existing) | `{name, version, sha256}` | Adds a previously-registered plugin to the global set. References the lock entry by `(name, version)` |
| `DELETE /claude-plugins/global/{name}` | (existing, fix the projection sync bug) | none | Removes from the global set |
| `GET /claude-plugins/global` | (existing) | none | Lists global |
| `GET /claude-plugins` | (existing) | none | Lists all locked entries |
| `GET /claude-plugins/{name}/{version}` | (existing) | none | Show one |

The previous "POST /claude-plugins/global takes a `ref` string and does the clone server-side" is split into three calls the CLI orchestrates.

## CLI orchestration (after redesign)

`syn claude-plugin global add <ref>`:

```ts
// pseudocode in apps/syn-cli-node/src/commands/claude-plugin.ts

async function addGlobal(ref: string) {
  const parsed = parseClaudePluginRef(ref);             // org/repo@version etc

  // 1. Local git work (CLI tier per ADR-066)
  const tmpdir = makeTempDir("syn-claude-plugin-");
  try {
    await gitClone(parsed.source_url, parsed.version, tmpdir);
    const commitSha = await getGitHeadSha(tmpdir);
    const manifest = readPluginManifest(tmpdir);        // .claude-plugin/plugin.json
    const tarball = makeTarball(tmpdir);                // exclude .git/

    // 2. Upload tree (thin API call)
    const { sha256 } = await api.POST("/claude-plugins/trees", {
      body: tarball,
      headers: { "Content-Type": "application/x-tar" },
    });

    // 3. Register the lock entry
    await api.POST("/claude-plugins/registrations", {
      body: {
        source_url: parsed.source_url,
        version: parsed.version,
        sha256,
        name: manifest.name ?? defaultNameFromSource(parsed.source_url),
        manifest,
      },
    });

    // 4. Add to global set
    await api.POST("/claude-plugins/global", {
      body: { name, version: parsed.version, sha256 },
    });
  } finally {
    removeTempDir(tmpdir);
  }
}
```

Each step is one thin API round-trip; none of them require git inside the API.

`syn workflow install <yaml>`:

The CLI parses the YAML, finds `claude_plugins:`, and for each ref that is not already in the lock (cheap GET check), runs the same three-step register flow before posting the workflow YAML. This keeps the install atomic from the user's perspective while preserving the thin-API invariant.

## What changes inside the codebase

### Domain (`packages/syn-domain/`)

- **Keep** every aggregate, event, command, port, and projection from PR1. They are correctly placed.
- **Keep** the `ClaudePluginStoragePort` shape; it does not depend on git.
- **Move** `ClaudePluginFetcherPort` and `ClaudePluginFetcherProtocol` out of `syn-domain` (no longer needed; the domain does not fetch). Remove the import from `ports/__init__.py`.
- **Remove** the fetcher dependency from `RegisterClaudePluginHandler`. The handler now takes only the storage port and a repository; the caller (CLI) provides a pre-uploaded `sha256`.

### Adapters (`packages/syn-adapters/`)

- **Move** `packages/syn-adapters/src/syn_adapters/git/claude_plugin_fetcher.py` and `in_memory_fetcher.py` into the CLI repo (Node-side). The Python git fetcher is no longer needed; the CLI has its own (`packages/git.ts`).
- **Keep** `packages/syn-adapters/src/syn_adapters/storage/claude_plugin_storage/` as-is. The MinIO tree adapter is correct.
- **Add** a small `tarball_writer` helper if needed (or use `tarfile` stdlib) for the API-side unpacking.

### API (`apps/syn-api/`)

- **Add** `POST /claude-plugins/trees` route: accepts `application/x-tar`, unpacks in-memory, validates `.claude-plugin/plugin.json` shape, computes sha256 of the normalized tree, calls `storage.upload_tree(...)`, returns `{sha256, file_count, size_bytes}`.
- **Add** `POST /claude-plugins/registrations` route: accepts the lock-entry body, dispatches `RegisterClaudePluginCommand` against the existing aggregate.
- **Modify** `POST /claude-plugins/global`: takes `{name, version, sha256}` instead of a `ref` string. Looks up the lock by `(name, version)`, dispatches `AddGlobalClaudePluginCommand`. No fetcher dependency.
- **Modify** `_wiring.py`: drop the fetcher getter. The resolution service no longer needs it; it just looks up locks.
- **Modify** `seed_workflow/SeedWorkflowService.py`: the implicit-fetch on filesystem-loaded workflows is harder when the API does not have git. Two options:
  - (a) **Strict mode**: if a YAML has `claude_plugins:` and any are not in the lock, fail the install with a clear "register the plugin via CLI first" error. Simple, honest, surfaces the contract.
  - (b) **Best-effort**: log a warning and skip the workflow. Lossier.
  
  Recommend (a). The user always has a CLI; if they want to install a workflow from filesystem they can pre-register the plugins.
- **Modify** `routes/workflows/commands.py`: same change. `POST /workflows/from-yaml` only validates that all declared `claude_plugins:` are already in the lock; it does not fetch.

### CLI (`apps/syn-cli-node/`)

- **Add** `apps/syn-cli-node/src/commands/claude-plugin/install.ts` (or rename the existing single-file group to a directory) with the `gitClone` + `makeTempDir` + `getGitHeadSha` flow described above.
- **Reuse** `apps/syn-cli-node/src/packages/git.ts` (already in the CLI for workflow install).
- **Add** a tarball builder helper (Node-stdlib `tar` package or shell out; the workflow install side already has one for upload).
- **Update** `claude-plugin.ts` so the `add`, `list`, `show` subcommands match the new endpoint shape.
- **Add** `syn workflow install` pre-flight: parse YAML, ensure each `claude_plugins:` entry is in the lock, register any that are not.

### Infrastructure

- **Revert** the `git` install line from `infra/docker/images/syn-api/Dockerfile`. Already reverted locally.
- **Confirm** the workspace image (`lib/agentic-primitives/providers/workspaces/claude-cli/Dockerfile`) still has git (it does, line 56).

### Tests

- **Remove** integration tests that asserted the API does git operations. Replace with route tests against `POST /claude-plugins/trees` (uploads a fixture tarball, asserts sha256 + storage population) and `POST /claude-plugins/registrations` (asserts the aggregate writes).
- **Keep** all aggregate, projection, slice, and resolver tests (they were always correct).
- **Add** a CLI integration test that mocks the API and verifies the three-step orchestration calls happen in order.
- **Update** the e2e smoke (`e2e-smoke.sh`) to drive the new endpoint shape via the CLI.

## How this maps onto the existing 5 commits

The 5 commits in `20260502_platform` are not pushed. Two paths to apply the redesign:

**Path 1: keep history, layer fix commits on top.** Each existing commit stays; new commits 6+ remove the fetcher from the API path, add the new endpoints, port the work to the CLI. The history reads as "we shipped X, then realized X had a smell, then fixed it." Honest, but noisy.

**Path 2: rewrite the branch.** Reset to `main`, re-apply the keep-as-is parts (storage, aggregates, projections, slices, resolver, ADR), then apply the redesign as the "API + CLI" commit. Cleaner final history, but rewrites already-existing commits (acceptable since not pushed).

I recommend Path 2. The 5 commits make sense individually, but the "git in API" smell threads through commits 1, 3, and 4 in subtle ways. A clean re-shape produces a better PR for review.

## Sequencing

Within Path 2:

1. Reset `20260502_platform` to `main`.
2. **Commit A** — `feat(orchestration): claude plugin storage (#726)` — settings, port, MinIO + in-memory adapters, lifecycle wiring. Drop the fetcher port and adapter entirely.
3. **Commit B** — `feat(orchestration): claude plugin aggregates + YAML schema (#726)` — same as before, no changes.
4. **Commit C** — `feat(orchestration): claude plugin slices + projections + resolver (#726)` — slice handlers updated to take `(sha256, manifest)` directly instead of fetching. Projections unchanged. Resolver only does lookups.
5. **Commit D** — `feat(api): thin claude plugin endpoints + ADR-065 + ADR-066 (#726)` — three endpoints (trees/registrations/global) plus typed-error mapping plus the docs site updates plus the new ADR.
6. **Commit E** — `feat(cli): syn claude-plugin commands using local git + tarball upload (#726)` — CLI command group, `packages/git.ts` reuse, three-step orchestration. CLI tests mocking the API.
7. **Commit F** — `feat(orchestration): wire claude plugin materialization into workspaces (#726)` — same as the existing PR2 commit.

Six logical commits, each independently reviewable, no architectural smell.

## Estimated cost

- Aggregate, projection, ADR, retro work: already done; reusable.
- Domain port + adapter cleanup: 1-2h.
- API endpoint rework (3 new routes + DI cleanup): 3-4h.
- CLI orchestration (three-step add, workflow-install pre-flight, tarball builder, tests): 4-6h.
- E2E smoke rewrite + manual verification: 1h.
- Reset + re-commit: 1h.

**Total: 1-2 days of focused work.** Better than shipping the smell.

## Out of scope for this redesign (still deferred)

- Org / system scopes (#761) — same as before.
- Webhook-installed workflows that declare `claude_plugins:` — these now fail loudly with "register via CLI first." Adding a server-side path requires a worker service or processor; defer until real demand.
- `@latest` resolution — same as before; rejected.
- Private-source auth — same as before; deferred.

## Manual smoke (after redesign)

```bash
# Once the redesign is in:
syn claude-plugin global add syntropic137/software-leverage-points@main
syn claude-plugin global list                  # SLP appears
syn claude-plugin show software-leverage-points main
syn claude-plugin global remove software-leverage-points
```

No git in any container. All `git clone` happens on the user's host. The API stays thin.
