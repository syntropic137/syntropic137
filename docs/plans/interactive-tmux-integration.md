# Interactive-tmux Workspace Provider — Integration Plan

**Status:** Draft — Phase C1 (planning, no code yet)
**Branch:** `feat/interactive-tmux-workspaces`
**Owner:** orchestrator / Phase C lead (this file is authoritative for the
flywheel kickoff)
**Last updated:** 2026-06-10

---

## 1. Why

The default execution path in Syntropic137 builds and runs `claude -p
"<prompt>"` inside a Docker workspace
(`apps/syn-api/src/syn_api/_wiring.py::_build_claude_command` →
`WorkspaceProvisionHandler` → `AgentExecutionHandler.handle` →
`ManagedWorkspace.stream(claude_cmd, ...)`). The Claude `-p` non-interactive
mode is exiting the Max subscription plan; the same OAuth credentials still
work in the *interactive* `claude` REPL.

`AgentParadise/agentic-primitives` validated, on the `agentprims-lab` branch
(branches `agentprims-exp01..05`), a tmux-driven transport: launch the
interactive `claude` / `codex` / `gemini` CLIs inside a Docker container
under `tmux`, and drive them from the host via
`docker exec <ctr> tmux send-keys` / `tmux capture-pane`. That work landed
as a sibling workspace image at
`providers/workspaces/interactive-tmux/` plus a `WorkspaceProvider`-shaped
adapter at
`lib/python/agentic_isolation/agentic_isolation/providers/interactive_tmux/`.

The driver exposes five primitives:

```
ws = InteractiveTmuxWorkspace.start_workspace(name, host_auth=...)
ws.send_message(agent, text)
result: AwaitResult = ws.await_completion(agent, timeout=...)
text: str = ws.capture_response(agent)
ws.stop()
```

The adapter wraps that into the existing
`agentic_isolation.WorkspaceProvider` Protocol (`create / destroy /
execute / write_file / read_file / file_exists`), so Syn137 can plug it
into the same seam it already uses for the Docker provider.

**Goal of this branch:** integrate that adapter as a *sibling* workspace
backend in Syn137 — selectable per workflow phase — without disturbing the
default `claude -p` Docker path.

## 2. Today's seam (what `claude -p` rides on)

| Layer | File | Role |
|---|---|---|
| CLI command | `apps/syn-api/src/syn_api/_wiring.py::_build_claude_command` | Builds `["claude","--model",model,"--verbose","--output-format","stream-json","--dangerously-skip-permissions","-p",prompt, ...allowedTools]` |
| Per-phase config | `packages/syn-domain/.../aggregate_execution/value_objects.py::AgentConfiguration` | `provider: str = "claude"`, `model`, `allowed_tools`. Already per-phase. |
| Workspace lifecycle facade | `packages/syn-adapters/.../service/workspace_service.py::WorkspaceService` | `create_workspace(...)` async-CM; selects backend (DOCKER / MEMORY / LOCAL / RECORDING). |
| Backend selection | `WorkspaceServiceConfig.backend: IsolationBackendType` (`DOCKER_HARDENED`/`LOCAL`/...) | Today picks security profile + `AgenticIsolationAdapter`. |
| Isolation adapter | `packages/syn-adapters/.../workspace_backends/agentic/adapter.py::AgenticIsolationAdapter` | Wraps `agentic_isolation.WorkspaceDockerProvider` for `create / destroy / execute / copy_to / copy_from`. |
| Setup phase (secrets) | `packages/syn-adapters/.../service/setup_phase.py` + `setup_phase_secrets.py` | ADR-024 — git creds + gh auth into the container before the agent runs. Token cleared after. |
| Token injection / sidecar | `SharedEnvoyAdapter` (`workspace_backends/docker/shared_envoy_adapter.py`) + `SidecarTokenInjectionAdapter` | ISS-43 — agents reach a shared Envoy that ext_authz-injects `ANTHROPIC_API_KEY` etc. into outbound calls. |
| Agent execution | `packages/syn-domain/.../slices/execute_workflow/handlers/AgentExecutionHandler.py::handle` | Calls `workspace.stream(claude_cmd, timeout_seconds, environment=agent_env)` → `EventStreamProcessor` parses JSONL → Lane-2 observability events. |
| Pause / resume / inject | `packages/syn-adapters/.../control/controller.py::ExecutionController` | Already has `InjectContext`, `PauseExecution`, `ResumeExecution`, `CancelExecution` commands. This is the existing control plane we'll piggy-back on. |

