# PR1 ready for commit

> **SUPERSEDED 2026-05-05** — describes the original 5-commit slice that placed git fetch in the API container. The redesign at `redesign-thin-api.md` moved git work to the CLI tier per ADR-066. The current ship-ready state for #726 is described in `redesign-thin-api.md` plus the Phase A and Phase B work that landed on top. Preserved here as the historical record of what was originally shipped.

Issue: [#726](https://github.com/syntropic137/syntropic137/issues/726) - workflow-scoped claude-plugin injection (dormant plumbing).

## Stats

- **Files modified:** 37
  - syn-api: 6, syn-domain: 7, syn-adapters: 4, syn-shared: 2
  - syn-cli-node: 2, syn-dashboard-ui: 1, syn-docs: 4
  - schemas: 3, scripts: 1, ci: 1, infra: 1
  - root: `.env.example`, `fitness-exceptions.toml`, `uv.lock`
  - generated arch docs: 2 (`docs/architecture/event-flows/README.md`, `docs/architecture/projection-subscriptions.md`)
- **Files created:** 63 (excluding scratch/experiment dirs)
  - syn-domain: 42 (aggregates, events, commands, ports, slices, ref + ref tests)
  - syn-adapters: 10 (git fetcher + claude-plugin-storage, in-memory repos)
  - syn-api: 5 (routes, error mapping, resolution service, route + service tests)
  - syn-cli-node: 2 (claude-plugin command + tests)
  - syn-docs: 3 (api ref MDX, guide MDX, generated cli MDX)
  - docs/adrs: 1 (`ADR-065-claude-plugin-injection.md`)
- **Net new tests:** 13 new test files (89 individual cases, all green)
- **LOC delta:** `+1922 / -114` from `git diff main --shortstat` (modified files only; the 63 new files add ~3100 more)

## Phases delivered

1. Settings + storage bucket (`SYN_STORAGE_CLAUDE_PLUGIN_BUCKET_NAME`, `_init_claude_plugin_storage`).
2. Storage + fetcher ports + adapters (MinIO + in-memory storage, git subprocess fetcher).
3. Aggregates + events + commands (`ClaudePluginRegistrationAggregate`, `GlobalClaudePluginRegistryAggregate`, 3 events, 3 commands, 2 repository ports).
4. `ClaudePluginRef` + YAML schema additions (workflow- and phase-level `claude_plugins:`, `ResolvedClaudePlugin` VO on `PhaseDefinition` and `ExecutablePhase`).
5. Slices + projections + resolution service (4 slices, `ClaudePluginLockProjection`, `GlobalClaudePluginsProjection`, coordinator wiring, fitness count 21 to 23).
6. API routes + implicit fetch wiring (5 endpoints under `/claude-plugins`, typed-error mapping to HTTP 422, install-time `ensure_registered` integration in both API and seed paths).
7. CLI commands (`syn claude-plugin global add/remove/list`, `syn claude-plugin list`, `syn claude-plugin show`).
8. Docs + ADR (ADR-065, API + guide MDX, auto-generated CLI MDX).

## Code-review remediation

### MUST FIX (5/5 done before this round)

- Em-dash sweep across PR1 source.
- `_wiring.py` typed (no `Any`).
- Concurrent-add race resolved via `ExpectedVersion.NoStream` first-writer-wins.
- `manifest` typed (`dict[str, str | int]`).
- Redundant upload skipped on storage cache hit (`storage.exists(sha256)`).

### SHOULD FIX (this round)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Move tests from `src/` to `tests/` | SKIPPED | Co-location is the dominant repo convention; both `syn-domain` and `syn-adapters` already have many `test_*.py` next to source. Keeping PR1 consistent. |
| 2 | Make all handler getters uniformly sync | DEFERRED | `get_add_global_claude_plugin_handler` transitively awaits `get_claude_plugin_storage()` which does real I/O (`await _prod()`) on first call; making it sync would require eager startup init. Asymmetry intentional and matches the pattern other async storage getters in `_wiring.py` use. |
| 3 | `add_global` response `added_at` accuracy | DONE | Response now reads from `GlobalClaudePluginsProjection.get_by_name` after `sync_published_events_to_projections`. |
| 4 | Drop `_storage._bucket_name` private access | DONE | Switched to existing public `MinioStorage.bucket_name` property. No analogous fix needed in `MinioArtifactStorage` (no PR1 hunk there). |
| 5 | Hoist `ClaudePluginRef` import | DONE | Moved to module-top runtime import in `claude_plugin_resolution_service.py`. |
| 6 | CLI docs auto-generation | DONE | `pnpm tsx scripts/generate-cli-docs.ts` wrote `claude-plugin.mdx`; `meta.json` already lists it (committed earlier in PR1). |
| 7 | Em-dash sweep across all PR1 files | DONE | Found one stray em-dash in `manager_registry.py` (added line); replaced. No em-dashes in any other PR1-touched source. |

## Doc / test gap closure

- `docs/adrs/ADR-065-claude-plugin-injection.md` captures identity scheme, resolution algorithm, deferred org/system scopes, and the in-orchestration aggregate placement rationale.
- Public CLI MDX added (`apps/syn-docs/content/docs/cli/claude-plugin.mdx`) and listed in `meta.json`.
- Public guide MDX added (`apps/syn-docs/content/docs/guide/claude-plugins.mdx`) and listed in `guide/meta.json`.
- Public API MDX added (`apps/syn-docs/content/docs/api/claude-plugins.mdx`).
- `fitness-exceptions.toml` ratcheted: untyped-dicts (`syn-domain` 372 to 391, `syn-api` 93 to 94 - all in new event/projection payloads, scoped to issue #673 just like the existing entries) and a new `max-loc-file` exception for `_wiring.py` scoped to issue #185.

## Suggested commit message

```
feat(orchestration): claude plugin injection plumbing (PR1) for #726

Adds the dormant plumbing for workflow-scoped Claude Code plugin
injection: settings + MinIO bucket, ClaudePluginRef parsing in
workflow YAML, two new aggregates (ClaudePluginRegistration,
GlobalClaudePluginRegistry), four slices, two projections, the
ClaudePluginResolutionService, five REST endpoints, the syn
claude-plugin CLI group, and ADR-065. Behaviour is unchanged for
existing workflows; PR2 wires the materialization step that
actually injects --plugin-dir flags.
```

## Suggested PR title and body

**Title:** `feat(orchestration): claude plugin injection plumbing (PR1) for #726`

**Body:**

```
## Summary

- Adds dormant plumbing for workflow-scoped Claude Code plugin injection
  (issue #726). Workflows can now declare `claude_plugins:` in YAML; the
  refs resolve through fetch + content-addressed MinIO storage and land in
  a lock projection at install time. Behaviour for existing workflows is
  unchanged because PR2 (separate, ~100 LOC) flips the workspace
  materialization switch.
- Two new aggregates inside the existing `orchestration` context
  (ADR-020): `ClaudePluginRegistration` (one stream per
  `(source_url, version)`) and singleton `GlobalClaudePluginRegistry`.
  `ClaudePluginResolutionService` walks workflow + phase + global refs and
  dispatches `RegisterClaudePluginCommand` for any miss; concurrent adds
  resolve via `ExpectedVersion.NoStream` first-writer-wins.
- Five new REST endpoints under `/claude-plugins`, typed
  `ClaudePluginError` taxonomy mapped to HTTP 422 with stable
  `error_code` strings, and a `syn claude-plugin` CLI group
  (global add/remove/list, list, show).

## Plan

`docs/experiments/cycle-004/dogfood-platform-726/plan-local.md` and the
phased plan in `.claude/plans/steady-soaring-bee.md`. Validation against
the production base image is captured in
`docs/experiments/cycle-004/dogfood-platform-726/validation-experiment/`.

ADR: `docs/adrs/ADR-065-claude-plugin-injection.md`.

## Test plan

- 89 PR1 cases pass; targeted suite is green
  (`pytest` against the 13 new test files).
- `ruff check` and `ruff format --check` clean on all PR1 files.
- `pyright` clean on all PR1 files (0 errors, 0 warnings).
- `just codegen` regenerates: OpenAPI spec, CLI MDX
  (`apps/syn-docs/content/docs/cli/claude-plugin.mdx`), CLI types
  (`apps/syn-cli-node/src/generated/api-types.ts`),
  dashboard types, API reference docs.
- `just fitness-check` passes for PR1 surface;
  remaining failures are pre-existing in `markdown-explorer/`.

## Out of scope (deferred)

- PR2: workspace materialization + `--plugin-dir` emission (~100 LOC).
- Issue #761: org and system scopes (needs `ExecuteWorkflowCommand`
  widening through the dispatch chain).
- `syn claude-plugin gc`, `@latest` resolution, private source auth.
```

## Known follow-ups

- **PR2** (`#726` continuation): wire `ResolvedClaudePlugin` through the
  dispatch chain into `_build_provision_result`, materialize trees into
  `<workspace>/.syn-plugins/<plugin>/`, emit `--plugin-dir` flags. Field
  is already on `ExecutablePhase` with default `()` so no signature
  changes are needed in PR2.
- **Issue #761**: org and system scopes once `ExecuteWorkflowCommand` is
  widened. PR1 leaves room for this with no rework required.
- Consider a future GC pass for unreferenced lock entries (no-op today).

## Manual verification needed before merge

Automation cannot exercise the live MinIO bucket bootstrap or end-to-end
git fetch path against a real public source. Before merging, on a
running stack:

1. `just dev-down && just dev`; confirm MinIO console shows the
   `claude-plugins` bucket.
2. `syn claude-plugin global add syntropic137/software-leverage-points@5.0.7`
   and `syn claude-plugin global list` (the registered entry should
   appear with non-null `added_at`).
3. `syn claude-plugin show software-leverage-points 5.0.7` returns the
   lock detail with the resolved sha and storage prefix.
4. `syn workflow install` of a YAML referencing
   `claude_plugins: [syntropic137/software-leverage-points@5.0.7]`
   succeeds; `syn claude-plugin list` shows the entry.
5. `syn workflow install` of a YAML with `nonexistent/repo@1.0.0` returns
   HTTP 422 with a clear `claude_plugin_unreachable` error code; no
   workflow row is created.
6. Stop API; drop `claude_plugin_lock` projection rows; restart; confirm
   the projection rebuilds from events.
7. Existing workflows without `claude_plugins:` still install and run
   unchanged (no `--plugin-dir` on the claude command line - that is
   PR2's job).
