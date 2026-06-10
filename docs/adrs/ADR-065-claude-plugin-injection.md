# ADR-065: Workflow-Scoped Claude Plugin Injection

- **Status**: Accepted (amended 2026-05-05; see "Amendment" at the end)
- **Date**: 2026-05-04
- **Issue**: [#726](https://github.com/syntropic137/syntropic137/issues/726)
- **Related**: ADR-020 (Bounded Context Convention), ADR-024 (Workspace Setup Phase), ADR-033 (agentic-primitives `--plugin-dir` injection), [ADR-066](ADR-066-separation-of-concerns.md) (Separation of Concerns - amends the resolution-tier choice in this ADR), [#761](https://github.com/syntropic137/syntropic137/issues/761) (org/system scopes follow-up)

## Context

Today, agents inside a Syntropic137 workspace see only the four Claude Code plugins baked into the base image (`sdlc`, `workspace`, `observability`, `git`). Workflows cannot declare additional plugin dependencies. This blocks the `software-leverage-points` review workflow and every future workflow that wants to ship its own skills, hooks, or commands.

The platform needs a primitive for declaring "this workflow needs these claude plugins" in YAML, resolving the references reproducibly, and materializing the resulting tree into each workspace at setup time. The injection mechanics (`<workspace>/.syn-plugins/<plugin>/` plus `claude --plugin-dir <path>`) were proven against the production base image in a standalone validation experiment before this ADR was written. See `docs/experiments/cycle-004/dogfood-platform-726/validation-experiment/` and `run.sh` (10/10 tests passed, including loading the real-world 20-skill `software-leverage-points` plugin with proper namespacing).

## Decision

### 1. Terminology

Always `claude_plugins` in YAML and `ClaudePlugin*` in code. Never bare `plugin`, which collides with Syntropic's existing "workflow plugin" / marketplace concept.

### 2. Bounded context placement

The two new aggregates (`ClaudePluginRegistration`, `GlobalClaudePluginRegistry`) live inside the existing `orchestration` bounded context. Per ADR-020, multiple aggregates belong in one context when they share domain language. Claude plugins are workspace inputs, same family as `Workspace`, `Workflow`, and `WorkflowExecution`. No new top-level context.

### 3. Scopes in v1

The resolved plugin set for a phase is the union of three scopes:

```
global  (set via `syn claude-plugin global add`)
  union workflow.claude_plugins  (workflow YAML)
  union phase.claude_plugins     (per-phase in workflow YAML)
```

Conflict rule: **phase wins over workflow wins over global** (innermost wins). Overrides logged at INFO so they are observable.

Org and system scopes are deferred to [#761](https://github.com/syntropic137/syntropic137/issues/761). They require widening `ExecuteWorkflowCommand` and `WorkflowExecutionStarted` through the dispatch chain. Pure additive when added later, no v1 rework.

### 4. Reference forms

`ClaudePluginRef` is a Pydantic value object that accepts three input forms and normalizes all to one shape:

- GitHub shorthand: `syntropic137/software-leverage-points@5.0.7`
- Full git URL: `https://gitlab.com/foo/bar.git@1.2.0`
- Verbose dict: `{source: ..., version: ..., name: ...}`

`@latest` and unpinned references are rejected. Reproducibility wins over ergonomics.

### 5. Identity, lock, and storage

| Concern | Choice |
|---|---|
| Lock key | `(source_url, version)` -> `resolved_sha + tree_storage_prefix` |
| Aggregate stream id | `claude-plugin-{sha256(source_url\|version)}` (deterministic) |
| Singleton aggregate stream id | `global-claude-plugins` |
| Storage backend | New MinIO bucket `claude-plugins`, content-addressed `sha256-<hash>/...` |
| First-writer-wins | `ExpectedVersion.NoStream` on first event (pattern from `WorkflowExecutionProcessor.py`) |

The bucket is bootstrapped eagerly at startup via `_init_claude_plugin_storage()`, mirroring `_init_artifact_storage()` (per ADR-012).

### 6. Resolution timing

References are resolved (cloned, hashed, uploaded) **at workflow registration time**, not at workspace boot. This is the implicit-fetch contract: `syn workflow install` either fully resolves every plugin into the lock or fails the install. By workspace setup time, resolution is a pure projection read, no network calls.

YAMLs declare semver references for readability. The lock pins the SHA internally. Mixing the two layers gives both readable workflow files and reproducible execution.

### 7. PR2 routing primitive

PR1 ships dormant: aggregates, lock projection, CLI commands, and implicit fetch on workflow install all work; the lock fills up; no workspace consumes anything yet. The PR2 hook is a single field on `ExecutablePhase`:

```python
claude_plugins: tuple[ResolvedClaudePlugin, ...] = ()
```

Default empty. PR2 reads this field in `WorkspaceProvisionHandler`, materializes each plugin into `<workspace>/.syn-plugins/<plugin>/` via the existing `inject_files()` (`docker cp`) path, and appends one `--plugin-dir /workspace/.syn-plugins/<name>` per resolved plugin to the claude command. No claude-CLI changes required (validated).

## Consequences

### Positive

- Reproducible execution via SHA-pinned lock entries; the same workflow definition produces byte-identical plugin trees forever.
- Simple union resolution: pure function, no I/O, crash-replay safe.
- No upstream changes needed in `agentic-primitives` or claude-cli; the `--plugin-dir` injection mechanism (ADR-033 in agentic-primitives) is the supported path.
- SLP-class workflows work end-to-end after PR2 flips the switch.
- Pure additive feature: dormant until a YAML declares `claude_plugins:` or someone runs `syn claude-plugin global add`.

### Negative

- Per-phase granularity is plugin-only. You cannot pick individual skills out of a plugin without authoring a sub-plugin. Acceptable: plugins are the natural unit of distribution in the Claude Code ecosystem.
- First use of a new `(source_url, version)` pays registration latency: clone + hash + per-file MinIO upload. Subsequent uses are projection-read fast.
- No GC of unreferenced lock entries in v1. Storage is cheap; defer until it grows.
- Private sources require auth that v1 does not implement. Failures return a clear `auth_required` typed error.

## Alternatives considered

- **New `skills` (or `claude_plugins`) bounded context.** Rejected as premature abstraction. Single aggregate family, shares orchestration's domain language. Splitting later is one rename.
- **Per-skill resolution rather than per-plugin.** Rejected. Plugins are the natural Claude Code distribution unit and the unit `--plugin-dir` understands. Skill-level resolution would add a layer with no upstream support.
- **All five scopes (global, org, system, workflow, phase) in v1.** Deferred to [#761](https://github.com/syntropic137/syntropic137/issues/761) to keep PR1 focused. Org and system require dispatch-chain widening; v1 ships the three scopes that need no command-shape changes.
- **Path A: flat `<workspace>/.claude/skills/` materialization.** Rejected for namespace collision risk and for losing the per-plugin grouping that `--plugin-dir` provides. Path B (real plugin trees plus `--plugin-dir` flags) chosen and validated.
- **SHA-only YAML refs.** Rejected for readability. Authors write semver in YAML; the platform pins the SHA in the lock.

## Validation

The injection mechanism was validated end-to-end before any platform code was written. Evidence:

- `docs/experiments/cycle-004/dogfood-platform-726/validation-experiment/run.sh` -- 10/10 tests pass.
- `validation-experiment/hello-world/` and `goodbye-world/` -- minimal proof plugins exercising single-plugin and multi-plugin loads.
- Confirmed: `<workspace>/.syn-plugins/<plugin>/.claude-plugin/plugin.json` is the correct on-disk shape; multiple `--plugin-dir` flags coexist; description-matched activation works without forced `/<skill>` invocations; the real-world `software-leverage-points` plugin (20 skills) loaded with the correct `software-leverage-points:<skill>` namespace.

## References

- [#726](https://github.com/syntropic137/syntropic137/issues/726) -- this feature
- [#761](https://github.com/syntropic137/syntropic137/issues/761) -- org/system scopes follow-up
- ADR-020 -- Bounded Context and Aggregate Convention
- ADR-024 -- Workspace setup phase and secret injection
- ADR-033 (agentic-primitives) -- existing `--plugin-dir` injection mechanism this ADR builds on
- Plan: `docs/experiments/cycle-004/dogfood-platform-726/plan-local.md`
- Implementation plan: `~/.claude/plans/steady-soaring-bee.md`

## Amendment (2026-05-05): resolution moved to CLI per ADR-066

Original wording in the "Resolution timing" and "PR2 routing primitive" sections implied that the API container performs the git clone, sha computation, and MinIO upload during workflow registration ("implicit fetch on workflow install"). That placement was a leakage of heavy I/O into the API tier and was caught during the first end-to-end smoke against the dev stack (the `git` binary was missing from the API image; adding it would have masked the underlying separation-of-concerns violation).

[ADR-066](ADR-066-separation-of-concerns.md) is the corrective principle and the redesign moved git work to the CLI tier. Concretely:

- The CLI (`syn claude-plugin install <ref>` and `syn workflow install <yaml>` pre-flight) does the `gitClone`, the tree walk, and the base64 packaging.
- The API exposes a thin `POST /claude-plugins/registrations` endpoint that accepts the pre-built tree as JSON, validates the manifest, computes the SHA, uploads to MinIO, and dispatches the domain command. No subprocess spawn, no `git` binary in the API image.
- The lock projection still pins by `(source_url, version) -> resolved_sha + tree_storage_prefix` and remains the canonical reproducibility primitive. Everything below the resolution tier (aggregates, events, projections, materializer, `--plugin-dir` flag emission) is unchanged.

The amendment does not change any of the locked design decisions in the table above (terminology, bounded context placement, scopes, lock key, conflict rule, materialization path, or rejection of `@latest`). Only the *runtime tier* in which fetch + upload happens moved from the API to the CLI. See `docs/experiments/cycle-004/dogfood-platform-726/redesign-thin-api.md` for the full redesign and `retro-git-in-api.md` for what went wrong and what changed in the agent's process to prevent recurrence.