Reference docs already in-tree:
* `docs/architecture/docker-workspace-lifecycle.md` (ADR-024 two-phase)
* `docs/api/v1/workspaces.md` (the workspaces v1 surface)
* `docs/adrs/ADR-021-isolated-workspace-architecture.md`
* `docs/adrs/ADR-024-setup-phase-secrets.md`

## 3. Integration points (where the new provider plugs in)

```
                                    ┌── _build_claude_command           (today)
                                    │                                    
   AgentConfiguration               ├── _build_interactive_tmux_command  (new)
       │  provider="claude"  ───────┤
       │  provider="claude-tmux"────┤
       └──────────────────────────  │
                                    ▼
WorkflowExecutionProcessor ── WorkspaceProvisionHandler
                                    │
                                    │   uses WorkspaceService.create_workspace
                                    ▼
WorkspaceService  ── WorkspaceServiceConfig.backend
   │
   ├── DOCKER_HARDENED → AgenticIsolationAdapter (claude-cli image, claude -p)
   └── INTERACTIVE_TMUX (new) → InteractiveTmuxIsolationAdapter
                                  └─ wraps agentic_isolation.providers.interactive_tmux
                                     .InteractiveTmuxProvider
                                  └─ image: agentic-workspace-interactive-tmux:latest
                                  └─ mounts ~/.claude + ~/.claude.json (host)
                                  └─ runs `sleep infinity`; tmux session "agents"
                                  └─ AgentExecutionHandler dispatches via:
                                       workspace._handle.send_message(...)
                                       workspace._handle.await_completion(...)
                                       workspace._handle.capture_response(...)
```

### 3.1 Provider selection (per workflow phase)

We add **one knob, two layers**:

1. **Per-phase, declarative:** extend `AgentConfiguration.provider` to
   accept a new value `"claude-interactive"` (in addition to the existing
   `"claude"`). The phase definition in YAML therefore says:

   ```yaml
   phases:
     - id: research
       agent:
         provider: claude            # default path, claude -p
         model: sonnet
     - id: chat
       agent:
         provider: claude-interactive  # new path, tmux REPL
         model: sonnet
   ```

   The provider string is consumed by `WorkspaceProvisionHandler` to pick
   the right command builder + workspace backend kind. We DO NOT introduce
   a new field; we keep using `agent_config.provider` so the schema, YAML
   loader, projections and `AgentSession.agent_provider` stay intact.

