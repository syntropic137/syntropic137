# Plan (local, baseline) — #726 workflow-scoped claude plugin injection

> **SUPERSEDED 2026-05-05** — this plan placed git fetch inside the API container, which was caught after the first end-to-end smoke against the dev stack. The redesign at `redesign-thin-api.md` moves git work to the CLI tier per ADR-066. See also `retro-git-in-api.md` for what went wrong. This document is preserved as the historical baseline for context.

**Track:** platform
**Item:** issue #726
**Author:** local session, revised 2026-05-05 after audit + validation experiment
**Workflow shape under test:** none yet (this is the local baseline; platform plans will be compared against it later in this cell)

## Goal

Make Claude Code inside an agent workspace see a curated set of plugins, declared per-workflow and per-phase in YAML, materialized at workspace setup time. The first consumer is `software-leverage-points` for the leverage-points review workflow.

Non-goals: a marketplace UI, runtime plugin installation by the agent, hot-swap mid-execution, org/system scopes (deferred to a follow-up — they need `ExecuteWorkflowCommand` widening which is out of scope here).

## Validated upfront (no rework risk)

The injection mechanism is proven against the production base image. See `validation-experiment/` in this cell directory. Confirmed:

- `<workspace>/.syn-plugins/<plugin>/` with `.claude-plugin/plugin.json` + `skills/<name>/SKILL.md` is the correct on-disk shape.
- `claude --plugin-dir <path>` loads it. Multiple `--plugin-dir` flags work simultaneously, no collisions.
- `docker cp` injection into a running container is fine — that's the same mechanism `WorkspaceProvisionHandler.inject_files()` already uses.
- Description-matched activation works. We do NOT need to force `/<skill>` invocations in workflow prompts.
- Real-world plugin (`software-leverage-points`, 20 skills) loaded and was fully invokable with the correct `software-leverage-points:<skill>` namespace.

## Terminology

- **Claude plugin** — the unit of distribution from the Claude Code ecosystem (a directory with `.claude-plugin/plugin.json` + optional `skills/`, `hooks/`, `commands/`, MCP servers). Always written `claude_plugins` in YAML / `ClaudePluginRegistration` in code, never bare `plugin` to avoid collision with Syntropic's existing "workflow plugin" / marketplace concept.
- **`ClaudePluginRef`** — a typed reference to a plugin at a specific version. Three input forms (all parsed to one normalized internal shape):
  - GitHub shorthand: `syntropic137/software-leverage-points@5.0.7`
  - Full URL: `https://gitlab.com/foo/bar.git@1.2.0`, `git+ssh://git@host/baz.git@2.0.0`
  - Verbose: `{source: github.com/syntropic137/software-leverage-points, version: 5.0.7, name: software-leverage-points}`
- **Lock entry** — a row in the `claude_plugin_lock` projection: `(source_url, version) → resolved_sha + tree_storage_uri`. Reproducibility primitive.
- **Resolved plugin set for a phase** — the union of global + workflow + phase claude_plugins after conflict resolution.

## Scope hierarchy (v1 = 3 of 5)

```
global     ←  syn claude-plugin global add <ref>     (a settings-style projection)
  ∪ workflow.claude_plugins                          (declared in workflow YAML)
  ∪ phase.claude_plugins                             (declared per-phase in workflow YAML)
```

Conflict rule when the same plugin appears at multiple scopes with different versions: **phase > workflow > global**. Innermost wins. Logged at INFO so the override is observable.

Out of scope for v1: org and system scopes. They require widening `ExecuteWorkflowCommand` and `WorkflowExecutionStarted` to carry org/system IDs through the dispatch chain — that's the expensive part. Pure additive when added later; no v1 rework.

## What "done" looks like

```yaml
id: review-001-leverage-points
claude_plugins:
  - syntropic137/software-leverage-points@5.0.7   # workflow scope
phases:
  - id: synthesize
    claude_plugins:
      - obra/superpowers@2.1.0                      # phase scope, additive
```

