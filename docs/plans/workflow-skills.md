# Workflow-Scoped Custom Skills — Research and Finding

- **Status**: Phase 1 research finding. Recommends STOP — do not build a parallel `skills:` field.
- **Date**: 2026-06-10
- **Branch**: `feat/workflow-skills`
- **Operator brief**: "Syntropic137 workflows must support CUSTOM SKILLS attached to workflows (a workflow/phase declares skills; the executing agent in the workspace gets them loaded)."
- **Author note**: The operator's brief instructed: *"If #764 makes this redundant or conflicts, STOP after Phase 1 and report that finding instead of building a duplicate."* That is the conclusion of this document.

## TL;DR

**PR [#764] already ships the primitive the operator asked for.** It is named `claude_plugins:` rather than `skills:`, but its design considered and explicitly rejected per-skill resolution (ADR-065 §"Alternatives considered"). A plugin is the natural Claude Code distribution unit; a single plugin can ship N skills (`skills/<name>/SKILL.md`), and the validation evidence in #764 covers a real-world 20-skill plugin (`software-leverage-points`). Building a parallel `skills:` field would duplicate the registration/storage/lock/materializer surface area for no functional gain and would fragment the YAML.

The one place a follow-up is genuinely needed is the **interactive-tmux integration gap** with PR [#765] — see §6. That is a small, targeted fix, not a parallel mechanism.

[#764]: https://github.com/syntropic137/syntropic137/pull/764
[#765]: https://github.com/syntropic137/syntropic137/pull/765

## 1. What #764 already provides

PR #764 (`feat: workflow-scoped claude plugin injection (#726)`, branch `20260502_platform`, OPEN) lands the full primitive:

| Layer | Mechanism |
|---|---|
| YAML | `claude_plugins:` field at both `workflow.claude_plugins:` and `phase.claude_plugins:` scope. Three input forms: GitHub shorthand `org/repo@version`, full git URL `https://host/path.git@version`, and verbose dict `{source, version, name}`. |
| CLI registration | `syn claude-plugin install <ref> [--global]`. CLI clones locally, base64-packs the tree, uploads via `POST /api/v1/claude-plugins/registrations`. Per ADR-066, no `git` in the API container. |
| Storage | Content-addressed `claude-plugins` MinIO bucket keyed by `sha256(source_url|version|name)`. Eager bootstrap at startup (per ADR-012). |
| Lock | Per-registration projection mapping `(source_url, version) → resolved_sha + tree_storage_prefix`. Resolution at workflow-install time; runtime is pure projection-read. |
| Scope union | `phase ⊃ workflow ⊃ global` (innermost wins). Overrides logged at INFO. |
| Materialization | `ClaudePluginMaterializer.fetch_for_workspace(...)` → `<workspace>/.syn-plugins/<name>/...` via `ManagedWorkspace.inject_files()` (docker-cp). Name validation rejects `..`, `/`, control chars at the materialization boundary. |
| Activation | `WorkspaceProvisionHandler` appends `--plugin-dir /workspace/.syn-plugins/<name>` per resolved plugin to the `claude_cmd` list, after `command_builder` runs. |
| Reproducibility | `@latest` and unpinned references are rejected at parse time. |

End-to-end evidence in #764:
- `docs/experiments/cycle-004/dogfood-platform-726/e2e-smoke-pr2.sh` ran multiple times against the dev stack and observed the `__SYN_HELLO_726__` sentinel skill output in the agent transcript. Execution IDs in the PR body.
- The real-world `syntropic137/software-leverage-points@5.0.7` plugin (20 skills) loaded with correct `software-leverage-points:<skill>` namespacing.
- `docker exec syn-api which git` returns nothing → ADR-066 invariant held.

ADRs:
- [ADR-065 — Workflow-Scoped Claude Plugin Injection](../adrs/ADR-065-claude-plugin-injection.md)
- [ADR-066 — Separation of Concerns](../adrs/ADR-066-separation-of-concerns.md) (amends ADR-065's resolution tier)

## 2. Why `claude_plugins:` and not `skills:`

ADR-065 §"Alternatives considered" rejected per-skill resolution explicitly:

> **Per-skill resolution rather than per-plugin.** Rejected. Plugins are the natural Claude Code distribution unit and the unit `--plugin-dir` understands. Skill-level resolution would add a layer with no upstream support.

Two reasons the rejection still holds:

1. **Distribution shape**: Anthropic's Claude Code plugin format (`.claude-plugin/plugin.json` + `skills/<name>/SKILL.md` + `commands/`, `hooks/`, `mcp/`) is the unit `claude --plugin-dir` understands. Per-skill resolution would either require Syn137 to invent a wrapper format (more lock-in) or to repackage upstream skills into one-skill plugins on the fly (more code, weaker guarantees).
2. **Distribution semantics**: A skill is rarely useful in isolation — it ships alongside the commands, hooks, and MCP wiring it depends on. Authors think in plugins; the platform should respect that.

If a workflow author wants a single skill out of a multi-skill plugin, they author a single-skill plugin (cheap — two files: `.claude-plugin/plugin.json` and `skills/<name>/SKILL.md`) and reference it. The validation experiment in #764 (`hello-world/`, `goodbye-world/`) shows exactly this minimal shape.

### What about UX?

The operator's brief suggested `skills: [name@version or repo paths]`. The same UX is reachable today: `claude_plugins: [name@version or repo paths]`. The field name `claude_plugins` is more accurate (because what gets shipped is a plugin tree, not a bare skill) and avoids the existing namespace collision the ADR called out — Syn137 already uses "plugin" in the workflow-plugin / marketplace sense, and `claude_plugins` is the disambiguated term.

If a cosmetic alias is wanted later, the right shape is a YAML-loader-only synonym (`skills:` → parsed identically to `claude_plugins:`), not a parallel storage/lock/materializer pipeline. This document explicitly defers that decision.

## 3. Does it work for "both `claude -p` and the new interactive-tmux provider"?

The operator's brief asked for both. The answer is: **yes for `claude -p` today; partial for interactive-tmux until a small bridging fix lands.**

PR #765 (`feat(workspaces): interactive-tmux provider integration`, branch `feat/interactive-tmux-workspaces`, OPEN, opened 2026-06-10) introduces a parallel dispatch path:

- For `provider: claude-interactive` phases, `WorkspaceProvisionHandler` sets `claude_cmd=[]` and `interactive_prompt=prompt`.
- `AgentExecutionHandler._handle_interactive(...)` routes through `InteractiveTmuxIsolationAdapter.provider_handle(handle).send_message / await_completion / capture_response`.
- The agent's `claude` process is started by the upstream driver (`agentic_isolation.providers.interactive_tmux`), not by appending flags to a freshly-spawned `claude -p`.

The materializer in #764 still copies plugin trees into `<workspace>/.syn-plugins/<name>/` regardless of provider — that step is provider-agnostic (it's `docker cp` of files). But the `--plugin-dir` flag emission lives in `_build_provision_result` and lands on `claude_cmd`, which is empty for the interactive path. Result: files are on disk in the workspace, but the long-lived claude process started by the tmux driver does not load them via plugin discovery.

### Bridging options (out of scope for this PR; flagged for follow-up)

Pick one when both #764 and #765 are merged:

1. **Workspace-side**: emit a `<workspace>/.claude/settings.json` (or the equivalent project-level discovery hook) that lists `<workspace>/.syn-plugins/*` so any claude process started inside that workspace discovers them. Smallest change; lives entirely in Syn137.
2. **Driver-side**: pass a list of plugin-dir paths via `WorkspaceServiceConfig` to the interactive-tmux provider, which forwards them when starting the claude binary. Requires an upstream change in `agentic-primitives` (provider config widening), then a Syn137 wiring change.
3. **Hybrid**: materialize to a path the driver already discovers (e.g. `<workspace>/.claude/plugins/<name>/`). Avoids both a flag and a settings file but breaks the documented `.syn-plugins/` convention from ADR-065 §"Validation".

Recommendation: option 1. It's local, requires no upstream coordination, and matches the "workspace as the unit of context" convention that AGENTS.md / CLAUDE.md hydration already uses (`WorkspaceProvisionHandler._hydrate_workspace`).

## 4. Security / prompt-injection trust model

Skill content is **instruction text the agent will read**. Once a skill is materialized and discovered, its `SKILL.md` is part of the agent's effective system prompt for that phase. This is a real prompt-injection surface and the platform needs to be explicit about who is trusted.

What #764 already enforces:

- **Pinned source**: `@latest` rejected at parse time; references must include a concrete version. The lock pins to a content sha256.
- **Content addressing**: plugin trees stored as `sha256-<hash>/...`; tamper detection is structural.
- **Path traversal**: plugin `name` is validated at the materialization boundary against `..`, `/`, `\`, NUL, leading-dot, and control characters. A hostile name cannot escape `<workspace>/.syn-plugins/<name>/`.
- **Separation of concerns** (ADR-066): the API container does no git work and accepts only pre-packaged JSON; an attacker cannot supply a `source_url` that triggers SSRF or shell injection at the API tier.

What the platform does **not** enforce (and should not pretend to):

- **Skill content review**: the `SKILL.md` body is whatever the author wrote. If a workflow declares `evil/repo@1.0.0` and that repo's `SKILL.md` instructs the agent to exfiltrate credentials, the platform will faithfully materialize it. Trust must come from the operator's choice of plugins.
- **Skill activation gating**: claude's plugin loader activates skills by description match against the agent's context. The platform cannot filter which skills become "live" for any given turn — that's a model-side decision.

**Operating recommendation**: treat `claude_plugins:` like `pip install` — pin versions, use `--global` only for plugins you would trust on every workflow, and prefer per-workflow declarations over per-org globals. Skill content review belongs in the PR that adds the plugin to a workflow, not in the platform.

This trust model is unchanged whether the field is named `skills:` or `claude_plugins:`. A parallel `skills:` field would not add safety.

## 5. Why we are not building a parallel seam

The operator's brief offered two options: extend #764 or build parallel. The parallel option would mean:

- A new YAML field `skills:` with its own parser.
- Either (a) shared storage with `claude_plugins:` (in which case it's a cosmetic alias and the work is two parsers + one validator, not a new pipeline), or (b) separate storage/lock/materializer (in which case it's a literal copy of the 12k-line PR #764 surface area, with a different `_validate_*` and a different MinIO bucket).

Neither produces a feature #764 lacks. The first is renameable later; the second is the duplicate the operator told us to avoid.

The actual operator goal — *"a workflow/phase declares skills; the executing agent in the workspace gets them loaded"* — is met by #764 today for the `claude -p` path and is met for the interactive-tmux path with the bridge from §3 once #765 lands.

## 6. Non-goals (this PR / this plan)

- Implementing a `skills:` YAML alias for `claude_plugins:`. Deferred until the operator decides whether terminology should change. Cheap to add later; cheaper to not add prematurely.
- Bridging #764 to #765's interactive dispatch. Requires both to be merged (or rebased onto a common base) before either bridge option in §3 can be written without churn. Captured here for the next agent to pick up.
- Org-scope and system-scope plugin sets. Already tracked as issue #761 by #764's author.
- Auth for private plugin sources. v1 returns a typed `auth_required` error; deferred per ADR-065 §"Consequences".
- Skill activation gating / sandboxing inside the agent. Out of platform scope; belongs to upstream claude-cli + plugin loader.

## 7. Test strategy

Because we are not shipping new code in this PR, there is nothing to test that #764 has not already tested. For the reader's benefit:

- **Unit**: ADR-065 §"Validation" lists `ClaudePluginRef` parser tests, YAML round-trip tests (`test_workflow_yaml_claude_plugins.py`), materializer tests, resolution-service tests. All green in #764.
- **Integration**: `docs/experiments/cycle-004/dogfood-platform-726/e2e-smoke.sh` and `e2e-smoke-pr2.sh`. Six independent execution IDs cited in the #764 body.
- **Production-image evidence**: the `software-leverage-points` 20-skill plugin loaded against the production base image with correct namespacing, in the validation-experiment cell.

When the bridge from §3 is implemented, it will need a small new test: a workflow that declares `claude_plugins:`, runs through the interactive-tmux provider, and exhibits a SKILL-driven side effect in the captured pane (e.g. a sentinel string from a `SKILL.md`-only plugin, mirroring `__SYN_HELLO_726__`).

## 8. Decision and next steps

**Decision**: STOP Phase 2 / Phase 3. Do not build a parallel skills pipeline. Open a PR with this document only.

**Recommended next-agent actions** (not blocking on this PR):

1. **Review and merge #764**. It is fully validated and on the OPEN list.
2. **Review and merge #765**. Its only unchecked test-plan item is the dod-host-path issue (`tempfile.mkdtemp` inside the syn-api container not reachable by the docker daemon spawning the agent container) — orthogonal to plugin injection.
3. **After both are merged**, file a small follow-up to implement bridge option 1 (`<workspace>/.claude/settings.json` listing materialized plugin dirs) so `claude_plugins:` works on the interactive-tmux path. Estimate: one slice change to `WorkspaceProvisionHandler._materialize_claude_plugins`, plus one integration test.

## 9. References

- PR [#764] — `feat: workflow-scoped claude plugin injection (#726)`
- PR [#765] — `feat(workspaces): interactive-tmux provider integration`
- [ADR-065 — Workflow-Scoped Claude Plugin Injection](../adrs/ADR-065-claude-plugin-injection.md)
- [ADR-066 — Separation of Concerns](../adrs/ADR-066-separation-of-concerns.md)
- [ADR-024 — Setup Phase Secrets Pattern](../adrs/ADR-024-setup-phase-secrets.md) (workspace lifecycle context)
- [docs/architecture/docker-workspace-lifecycle.md](../architecture/docker-workspace-lifecycle.md)
- Issue [#726](https://github.com/syntropic137/syntropic137/issues/726) — original feature request
- Issue [#761](https://github.com/syntropic137/syntropic137/issues/761) — org/system scopes follow-up