2. **Service-level backend selection:** `WorkspaceServiceConfig` gains
   `provider_kind: Literal["docker", "interactive-tmux"] = "docker"`. When
   `WorkspaceProvisionHandler` sees a phase whose `provider ==
   "claude-interactive"`, it asks the workspace service for an
   interactive-tmux-backed workspace. Concretely: we expose a thin
   `WorkspaceService.create_workspace(..., provider_kind="interactive-tmux")`
   override (kwarg, default = service's `provider_kind`), so a single
   service instance can serve both kinds in one execution.

### 3.2 send_message / await_completion mapping

The Processor To-Do List pattern in
`WorkflowExecutionProcessor` already runs each phase as: provision →
agent_exec → collect → next. For interactive-tmux phases, we keep that
same outer loop but swap the inside of `AgentExecutionHandler.handle`:

| Today (claude -p) | Interactive-tmux |
|---|---|
| `workspace.stream(claude_cmd, ...)` yields JSONL chunks; `EventStreamProcessor` parses them. | `ws._handle.send_message("claude", prompt)`; loop: `await_completion(...)` → `capture_response(...)`; emit a single synthetic `assistant_message` event for Lane 2 (no per-token stream in v1). |
| Token usage + tool calls parsed from `stream-json`. | Not available from interactive transport in v1. We record `provider="claude-interactive"` on the agent session and a non-billing `interactive_pane_capture` artifact. UBS-shape token totals are explicitly **deferred** (see §6). |
| Single-shot per phase. | Multi-turn within a phase: see §3.3. |

Implementation seam (new file):
`packages/syn-adapters/.../workspace_backends/interactive_tmux/handler.py::run_interactive_phase(
    workspace, prompt, *, agent="claude", timeout, max_turns=1)`.
`AgentExecutionHandler` dispatches on
`isinstance(workspace._handle, InteractiveTmuxWorkspace)` (or, cleaner, on
the new `WorkspaceServiceConfig.provider_kind` carried on
`ManagedWorkspace`). Either way, **the dispatch lives in
`AgentExecutionHandler`, not in the workspace lifecycle code** — provision
stays uniform, the difference is purely in how the agent runs.

### 3.3 Mid-execution bidirectional comms → existing control plane

`ExecutionController` already speaks four commands: `PauseExecution`,
`ResumeExecution`, `CancelExecution`, `InjectContext`. For interactive
phases we wire these straight through:

* `InjectContext(execution_id, phase_id, message)` →
  `ws._handle.send_message("claude", message)` then
  `ws._handle.await_completion("claude", timeout)`. Result is recorded as a
  `context_injected` Lane-1 event (already exists) plus a Lane-2
  `interactive_turn` capture.
* `PauseExecution` → semantically a no-op for tmux (the REPL is idle
  between turns by design); we still flip the controller state so the
  processor stops dispatching follow-ups.
* `ResumeExecution` → re-enable processor dispatch.
* `CancelExecution` → `ws._handle.stop()` + `cleanup_workspace(...)`.

Out of scope for v1: streaming partial responses back through the
collector. The interactive transport surfaces only "the agent went idle";
we capture the pane *once* at idle. Streaming is a follow-up arc (see §6).

### 3.4 Credential mounting in this repo's Docker stack

The interactive-tmux provider's auth model **bypasses Syn137's Envoy
sidecar by design**. Why: the interactive `claude` CLI does OAuth via
`~/.claude/.credentials.json` + `~/.claude.json` on disk — there is no
outbound API key to inject. The Envoy token-injection adapter
(`SidecarTokenInjectionAdapter`) is therefore **not applicable** on this
path, and we must NOT wire it.

Concretely:

| Concern | Default Docker path (today) | Interactive-tmux path (this PR) |
|---|---|---|
| Anthropic auth | `ANTHROPIC_API_KEY` injected by Envoy via ext_authz | `~/.claude/` + `~/.claude.json` bind-mounted into container |
| GitHub auth | GitHub App token → setup phase → `~/.git-credentials` | Same (setup phase still runs against the interactive-tmux image — see §3.5) |
| Egress isolation | Container on `agent-net`, only Envoy is reachable | Container needs `api.anthropic.com` reachable so the CLI's own HTTPS works; staying on `agent-net` is fine IF Envoy's allowlist already includes that host (it does) |
| Setup-phase secret clearing | `GITHUB_APP_TOKEN` removed after setup | Same — we keep ADR-024 semantics: the Claude OAuth tokens are mounted (file-based, not env-based), so the env-clear step still applies |

**Bind-mount contract:** the host must have `~/.claude/` and
`~/.claude.json` on the user the VPS runs the orchestrator as. The
agentic-primitives EXP-05a finding is unambiguous: **both** must be
mounted, individually they fail. The driver's
`_ClaudeAdapter.prepare_host_auth` already builds the throwaway copies +
synthesises a pre-seeded `.claude.json` (onboarding markers + per-project
trust); we accept that as-is.

**Failure mode:** if `~/.claude/` is missing on the host (fresh VPS, no
operator login), `start_workspace` raises before any container starts. We
surface that as a `WorkspaceProvisionError` with an actionable message:
"interactive-tmux requires ~/.claude on the orchestrator host; run
`claude login` on the host or fall back to provider=claude (claude -p)".

### 3.5 Setup phase compatibility

The interactive-tmux image's entrypoint is `sleep infinity` and the driver
launches `tmux new-session` post-start. That means our existing setup
script (`packages/syn-adapters/.../service/setup_phase_secrets.py`) cannot
just be the `docker run` command — but it doesn't need to be. The setup
phase runs via `workspace.run_setup_phase(secrets)` which goes through
`provider.execute(workspace, "/workspace/setup.sh", env=...)`. The
interactive-tmux adapter implements `execute()` as a plain `docker exec`,
so this works unchanged. We do need the interactive-tmux image to ship a
working `setup.sh` (git + gh + identity) at `/workspace/setup.sh` — the
agentic-primitives `Dockerfile` already inherits the same base shape, but
we verify this in C2 and, if missing, contribute the script upstream.

## 4. The smallest viable seam (what Phase C2 will change)

In priority order, no more than is needed:

1. **Vendor the driver** OR rely on submodule path. The adapter at
   `lib/agentic-primitives/lib/python/agentic_isolation/agentic_isolation/providers/interactive_tmux/`
   already auto-resolves `interactive_tmux.py` by walking up from its own
   location. Since we have the submodule, **no vendoring needed for v1** —
   the adapter finds the driver via
   `lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py`.
   Risk: agentic-primitives currently pins to `main` (not `agentprims-lab`).
   We bump the submodule pointer to `agentprims-lab` HEAD (or whatever
   commit on that branch lands the provider + adapter) in this PR.

2. **New isolation adapter (Syn137 side):**
   `packages/syn-adapters/src/syn_adapters/workspace_backends/interactive_tmux/__init__.py`
   exports `InteractiveTmuxIsolationAdapter` mirroring
   `AgenticIsolationAdapter`'s public shape (`is_available`, `create`,
   `destroy`, `execute`, `copy_to`, `copy_from`, `health_check`). It wraps
   `agentic_isolation.providers.interactive_tmux.InteractiveTmuxProvider`,
   imported from the submodule.