Plus this works:
```bash
syn claude-plugin global add syntropic137/syntropic137-claude-plugin@1.4.2
syn claude-plugin global list
syn claude-plugin global remove syntropic137-claude-plugin
```

When the workflow runs, the workspace's `/workspace/.syn-plugins/` tree contains exactly the union resolved per phase, each materialized from the platform's MinIO storage. The claude command picks them up via `--plugin-dir` flags.

A throwaway `hello-world` plugin proves the path end-to-end (already written and run; see `validation-experiment/`).

## Grounding (current state)

### Workflow YAML / domain model

- Pydantic source of truth: `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py`
  - `WorkflowDefinition` (root) at line 272-302 — has `id`, `name`, `description`, `type`, `repository`, `inputs`, `requires_repos`, `project_name`. **No `claude_plugins` field today.**
  - `PhaseYamlDefinition` at line 165-193 — has `id`, `name`, `order`, `execution_type`, `prompt_template`, `prompt_file`, `model`, `max_tokens`, `timeout_seconds`, `allowed_tools`, `argument_hint`. **`allowed_tools` is the natural neighbor for `claude_plugins`.**
- Domain VO: `value_objects.py:53-101` — `PhaseDefinition` is frozen.
- Schema export: `scripts/export_plugin_schemas.py` regenerates `schemas/plugin/workflow.schema.json` from the Pydantic models. CI fails on drift. Adding `claude_plugins:` is forward-compatible (workflow root has no `extra="forbid"`).
- Workflow registration: filesystem scan (`SeedWorkflowService.py:115-177`) plus `POST /workflows/from-yaml` (CLI install path). No DB-backed registry.

### Workspace setup + agent start (validated)

- `WorkspaceProvisionHandler.handle()` at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py:186-242`. Sequence:
  1. `workspace_service.create_workspace()` — line 213-220
  2. Enter context — line 223
  3. `_hydrate_workspace()` → `workspace.run_setup_phase(secrets)` — line 225, 256 (secrets injected as env vars)
  4. Secrets cleared — line 261
  5. `workspace.inject_files()` for AGENTS.md / CLAUDE.md — line 263-274
  6. `_build_provision_result()` — constructs the prompt and Claude CLI command — line 308
- File injection: `ManagedWorkspace.inject_files()` → `WorkspaceService._isolation.copy_to()` → `provider.write_file(...)` (`adapter_copy.py:118-133`). Under the hood: `docker cp`. Already what we need.
- Base image: `ghcr.io/agentparadise/agentic-workspace-claude-cli:latest`. Already supports `--plugin-dir` (per ADR-033 in agentic-primitives) and ships baked-in plugins (`sdlc`, `workspace`, `observability`, `git`) discovered by entrypoint at `/opt/agentic/plugins/`. We add user plugins separately at `/workspace/.syn-plugins/<plugin>/` — does not conflict with baked-ins.
- Container user: `agent` (uid 1000). Workspace owned by agent. Plugin tree we drop in must be writable by agent — `docker cp` honors target ownership, no `chown` dance needed.

### Storage

- MinIO bucket bootstrap: `apps/syn-api/src/syn_api/services/lifecycle.py:320-326` (`_init_artifact_storage` → `storage.ensure_ready()`). Buckets created eagerly per ADR-012. We add a new bucket: `claude-plugins`.
- Artifact storage adapter pattern: `packages/syn-adapters/src/syn_adapters/storage/artifact_storage/minio.py`. Reuse for the plugin storage adapter — same client, different bucket + key shape.
- Storage key for a plugin tree: `claude-plugins/sha256-<hash>/<relative-path-inside-tree>`. Each file uploaded individually so we can reconstruct the tree on read.

### Hierarchy / scopes (only global aggregate-side concern in v1)

- Global plugins live in a projection (`global_claude_plugins`) plus a tiny aggregate (`GlobalClaudePluginRegistry`) that owns the events. One row, one mutable list. CLI commands write events; resolver reads the projection.
- Workflow + phase plugins are declared in YAML and frozen on the `WorkflowDefinition` record at registration time. No domain widening anywhere else.
- Org and system scopes deferred. The `ExecuteWorkflowCommand` does NOT change in v1.

## Design

### Bounded context placement

`ClaudePluginRegistration` aggregate lives **inside the existing `orchestration` bounded context**, alongside `Workspace`, `Workflow`, `WorkflowExecution`. Per ADR-020, multiple aggregates in one context when they share domain language — claude plugins are workspace inputs, same family as the other orchestration aggregates. No new context, no new top-level directory.

```
contexts/orchestration/
  domain/
    aggregate_claude_plugin_registration/         # NEW: per-(source_url, version) plugin
      ClaudePluginRegistrationAggregate.py
    aggregate_global_claude_plugin_registry/      # NEW: singleton list of global plugins
      GlobalClaudePluginRegistryAggregate.py
    events/
      ClaudePluginRegisteredEvent.py              # NEW
      GlobalClaudePluginAddedEvent.py             # NEW
      GlobalClaudePluginRemovedEvent.py           # NEW
    commands/
      RegisterClaudePluginCommand.py              # NEW
      AddGlobalClaudePluginCommand.py             # NEW
      RemoveGlobalClaudePluginCommand.py          # NEW
  slices/
    register_claude_plugin/                       # NEW: explicit single-plugin register (used by global add and by implicit fetch)
    list_claude_plugins/                          # NEW: query handler
    resolve_claude_plugins_for_phase/             # NEW: union of scopes
  ports/
    ClaudePluginStoragePort.py                    # NEW: thin port over MinIO bucket
    ClaudePluginFetcherPort.py                    # NEW: clones git URL at version, returns tree bytes
