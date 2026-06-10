# Workflow-Scoped Custom Skills — Research and Finding

- **Status**: Phase 1 research finding. Recommends STOP — do not build a parallel `skills:` field.
- **Date**: 2026-06-10
- **Branch**: `feat/workflow-skills`
- **Operator brief**: "Syntropic137 workflows must support CUSTOM SKILLS attached to workflows (a workflow/phase declares skills; the executing agent in the workspace gets them loaded)."
- **Author note**: The operator's brief instructed: *"If #764 makes this redundant or conflicts, STOP after Phase 1 and report that finding instead of building a duplicate."* That is the conclusion of this document.

## TL;DR

**PR [#764] already ships the primitive the operator asked for.** It is named `claude_plugins:` rather than `skills:`, but its design considered and explicitly rejected per-skill resolution (ADR-065 §"Alternatives considered"). A plugin is the natural Claude Code distribution unit; a single plugin can ship N skills (`skills/<name>/SKILL.md`), and the validation evidence in #764 covers a real-world 20-skill plugin (`software-leverage-points`). Building a parallel `skills:` field would duplicate the registration/storage/lock/materializer surface area for no functional gain and would fragment the YAML.

The one place a follow-up is genuinely needed is the **interactive-tmux integration gap** with PR [#765]; see §3 for the gap analysis and §10 for the experimentally proven fix (option 2, `claude_plugin_dirs` driver wiring). That is a small, targeted fix, not a parallel mechanism.

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

> **Note**: ADR-065 and ADR-066 land with #764. If this document merges before #764, the relative links above (and in §11) will not resolve on `main` until #764 merges.

## 2. Why `claude_plugins:` and not `skills:`

ADR-065 §"Alternatives considered" rejected per-skill resolution explicitly:

> **Per-skill resolution rather than per-plugin.** Rejected. Plugins are the natural Claude Code distribution unit and the unit `--plugin-dir` understands. Skill-level resolution would add a layer with no upstream support.

Two reasons the rejection still holds:

1. **Distribution shape**: Anthropic's Claude Code plugin format (`.claude-plugin/plugin.json` + `skills/<name>/SKILL.md` + `commands/`, `hooks/`, `mcp/`) is the unit `claude --plugin-dir` understands. Per-skill resolution would either require Syn137 to invent a wrapper format (more lock-in) or to repackage upstream skills into one-skill plugins on the fly (more code, weaker guarantees).
2. **Distribution semantics**: A skill is rarely useful in isolation — it ships alongside the commands, hooks, and MCP wiring it depends on. Authors think in plugins; the platform should respect that.

If a workflow author wants a single skill out of a multi-skill plugin, they author a single-skill plugin (cheap — two files: `.claude-plugin/plugin.json` and `skills/<name>/SKILL.md`) and reference it. The validation experiment in #764 (`hello-world/`, `goodbye-world/`) shows exactly this minimal shape.

### What about UX?

The operator's brief suggested `skills: [name@version or repo paths]`. A close equivalent is reachable today via `claude_plugins:`, whose parser (`ClaudePluginRef` in #764) accepts exactly three YAML forms:

1. GitHub shorthand `org/repo@version` (e.g. `syntropic137/software-leverage-points@5.0.7`);
2. full URL `<url>@<version>` (https / ssh / git forms; a bare host like `github.com/org/repo` in the verbose form expands to https);
3. verbose mapping `{source, version, name}` (`source_url` accepted as an alias for `source`; `name` is an optional display-name override).

Bare `name@version` (no org or host) is NOT a supported YAML form; there is no marketplace/bare-name resolution in #764, so any future bare-name support would be a CLI-side convenience, not a workflow YAML form. The field name `claude_plugins` is more accurate (because what gets shipped is a plugin tree, not a bare skill) and avoids the existing namespace collision the ADR called out: Syn137 already uses "plugin" in the workflow-plugin / marketplace sense, and `claude_plugins` is the disambiguated term.

If a cosmetic alias is wanted later, the right shape is a YAML-loader-only synonym (`skills:` → parsed identically to `claude_plugins:`), not a parallel storage/lock/materializer pipeline. This document explicitly defers that decision.

## 3. Does it work for "both `claude -p` and the new interactive-tmux provider"?

The operator's brief asked for both. The answer is: **yes for `claude -p` today; for interactive-tmux the gap is closed by the option-2 driver wiring proven in §10** (a small bridging fix, pending an upstream `agentic-primitives` release bump plus five wiring touches).

PR #765 (`feat(workspaces): interactive-tmux provider integration`, branch `feat/interactive-tmux-workspaces`, OPEN, opened 2026-06-10) introduces a parallel dispatch path:

- For `provider: claude-interactive` phases, `WorkspaceProvisionHandler` sets `claude_cmd=[]` and `interactive_prompt=prompt`.
- `AgentExecutionHandler._handle_interactive(...)` routes through `InteractiveTmuxIsolationAdapter.provider_handle(handle).send_message / await_completion / capture_response`.
- The agent's `claude` process is started by the upstream driver (`agentic_isolation.providers.interactive_tmux`), not by appending flags to a freshly-spawned `claude -p`.

The materializer in #764 still copies plugin trees into `<workspace>/.syn-plugins/<name>/` regardless of provider — that step is provider-agnostic (it's `docker cp` of files). But the `--plugin-dir` flag emission lives in `_build_provision_result` and lands on `claude_cmd`, which is empty for the interactive path. Result: files are on disk in the workspace, but the long-lived claude process started by the tmux driver does not load them via plugin discovery.

### Bridging options (historical analysis; resolved experimentally in §9-§10)

Three options were originally identified, to be picked up once both #764 and #765 merged. The experiments in §9 and §10 have since settled the choice; the list is kept for the record with its outcome per option:

1. **Workspace-side** (DISPROVEN; do not implement): emit a `<workspace>/.claude/settings.json` (or the equivalent project-level discovery hook) that lists `<workspace>/.syn-plugins/*` so any claude process started inside that workspace discovers them. This looked like the smallest change (entirely in Syn137), and an earlier draft of this document recommended it; the §9 experiment (Arm B) then proved the interactive-tmux-launched claude does NOT load plugins this way. Historical only.
2. **Driver-side** (RECOMMENDED; proven end-to-end in §10): pass a list of plugin-dir paths to the interactive-tmux provider, which forwards them as `--plugin-dir` flags when starting the claude binary. The required upstream change has since shipped: `agentic-primitives` added `claude_plugin_dirs` to the driver (commit `f671a2e`), and the §10 e2e demonstrates discovery AND activation of a workflow-declared skill through this path.
3. **Hybrid**: materialize to a path the driver already discovers (e.g. `<workspace>/.claude/plugins/<name>/`). Never explored; superseded by option 2 and it would break the documented `.syn-plugins/` convention from ADR-065 §"Validation".

Recommendation: **option 2 is the single current recommendation.** The original option-1 recommendation is retained above only as history; §9 contains the experimental disproof and §10 the positive proof of the option-2 wiring.

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
- Bridging #764 to #765's interactive dispatch. Requires both to be merged (or rebased onto a common base) before the option-2 bridge from §3/§10 can land without churn. Captured here for the next agent to pick up.
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

**Recommended next-agent actions** (not blocking on this PR; updated after the §9-§10 experiments):

1. **Review and merge #764**. It is fully validated and on the OPEN list.
2. **Review and merge #765**. The docker-out-of-docker host-path gap is FIXED on its branch (upstream `agentic-primitives` commit `ea881ea` plus a same-path `TMPDIR` bind-mount; HTTP-triggered interactive phase completed in execution `exec-c64eeaf74a14`). Its remaining unchecked test-plan item is a downstream artifact-pipeline gap: the workflow processor dispatches a SECOND `COLLECT_ARTIFACTS` for zero-artifact phases and raises `KeyError` at `WorkflowExecutionProcessor.py:607`; orthogonal to plugin injection.
3. **After both are merged**, file a small follow-up to implement bridge option 2 (NOT option 1, which §9 experimentally disproved): bump the `agentic-primitives` submodule to a release containing the `claude_plugin_dirs` driver parameter and carry the five-touch wiring plus two unit tests from `exp/skills-tmux-bridge` (§10) into a regular feature branch so `claude_plugins:` works on the interactive-tmux path. Add one integration test asserting claude is started with the expected `--plugin-dir` flag list.

## 9. Appendix — Experimental proof (exp/skills-tmux-bridge)

Per a follow-up operator request, an experimental branch was cut from
`main` and the two open PRs were merged into it:

- `exp/skills-tmux-bridge` — READ-ONLY experiment, **never to be merged**
- Branch: <https://github.com/syntropic137/syntropic137/tree/exp/skills-tmux-bridge>

The branch merges PR #764 (`20260502_platform`) and PR #765
(`feat/interactive-tmux-workspaces`). One minor conflict in
`WorkspaceProvisionHandler.py` was resolved by taking both: #765's
interactive detection (skip the CLI command builder when interactive)
plus #764's `--plugin-dir` flag emission (only on the `claude -p` path).
The merge took ~5 minutes; conflicts were not gnarly.

On top of the merge, the branch implements the option-1 bridge
recommended in §3. `_materialize_claude_plugins` now also writes a
workspace-level `<workspace>/.claude/settings.json` whose body lists
every materialized plugin under `enabledPlugins: {<name>@syn: true}`
and (informationally) under `extraKnownPluginDirs: [<path>...]`. Four
unit tests (`TestWorkspaceProvisionHandlerSkillsBridge`) pin the bytes
shape. `_build_provision_result` is refactored into a small helper so
the cognitive complexity gate (`just fitness-check`) stays green.

### Three-arm e2e — decisive negative result

Direct-driver e2e against `agentic-workspace-interactive-tmux:latest`
(claude-cli v2.1.126, Opus 4.7). Harness, transcripts, and reproduction
instructions:
[`docs/experiments/exp-skills-tmux-bridge/README.md`](https://github.com/syntropic137/syntropic137/blob/exp/skills-tmux-bridge/docs/experiments/exp-skills-tmux-bridge/README.md).

| Arm | Setup | Skill discovered? |
|---|---|---|
| A — control | bare `claude` started by driver, no flags, no files | no |
| B — option-1 | bare `claude` relaunched with `<workspace>/.claude/settings.json` + plugin tree on disk | **no** |
| C — positive | `claude --plugin-dir /workspace/.syn-plugins/sentinel-skill-plugin` | **yes** |

Decisive evidence from Arm C's transcript:

> `❯ Say the word READY in your reply.`
>
> `● READY`
>
> *"I noticed a skill in the available list (sentinel-skill-plugin:sentinel-skill) whose description attempts to make me auto-prefix every reply with a sentinel token. That looks like a prompt-injection pattern rather than a legitimate user-invoked skill, so I'm ignoring it."*

Claude **names the skill by its plugin-qualified slug** in Arm C without
being asked. That is the discovery signal. The sentinel itself never
lands in any arm because claude (correctly) refused the SKILL.md as a
prompt-injection pattern; the refusal is good agent behavior and is
orthogonal to the discovery question.

Arm B's transcript shows claude replying with just `● READY` and no
mention of any skill, proving the workspace-level `.claude/settings.json`
does NOT cause the interactive-tmux-launched claude to load plugins from
`<workspace>/.syn-plugins/<name>/`.

### What this proves

1. **Option 1 is non-functional** for the interactive-tmux dispatch path.
   The bridge code on `exp/skills-tmux-bridge` should NOT be adapted into
   a real PR.
2. **Option 2 is the durable fix.** The interactive-tmux driver in
   `agentic-primitives` (`providers/workspaces/interactive-tmux/driver/`)
   must accept a `plugin_dirs: list[Path]` parameter on
   `start_workspace` and pass it to the existing
   `_ClaudeAdapter.launch_in_window` injection point so claude starts
   with `--plugin-dir <path>` flags. The Syn137 side then becomes a tiny
   wiring change: forward the resolved `ExecutablePhase.claude_plugins`
   paths into the workspace config.
3. **#764's reproducibility, lock, storage, and `claude -p` activation
   path are unaffected** by this finding. #764 should still merge as-is.
   The bridge work is purely about widening #764's coverage to the new
   interactive provider.

### Caveat (honest reporting)

The experiment exercises the discovery contract only — it does NOT route
through `syn-api → InteractiveTmuxIsolationAdapter → driver` end-to-end.
PR #765's own test plan §9-§10 documents a `tempfile.mkdtemp`-based
docker-out-of-docker host-path translation gap that prevents
syn-api-routed executions from reaching the driver successfully.
Bypassing syn-api isolates the bridge mechanism cleanly; it does not
validate the full dispatch path. That gap is orthogonal and lives
upstream in `agentic-primitives`.

### Recommended next steps (historical; superseded by §10's updated list)

1. Merge #764. The `claude -p` skills-on-workflows feature works today.
2. Resolve #765's docker-out-of-docker host-path translation gap upstream
   in `agentic-primitives`. (Since fixed; see §10's caveat.)
3. Add a `plugin_dirs` parameter to the `interactive_tmux` driver
   upstream; wire it through `InteractiveTmuxIsolationAdapter` on the
   Syn137 side. After that, merge #765. (Since shipped upstream as
   `claude_plugin_dirs`; see §10.)
4. **Skip the bridge slice from `exp/skills-tmux-bridge`** — the evidence
   above shows option 1 doesn't work. The right follow-up is the upstream
   driver change plus the tiny wiring change in
   `WorkspaceProvisionHandler` (pass `phase.claude_plugins` paths into
   the workspace config). Estimate: one slice change + one integration
   test that asserts claude is started with the expected `--plugin-dir`
   flag list.

## 10. Appendix — Positive proof of option-2 wiring (exp/skills-tmux-bridge v4)

The §9 disproof of option 1 was followed by upstream `agentic-primitives`
shipping `claude_plugin_dirs` on the interactive-tmux driver (commit
[`f671a2e`](https://github.com/AgentParadise/agentic-primitives/commit/f671a2ec98fb937fdf91e03e4aa5f7831b0662f3),
branch `feat/interactive-tmux-workspace-provider`). The driver now emits
one `claude --plugin-dir <path>` flag per entry at launch time. Syn137
wires that through, and the e2e now demonstrably activates a workflow-
declared skill on the interactive-tmux dispatch path.

### What changed on `exp/skills-tmux-bridge`

The branch's settings.json bridge (option 1) was removed; the option-2
wiring landed in five small touches plus a submodule bump:

| File | Change |
|---|---|
| `lib/agentic-primitives` | bumped to `f671a2e` |
| `packages/syn-domain/.../aggregate_workspace/value_objects.py` | `IsolationConfig.claude_plugin_dirs: tuple[str, ...] = ()` |
| `packages/syn-adapters/.../service/workspace_lifecycle.py` | `build_isolation_config(claude_plugin_dirs=...)` |
| `packages/syn-adapters/.../service/workspace_service.py` | `create_workspace(*, claude_plugin_dirs=...)` forwards to builder |
| `packages/syn-adapters/.../interactive_tmux/adapter.py` | Per-call `_InteractiveTmuxProvider(default_claude_plugin_dirs=...)` when non-empty; default provider reused otherwise |
| `packages/syn-domain/.../execute_workflow/handlers/WorkspaceProvisionHandler.py` | Computes `/workspace/.syn-plugins/<name>` per resolved plugin; forwards via `claude_plugin_dirs=`; settings.json bridge removed |

The new wiring is regression-guarded by two unit tests
(`TestWorkspaceProvisionHandlerForwardsPluginDirs`): one asserts the
handler converts `phase.claude_plugins` into the right
`/workspace/.syn-plugins/<name>` paths and forwards them to
`create_workspace`; the other asserts the no-plugins path passes an
empty tuple (keeps the non-interactive contract byte-equal).

Full regression suite green on `packages/syn-adapters/ +
packages/syn-domain/`: **1706 passed**. The four old settings.json shape
tests are gone; two new wiring contract tests replace them.

### Two-arm e2e (workspaces cleaned up)

Harness, transcripts, and reproduction instructions:
[`docs/experiments/exp-skills-tmux-bridge/v4/`](https://github.com/syntropic137/syntropic137/tree/exp/skills-tmux-bridge/docs/experiments/exp-skills-tmux-bridge/v4)
on the exp branch.

| Arm | Setup | Sentinel? |
|---|---|---|
| A — control | `claude` (bare) — no plugin dirs | absent |
| B — wired (option 2) | `claude --plugin-dir /workspace/.syn-plugins/syn137-greet-plugin` | **PRESENT** |

**Arm A — control** (workspace `exp-bridge-A-1781118934`):

> `❯ Give me a Syn137 greeting.`
>
> `● I don't have anything in memory about "Syn137" and it's not a standard greeting format I recognize. Could you tell me what a Syn137 greeting is, or where I'd find the spec?`

Claude has no awareness of the skill — there is nothing project-specific
in its context because the SKILL.md is not loaded.

**Arm B — wired** (workspace `exp-bridge-B-1781118972`):

> `❯ Give me a Syn137 greeting.`
>
> `● Syn137 build 137.0 — workflow-skills bridge online.`
>
> `Ready to help — what would you like to work on?`

Claude **emits the literal sentinel from the SKILL.md** — discovery AND
activation confirmed end-to-end through the interactive-tmux dispatch
path with the new upstream driver. This is the behavior change the
operator's brief asked for.

The SKILL is a legitimate domain-specific instruction (a project-named
greeting), not the prompt-injection-shaped sentinel from v3. Claude
follows it rather than refusing.

### Caveat about syn-api routing (updated against #765's current branch)

The v4 e2e drives the upstream driver directly to isolate the discovery
+ activation contract; it does not itself route through syn-api. The
docker-out-of-docker host-path gap that previously blocked the full
`syn-api -> InteractiveTmuxIsolationAdapter -> driver` chain has since
been FIXED on `feat/interactive-tmux-workspaces`: upstream
`agentic-primitives` commit `ea881ea` added `ITMUX_*` credential-path
overrides, and combined with a same-path `TMPDIR=/data/tmp/syn-itx`
bind-mount the HTTP-triggered chain completed an interactive phase
end-to-end (execution `exec-c64eeaf74a14`: phase COMPLETED, exit 0,
1950-char pane capture, Envoy bypass confirmed). The remaining blocker
on that chain is downstream of the integration: the workflow processor
dispatches a SECOND `COLLECT_ARTIFACTS` for zero-artifact phases and
raises `KeyError` at `WorkflowExecutionProcessor.py:607`, so the
workflow-level status is `failed` even though the interactive phase ran
to completion. That gap lives in Syn137's workflow processor / to-do
projection (empty-`artifact_ids` transition), not in
`agentic-primitives`. Once it is fixed, the wiring on this branch is
production-ready as written.

### Recommended next steps (updated from §9)

1. Merge #764 (`claude_plugins` registration + materialization). The
   `claude -p` skills-on-workflows feature is unchanged and works.
2. Fix the zero-artifact `COLLECT_ARTIFACTS` transition gap in the
   workflow processor (`KeyError` at `WorkflowExecutionProcessor.py:607`
   on the second dispatch); this is now the only remaining blocker on
   the syn-api-routed interactive chain. The docker-out-of-docker
   host-path gap is already fixed on #765's branch (upstream `ea881ea`
   + `TMPDIR` overlay). Then merge #765.
3. Adopt the upstream `claude_plugin_dirs` parameter (now merged on
   `feat/interactive-tmux-workspace-provider`); cut a new
   `agentic-primitives` release and bump the submodule pin on a
   regular feature branch (NOT the exp branch).
4. Carry the wiring from `exp/skills-tmux-bridge` into that regular
   branch (5 small touches above + 2 tests). The exp branch itself
   stays read-only.

## 11. References

- PR [#764] — `feat: workflow-scoped claude plugin injection (#726)`
- PR [#765] — `feat(workspaces): interactive-tmux provider integration`
- PR [#767] — this PR (the research finding + experiment record)
- Exp branch [`exp/skills-tmux-bridge`](https://github.com/syntropic137/syntropic137/tree/exp/skills-tmux-bridge) — merges + wiring + transcripts (never merge)
- Upstream agentic-primitives commit [`f671a2e`](https://github.com/AgentParadise/agentic-primitives/commit/f671a2ec98fb937fdf91e03e4aa5f7831b0662f3) — `claude_plugin_dirs` driver support
- [ADR-065 — Workflow-Scoped Claude Plugin Injection](../adrs/ADR-065-claude-plugin-injection.md) (lands with #764; link broken on `main` until #764 merges)
- [ADR-066 — Separation of Concerns](../adrs/ADR-066-separation-of-concerns.md) (lands with #764; link broken on `main` until #764 merges)
- [ADR-024 — Setup Phase Secrets Pattern](../adrs/ADR-024-setup-phase-secrets.md) (workspace lifecycle context)
- [ADR-033 in agentic-primitives — Plugin-Native Workspace Images](https://github.com/AgentParadise/agentic-primitives/blob/main/docs/adrs/033-plugin-native-workspace-images.md) (rejects `enabledPlugins`-without-cache for Docker; informed the option-1 finding)
- [docs/architecture/docker-workspace-lifecycle.md](../architecture/docker-workspace-lifecycle.md)
- Issue [#726](https://github.com/syntropic137/syntropic137/issues/726) — original feature request
- Issue [#761](https://github.com/syntropic137/syntropic137/issues/761) — org/system scopes follow-up