3. **Backend wiring:** `WorkspaceServiceConfig.provider_kind` field;
   `WorkspaceService._create_docker_impl` branches on it (`"docker"` →
   `AgenticIsolationAdapter` as today; `"interactive-tmux"` →
   `InteractiveTmuxIsolationAdapter`). No new public enum value yet — we
   keep `IsolationBackendType` semantically about the security profile
   (`DOCKER_HARDENED` etc.) and orthogonally control the *image+driver*
   via `provider_kind`. This keeps every other adapter (memory, recording)
   untouched.

4. **Command builder dispatch:** in `_wiring.py`, factor `_build_command`
   to look at `phase.agent_config.provider`:
   * `"claude"` → existing `_build_claude_command` (returns the
     full `claude -p ...` argv).
   * `"claude-interactive"` → returns an empty list `[]` (signal to
     `AgentExecutionHandler` that this phase is driven by
     `send_message`/`await_completion`, not `stream`). The prompt text is
     carried separately on the `ProvisionResult` (new field
     `interactive_prompt: str | None = None`).

5. **AgentExecutionHandler dispatch:** if `claude_cmd == []` and
   `workspace._handle` quacks like `InteractiveTmuxWorkspace`, take the
   interactive path: `send_message → await_completion → capture_response`.
   Record one synthetic Lane-2 event per turn (`interactive_turn` —
   message in, pane out, duration_ms). Single turn in v1.

6. **Feature flag (rollout safety):** add
   `SYN_INTERACTIVE_TMUX_ENABLED` (default `false`) to
   `packages/syn-shared/src/syn_shared/settings/workspace.py`. When false,
   any phase declaring `provider: claude-interactive` is **rejected at
   workflow-template creation time** with a clear error (not silently
   falling back to `claude -p`, which would hide misconfigurations). The
   default remains `claude -p`. Tracking issue and the rollout knob both
   live in `WorkspaceSettings` so they show up under `just sync-env`.

## 5. Test strategy (Phase C3)

| Layer | What we run |
|---|---|
| Unit — adapter | `tests/workspace_backends/interactive_tmux/test_adapter.py` — patch the agentic_isolation provider with a stub; verify create/destroy/execute round-trip, `provider_kind="interactive-tmux"` selects the new adapter in `WorkspaceService`, `is_available()` reads `shutil.which("docker")`. No real Docker required. |
| Unit — command builder dispatch | `tests/wiring/test_command_dispatch.py` (new) — `provider="claude"` builds `claude -p ...`; `provider="claude-interactive"` returns `[]` and carries the prompt out-of-band. |
| Unit — flag gate | Workflow-template creation with `provider: claude-interactive` and `SYN_INTERACTIVE_TMUX_ENABLED=false` raises a typed error; with `=true` it succeeds. |
| Integration | `tests/workspace_backends/interactive_tmux/test_integration.py` (skip if no Docker + no `~/.claude/`) — start a workspace, run `execute("echo hi")`, run a single `send_message → await_completion` round, assert `AwaitResult.ready` and a non-empty pane capture. |
| End-to-end | One real workflow execution against a one-phase workflow whose phase has `provider: claude-interactive` and a trivial prompt ("Reply with the literal string OK."). Asserts: agent session created, exit code 0, single artifact captured, no Envoy token injection attempted. Recorded as evidence in the §9 Validation appendix. |
| QA gates | `just qa` end-to-end: `ruff check`, `ruff format --check`, `pyright`, `pytest`, `vsa-validate`, `just fitness-check`, `just docs-sync`. |

We do NOT add a new live recording fixture in v1; the recording backend
keeps shadowing `claude -p`. Recording the interactive transport is a
separate arc (see §6).

## 6. Rollout

* **Phase 1 (this PR):** feature flag `SYN_INTERACTIVE_TMUX_ENABLED=false`
  by default; the new adapter ships but no production workflow uses it.
  CI runs the new unit + adapter tests; the integration + e2e tests are
  marked `skipif` on missing Docker/host creds. Default `claude -p` path
  is unchanged.