```

`ClaudePluginRegistrationAggregate` fields:
- `source_url: str` (canonical URL, e.g. `https://github.com/syntropic137/software-leverage-points`)
- `version: str` (whatever was declared — semver tag or raw sha)
- `resolved_sha: str` (sha256 of the tree contents — content-addressed identity)
- `name: str` (display name; defaults to repo basename, overridable via verbose form)
- `tree_storage_prefix: str` (MinIO prefix where tree files live)
- `manifest: dict` (parsed `plugin.json`)
- `registered_at: datetime`

Identity: `(source_url, version)`. Immutable once registered — re-registering the same `(source_url, version)` is a no-op (or returns the existing row).

### YAML extension

Add to `WorkflowDefinition` (`workflow_definition.py:272`):
```python
claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)
```

Add to `PhaseYamlDefinition` (`workflow_definition.py:165`):
```python
claude_plugins: list[ClaudePluginRef] = Field(default_factory=list)
```

`ClaudePluginRef` is a Pydantic model with a `model_validator(mode='before')` that accepts:
- a string and parses GitHub shorthand or git URL form
- a dict for the verbose form

Both produce the same internal shape: `{source_url, version, name, name_overridden}`. Stored on `WorkflowDefinition` and `PhaseDefinition` (frozen tuples).

Schema export pipeline runs as part of `just codegen` — JSON schema regenerates automatically; CI fails on drift.

### Reference resolution at workflow registration time (implicit fetch)

When a workflow YAML is installed:

1. Parse `claude_plugins:` at workflow + every phase. Collect the unique `(source_url, version)` pairs.
2. For each pair, query the `claude_plugin_lock` projection.
3. **Hit:** reuse the existing `resolved_sha` and `tree_storage_prefix`. Move on.
4. **Miss:** dispatch `RegisterClaudePluginCommand` →
   - Fetcher port clones the source URL at the version (semver tag, branch, or raw sha) into a tmp dir.
   - Compute sha256 over the tree contents (sorted file order, content + relative path).
   - Validate `.claude-plugin/plugin.json` exists and parses.
   - Upload every file under the tree to MinIO at `claude-plugins/sha256-<hash>/<rel-path>`.
   - Emit `ClaudePluginRegisteredEvent` with the full lock entry.
   - The `claude_plugin_lock` projection picks it up.
