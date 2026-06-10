# Multi-agent workspaces — integration plan

**Status:** Draft (Phase 1 plan, before code)
**Branch:** `feat/multi-agent-workspaces` (stacked on `feat/interactive-tmux-workspaces`, PR #765)
**Owner:** Phase C+ lead
**Last updated:** 2026-06-10

---

## 1. Why

PR #765 (the parent of this branch) wired the single-agent
interactive-tmux workspace provider so a workflow can drive **one**
Claude REPL through `send_message` / `await_completion` /
`capture_response`. The underlying provider — and the swarm container
behind it — already supports three agents in parallel
(EXP-04/04b on `agentprims-lab`, [combined-swarm experiment](https://github.com/AgentParadise/agentic-primitives/blob/agentprims-lab/experiments/EXP-04-combined-swarm-container.md)):
**one container, three tmux windows (`claude` / `codex` / `gemini`),
independent prompt submission per window, concurrent operation
verified across N=3 runs with no cross-talk and ~900 MB total RSS.**

This PR exposes that capability to Syn137 workflows so a single
execution can route different phases to different agents while
sharing workspace state (filesystem) between them. The smallest
viable proof: **phase 1 runs on Claude and writes a file; phase 2
runs on Codex in the same workspace and reads it**.

## 2. Today (after #765)

- `InteractiveTmuxIsolationAdapter` wraps the agentic-primitives
  driver. Constructor accepts a `default_host_auth` dict keyed by
  agent name (`claude` / `codex` / `gemini`). With all three
  credential sets mounted, `start_workspace` brings up a tmux session
  with one window per enabled agent.
- `provider_handle(handle).send_message(agent, prompt)` already
  takes an explicit `agent` argument. The driver's per-agent matrix
  (submit pattern, readiness heuristic, init gates) is fully encoded
  on the agentic-primitives side.
- `WorkflowExecutionProcessor` creates **one workspace per phase**:
  provision → run agent → collect artifacts → complete phase →
  destroy workspace → next phase. Each phase is single-shot.
- `AgentExecutionHandler._handle_interactive()` hardcodes
  `send_message("claude", prompt)` — single agent.
- The YAML schema (`PhaseYamlDefinition`) has **no `agent` block**;
  the `provider`/`agent_id` fields are silently dropped (this is the
  detection gap documented in `interactive-tmux-integration.md` §9).

## 3. Scope of this PR

### In scope (v1)

1. **Workflow YAML schema gains an `agent` block.** Each phase can
   declare which agent it targets:

   ```yaml
   phases:
     - id: write
       agent:
         provider: claude-interactive
         agent_id: claude            # which tmux window
       prompt_template: |
         Write the literal string "hello multi-agent" to
         /workspace/note.txt and confirm.
     - id: read
       agent:
         provider: claude-interactive
         agent_id: codex
       prompt_template: |
         Read /workspace/note.txt and reply with its contents.
   ```

   `agent_id` defaults to `claude` when absent (back-compat with
   PR #765's single-agent workflows).

2. **Workspace lifetime: per-execution, not per-phase, for
   interactive-tmux backends.** When the wiring is configured with
   `provider_kind="interactive-tmux"`, the first
   `PROVISION_WORKSPACE` todo for an execution creates the shared
   workspace; subsequent phases REUSE it. The workspace is destroyed
   at execution completion (success, failure, or cancel) instead of
   at phase completion. The default `claude -p` Docker path is
   unchanged (workspace stays per-phase there).

   Rationale: the EXP-04 swarm container is the natural unit of
   "shared state" — filesystem, claude/codex/gemini panes, runtime.
   Anything else (per-phase containers with bind-mounted scratch
   dirs) is more moving parts for the same effect.

3. **Per-agent dispatch in `AgentExecutionHandler`.** The handler
   reads `phase.agent_config.agent_id` (new field on
   `AgentConfiguration`) and calls
   `provider_handle(handle).send_message(agent_id, prompt)`. Default
   stays `"claude"` so PR #765's behaviour is unchanged.

4. **All three credentials mounted by default** when
   `SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED=true`. The compose overlay
   already mounts `~/.claude` + `~/.claude.json`; extend it to also
   mount `~/.codex` and `~/.gemini` when present, and set
   `ITMUX_CODEX_HOME` / `ITMUX_GEMINI_HOME`. Missing dirs are dropped
   silently (`_default_host_auth_from_env` already handles this).

5. **Lane-2 events per agent.** The synthesized
   `interactive_turn`-shaped Lane-2 capture now carries `agent_id`
   so the dashboard can group per-agent in the same execution.

### Out of scope (explicit non-goals)

1. **Cross-agent autonomy / coordination protocols.** Phase 1 writes,
   phase 2 reads — that's a workflow-orchestrated handoff via the
   shared filesystem. No "agents talking to each other" plumbing
   (no auto-passing pane captures across agents, no shared message
   bus, no agent-to-agent delegate calls).
2. **Concurrent phases.** Phases stay sequential. The driver and
   container support concurrent dispatch (EXP-04b proved this), but
   the workflow processor's to-do list is sequential by design and
   that stays.
3. **Per-phase per-agent token / cost accounting.** Same gap as
   `interactive-tmux-integration.md` §7 #2 — Lane 2 records zero
   tokens for interactive transport in v1.
4. **Codex / Gemini as the DEFAULT phase agent.** Default agent stays
   `claude`. Opting into codex/gemini is per-phase.
5. **Per-phase agent override (e.g., "run phase X on codex in a
   separate sub-workspace").** v1 is one container, multiple panes,
   shared filesystem. Truly isolated per-agent containers belong in
   v2 if we ever need them.
6. **Workflow-level recovery if the shared workspace dies mid-run.**
   The handler treats a dead workspace as a failure on the current
   phase; the remaining phases fail-fast. Restart-from-checkpoint is
   future work.

## 4. Integration points

```
WorkflowExecutionProcessor
   │  per-execution dispatch loop
   │
   ├── _handle_provision  (interactive-tmux backend)
   │     │ if shared workspace exists for execution → reuse
   │     │ else → InteractiveTmuxIsolationAdapter.create()
   │     │       container hosts claude + codex + gemini panes
   │     │       (whichever agents have credentials)
   │     ▼
   │   _shared_workspace[execution_id] = workspace
   │
   ├── _handle_run_agent
   │     │ agent_id = phase.agent_config.agent_id or "claude"
   │     │ AgentExecutionHandler._handle_interactive(
   │     │   workspace, prompt, agent_id=agent_id)
   │     │     send_message(agent_id, prompt)
   │     │     await_completion(agent_id)
   │     │     capture_response(agent_id)
   │     ▼
   │   Lane-2 event { agent_id: "codex", ... }
   │
   ├── _handle_collect_artifacts  (best-effort, may be empty in v1)
   ├── _handle_complete_phase
   │     │ DO NOT destroy workspace
   │     ▼
   └── after final phase or on fail/cancel
         InteractiveTmuxIsolationAdapter.destroy()
```

## 5. Adapter / driver changes needed

- **`InteractiveTmuxIsolationAdapter.create()` accepts an optional
  `agents: tuple[str, ...]` override.** Otherwise it falls back to
  whichever of `claude`/`codex`/`gemini` have credentials in the
  environment (via `_default_host_auth_from_env` — already
  implemented upstream). For v1 the wiring passes no override; the
  default behavior brings up whatever the host has creds for.
- **No changes to the agentic-primitives driver.** EXP-04 already
  proved per-agent dispatch works; the multi-agent surface is
  already exposed via `send_message(agent, prompt)`.

## 6. YAML schema

`PhaseYamlDefinition` gains:

```python
class PhaseAgentSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str = "claude"          # "claude" | "claude-interactive"
    agent_id: Literal["claude", "codex", "gemini"] = "claude"
    model: str | None = None          # carried to AgentConfiguration

class PhaseYamlDefinition(BaseModel):
    ...
    agent: PhaseAgentSpec | None = None
```

`AgentConfiguration` gains an optional `agent_id` field (defaults to
`"claude"`) so the domain layer carries the pane identity end-to-end.
For non-interactive phases, `agent_id` is ignored.

## 7. Test strategy

- **Unit (YAML parser):** a workflow with two phases (`claude` and
  `codex`) parses correctly; `agent_id` is preserved end-to-end into
  `AgentConfiguration`.
- **Unit (handler dispatch):** mocked `provider_handle` records the
  `agent` argument it was called with; verify `phase.agent_config.agent_id`
  flows through correctly.
- **Unit (workspace lifetime):** with `provider_kind="interactive-tmux"`,
  the second phase in the same execution does NOT call
  `adapter.create()` again; cleanup runs once at execution end.
- **Integration (docker-gated, single-agent extension):** the
  existing `test_integration.py` from PR #765 is unchanged; adding
  one new test that drives `codex` instead of `claude` for the same
  workspace would inflate test runtime by another ~35s for low
  marginal value (the per-agent matrix lives in agentic-primitives
  already). Skip.
- **E2E (host with all three creds):** the `claude-then-codex-shared`
  YAML workflow. Phase 1 (claude) writes `/workspace/note.txt`,
  phase 2 (codex) reads it. Both phases share the same Docker
  container. Capture: execution_id, both pane captures, file
  contents observed by codex, proof workspace was reused.

## 8. Rollout

- Same `SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED` flag as PR #765
  gates the entire path. Default off.
- The new shared-workspace lifetime is an internal behaviour change
  for the `provider_kind="interactive-tmux"` factory; no operator
  knob.
- Operators who only have `~/.claude` (no codex / gemini creds) get
  the same behaviour as PR #765 — single-agent container. The
  `agents` enabled set is computed from whichever creds are present.

## 9. Validation appendix

> Filled in during Phase 3.

## 10. Friction log

> Append-only during Phases 2 / 3.

---

## References

- `docs/plans/interactive-tmux-integration.md` — single-agent
  foundation, e2e bring-up evidence, friction log entries shared
  with this PR (same compose overlay, same submodule, same flag).
- `lib/agentic-primitives/experiments/EXP-04-combined-swarm-container.md`
  on `agentprims-lab` — verified single-container three-agent
  swarm with concurrent dispatch, restart survival, footprint
  measurements.