* **Phase 2 (follow-up issue, not this PR):** flip the flag on a dedicated
  dogfooding workflow ("interactive-chat-spike"), watch operator
  experience for one week.
* **Phase 3 (follow-up):** expose `claude-interactive` in the workflow
  YAML schema docs + `apps/syn-docs/`; record the first real customer
  workflow that uses it.
* **Phase 4 (later):** consider whether interactive becomes the default
  for chat-shaped workflows once we can attribute token usage without
  `stream-json` (likely via `~/.claude/projects/<ws>/sessions/*.jsonl`
  capture).

Rollback: flip `SYN_INTERACTIVE_TMUX_ENABLED=false`; existing executions
running on the new path drain naturally (the workspace context manager
cleans up on next event). No data migration required.

## 7. Explicit non-goals (v1)

The following are **out of scope** for this PR and will not be addressed
unless they block the goal stated in §1:

1. **Per-token streaming for interactive transport.** The driver returns
   pane captures at idle, not per-token. We do not synthesise a fake
   stream.
2. **Authoritative token / cost accounting.** No
   `result_input_tokens`/`result_output_tokens` from this path in v1.
   Lane-2 session_summary fields will be 0 for interactive phases; the
   dashboard's cost-by-phase widget will show zero, and that is
   documented behaviour.
3. **Codex / Gemini providers.** The image hosts all three but Syn137
   exposes only `provider: claude-interactive` in v1. Codex/Gemini wiring
   is a separate decision (subscription economics, dashboard cost-model,
   provider-conditional prompt templates).
4. **MCP / plugin parity with the claude-cli image.** The interactive-tmux
   image ships with no plugins by design (per its manifest). Pulling
   plugin parity is its own arc.
5. **Multi-turn within a phase.** The control plane already supports
   `InjectContext`, but the runtime piping (collector turns,
   per-turn Lane-2 events, conversation projection) needs follow-up
   design. V1 supports one turn per phase; multi-turn is a documented
   later step.
6. **Replacing the Envoy sidecar.** The sidecar stays in place for the
   default path; we just don't wire it on the interactive path.
7. **Provider selection at runtime via API.** Selection is per-phase in
   the workflow definition (YAML). The HTTP API does NOT yet accept
   "override the provider for this execution" — that's a v2 affordance.

## 8. Open questions tracked in this branch

* **`workspace._handle` typing.** Today `ManagedWorkspace` carries
  `isolation_handle: IsolationHandle` plus a private `_workspaces` dict on
  the adapter. For interactive-tmux we need access to the underlying
  `InteractiveTmuxWorkspace` object (for `send_message` etc.). Decision:
  expose a `provider_handle` accessor on `ManagedWorkspace` that the
  interactive adapter populates with the `_handle` (the
  `agentic_isolation.Workspace._handle`). The default Docker path leaves
  it `None`. **Decision recorded in this plan; verify in C2.**
* **Submodule branch pin.** The provider + adapter live on
  `agentprims-lab`. Pin our submodule there in this PR. Track upstream
  merge into `main` in a follow-up issue and re-pin to `main` once it
  lands.

## 9. Validation appendix (filled in during Phase C3)

> Empty in C1. Phase C3 records here, in order:
>
> 1. `just qa` exit code + duration.
> 2. Output of the new unit-test files.
> 3. Output of the integration test (if Docker + host creds available),
>    else the documented "skipped" reason.
> 4. The end-to-end workflow run: workflow YAML used, execution_id,
>    exit_code, pane capture excerpt, links to the resulting events in the
>    event store.

## 10. Friction log (filled in across C2/C3)

> Append-only. Each entry: timestamp, what hurt, how we worked around it
> (only if working around — first preference is to fix upstream and link
> the agentic-primitives change here).

---

## References

* `docs/architecture/docker-workspace-lifecycle.md` — ADR-024 setup phase.
* `docs/api/v1/workspaces.md` — workspaces v1 surface.
* `docs/adrs/ADR-021-isolated-workspace-architecture.md`
* `docs/adrs/ADR-023-workspace-first-execution-model.md`
* `docs/adrs/ADR-024-setup-phase-secrets.md`
* `lib/agentic-primitives/providers/workspaces/interactive-tmux/README.md`
  (on `agentprims-lab`) — the EXP-05 design.
* `lib/agentic-primitives/lib/python/agentic_isolation/agentic_isolation/providers/interactive_tmux/__init__.py`
  (on `agentprims-lab`) — the WorkspaceProvider adapter we wrap.