5. Workflow registration only succeeds if every reference resolves. Fail loudly with a clear error per failure type:
   - `unreachable: source URL did not respond / 404`
   - `version_not_found: tag '5.0.7' not found in repo`
   - `not_a_plugin: tree at <ref> missing .claude-plugin/plugin.json`
   - `manifest_invalid: plugin.json schema error: <detail>`

`@latest` and unpinned references are rejected. Reproducibility wins over ergonomics. Add a `latest` resolver later if real demand shows up.

### Resolution algorithm at phase execute time

Pure function `resolve_claude_plugins_for_phase(workflow_def, phase) → tuple[ResolvedPlugin, ...]`:

1. Read `global_claude_plugins` projection → list of `ClaudePluginRef`.
2. Append `workflow_def.claude_plugins`.
3. Append `phase.claude_plugins`.
4. For each ref, look up `(source_url, version)` in `claude_plugin_lock` → `resolved_sha`, `tree_storage_prefix`, `name`.
5. Apply conflict rule by walking the union list once: keep the **last** entry per `(name)` (since we appended in scope order, the last is always the innermost — phase wins over workflow wins over global). Log every override at INFO with the displaced version.
6. Return the deduplicated list.

Determinism: same inputs → same outputs. No I/O during resolution; only a projection read up front. Crash-replay safe (the projection is rebuildable from events).

### Materialization in the workspace

In `WorkspaceProvisionHandler` between line 261 (secrets cleared) and line 263 (AGENTS.md inject):

```python
resolved = await self._claude_plugin_resolver.resolve_for_phase(
    workflow_def=cmd.workflow_definition,
    phase=phase,
)
if resolved:
    plugin_files = await self._claude_plugin_storage.fetch_trees(resolved)
    # plugin_files is list[(workspace_relative_path, bytes)]
    # e.g. (".syn-plugins/software-leverage-points/.claude-plugin/plugin.json", b"...")
    await workspace.inject_files(plugin_files)
```

`ClaudePluginStoragePort.fetch_trees(resolved)` walks each plugin's MinIO prefix, reads every file, and rewrites the keys onto `<workspace>/.syn-plugins/<name>/<rel-path>`. Reuses the existing `inject_files()` docker-cp path. No new injection mechanism, no permission dance (agent owns `/workspace`).

### Wiring `--plugin-dir` flags into the claude invocation

In `_build_provision_result()` (line 308), append one `--plugin-dir /workspace/.syn-plugins/<name>` per resolved plugin to the claude command. The list is passed in alongside the other invocation arguments — same shape as how `AGENTIC_PLUGIN_FLAGS` is appended for baked-in plugins, just from a different source.

This bypasses any reliance on entrypoint-time scanning. Resolution happens after entrypoint runs; the orchestrator constructs the final command with our flags. Validated against the production image — works as expected.

### CLI

New commands in `apps/syn-cli-node/src/commands/claude-plugin.ts`:
- `syn claude-plugin global add <ref>`
- `syn claude-plugin global remove <name>`
- `syn claude-plugin global list`
- `syn claude-plugin list` — list every registered (workflow-or-global-referenced) plugin in the lock
- `syn claude-plugin show <name@version>` — show the lock entry detail

Backed by API routes that call the slice command handlers. Codegen via `just codegen` per CLAUDE.md.

No `syn claude-plugin register <ref>` in v1 — registration is implicit on workflow install or `global add`. If a real "fetch ahead of time" use case shows up, we add it then.

## Test strategy

1. **Unit:**
   - `ClaudePluginRef` parser (string forms + dict form, all error paths).
   - `ClaudePluginRegistrationAggregate` immutability rules (re-register same `(source_url, version)` is a no-op or rejected).
   - `GlobalClaudePluginRegistryAggregate` add/remove/list.
   - Resolver: union, conflict rule, override logging.
   - YAML round-trip with `claude_plugins:` at both levels.
2. **Integration (no Docker, real MinIO from test stack):**
   - Fetcher port against a tiny GitHub fixture repo (or local file URL) — verify clone + sha + upload + lock-row write.
   - `fetch_trees()` round-trip — upload a fixture tree, fetch it, compare bytes.
3. **End-to-end (the canonical proof):**
   - Use the existing `hello-world` plugin from `validation-experiment/`.
   - `syn workflow install` a one-phase workflow that declares `claude_plugins: [test/hello-world@0.0.1]` (registered against a local fixture URL or a fixture push to a test repo).
   - Trigger the workflow with prompt "greet me".
   - Assert agent transcript contains `__SYN_HELLO_726__`.
4. **Replay test:** `ClaudePluginRegisteredEvent` and `GlobalClaudePluginAddedEvent` replay correctly through their aggregates; existing event fixtures keep working with new event types in the registry.

## Rollout / migration

- Pure additive. No existing workflow YAML or event becomes invalid.
- Schema export will produce a diff in `schemas/plugin/workflow.schema.json`; `just codegen` handles it.
- New event types in the projection coordinator registry (`packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py`); new projection (`claude_plugin_lock`, `global_claude_plugins`) registered there.
- New MinIO bucket (`claude-plugins`) added to `_init_artifact_storage()` startup.
- No data backfill. Global / workflow / phase plugin lists start empty.
- No feature flag. The feature is dormant until someone declares `claude_plugins:` in YAML or runs `syn claude-plugin global add`.

## Risks

1. **Container user / `~` resolution** — N/A. We materialize to `/workspace/.syn-plugins/`, not to `~/.claude/skills/`. `/workspace` is owned by `agent`, no permission concerns. Validated.
2. **Plugin manifest variation** — `plugin.json` schema is loose per the official docs (only `name` is conventionally required). Validate at fetch time: parse, check `name`, accept everything else permissively. Reject only on JSON-shape errors.
3. **Concurrent registration of the same `(source_url, version)`** — two workflow installs racing on the same plugin. Solved by `ExpectedVersion.NoStream` on the registration aggregate's first event; second writer sees a version conflict and reads the existing lock row. Pattern already in use; see `WorkflowExecutionProcessor.py:722`.
4. **Plugin tree size** — a 10MB plugin × 5 phases per workflow × N concurrent workflows = bandwidth on the docker-cp path. Mitigation: cache plugin file bytes in-process by `resolved_sha` (LRU). Workspace lifetime is short; cache stays warm during a workflow's phases.
5. **Garbage collection of unreferenced lock entries** — old plugin trees in MinIO whose lock entries no workflow references anymore. Storage is cheap; defer GC. Add `syn claude-plugin gc` later if it grows.
6. **Auth on private plugin sources** — first cut: public sources only. Private GitHub repos require token forwarding to the fetcher. Defer with a clear error: `auth_required: <ref> needs credentials, not yet supported`.
7. **`software-leverage-points` and similar plugins ship with `.claude/skills/` and `.claude-plugin/` and `.codex-plugin/` and `.cursor-plugin/` and `.opencode/` etc.** — confirmed by validation. Materializing the full tree includes all of these. Claude only reads `.claude-plugin/plugin.json` + `skills/`; the rest is harmless tree weight. No filtering needed in v1.

## Cross-perspective tradeoffs

- **DDD purist** wants a `claude_plugins` bounded context. Rejected: single aggregate, shares orchestration's domain language. Splitting now is premature abstraction; merging later if it grows is one rename.
- **Pragmatist** wants `claude_plugins:` to point at git URLs cloned fresh every time. Rejected: violates the issue's "no GitHub / network calls at workspace boot" requirement; reproducibility means lock entries.
- **Operator** wants `syn claude-plugin install <ref>` to fetch immediately so they can inspect before any workflow runs. **Accepted as a follow-up convenience**; v1 fetches implicitly on workflow install or global add. Add explicit register if real use cases show up.
- **Future-self** wants org/system scopes for team-specific plugin defaults. **Out of scope for v1** — needs `ExecuteWorkflowCommand` widening. Pure additive when added later, no v1 rework.

## Out of scope (explicit non-goals)

- Org-level and system-level scopes (deferred; needs ExecuteWorkflowCommand widening)
- Marketplace UI / discovery
- Cross-org plugin sharing
- Runtime plugin install by the agent
- Hot-reload of plugins mid-phase
- `@latest` / unpinned version tags
- Private source auth (token forwarding to fetcher)
- Per-phase markdown-frontmatter `claude_plugins` declaration (workflow YAML only in v1)
- Skill-level resolution within a plugin (we always inject the full plugin)
- GC of unreferenced lock entries

## Sequencing for implementation

Two PRs, per the agreed plan shape:

**PR1 — dormant plumbing (steps 1-5):**

1. New aggregates + events + commands in `orchestration` (`ClaudePluginRegistrationAggregate`, `GlobalClaudePluginRegistryAggregate`).
2. Storage port + MinIO adapter; bucket added to `_init_artifact_storage()`.
3. Fetcher port + git-clone-based adapter.
4. `register_claude_plugin` slice (used by global-add and implicit fetch).
5. `ClaudePluginRef` Pydantic model + YAML schema additions on `WorkflowDefinition` and `PhaseYamlDefinition` + `to_domain()` propagation. Schema codegen runs.
6. `claude_plugin_lock` and `global_claude_plugins` projections; registered in `coordinator_service.py`.
7. `resolve_claude_plugins_for_phase` query handler.
8. CLI commands (`syn claude-plugin global add/remove/list`, `syn claude-plugin list/show`).
9. Implicit fetch wired into `POST /workflows/from-yaml` registration path.

PR1 lands as a no-op feature: anyone can `syn claude-plugin global add ...` and the lock fills up, but no workspace consumes it yet.

**PR2 — the switch (steps 6-7 from the original plan, plus validation):**

1. Wire materializer into `WorkspaceProvisionHandler` between line 261 and 263.
2. Append `--plugin-dir` flags in `_build_provision_result()`.
3. Hello-world end-to-end test running through the platform (re-uses the validation plugin).
4. ADR for the design.

PR2 is small (~80 LOC + the e2e test). Behavior change only takes effect when a workflow YAML declares `claude_plugins:` or a global plugin is set.

CLI commands and docs are folded into PR1 since they're independently shippable and testable.

## Estimated cost

PR1: ~700-900 LOC across ~25 files. Mostly mechanical (aggregate + event + command + projection boilerplate).
PR2: ~100 LOC + an integration test (~150 LOC).

Total: ~1000 LOC end-to-end. Down from the ~2500 LOC original estimate, primarily by:
- Cutting org/system scopes
- Folding into existing `orchestration` context
- Skipping skill/tool/hook abstractions in favor of plugin-as-unit
- Reusing existing `inject_files()` mechanism

Rough wall-clock: 4-6 hours focused work for a single agent, or 2-3 hours with parallel sub-agents on the independent boilerplate sweeps in PR1.

## Open questions for the dogfood pass

1. **Where should the lock projection live in the read-model schema?** Best fit is alongside other orchestration projections in the coordinator registry. Confirm during implementation.
2. **Should `name` overrides cause a lock-entry conflict?** I.e. two workflows reference the same `(source_url, version)` but assign different `name` overrides. Recommend: lock is keyed by `(source_url, version)`; name override is a per-reference concern resolved at materialization time, not stored on the lock. Confirm.
3. **Bucket name** — `claude-plugins` is fine but check for any existing naming convention I missed.

## Reference files

- Plan baseline (this file): `docs/experiments/cycle-004/dogfood-platform-726/plan-local.md`
- Validation experiment + results: `docs/experiments/cycle-004/dogfood-platform-726/validation-experiment/`
- Issue: https://github.com/syntropic137/syntropic137/issues/726
