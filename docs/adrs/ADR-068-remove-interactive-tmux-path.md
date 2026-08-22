# ADR-068: Remove the interactive-tmux agent path

- **Status**: Accepted
- **Date**: 2026-08-22
- **Issue**: #771, #768, #777
- **Related**: ADR-027 (workspace provider images), ADR-066 (separation of concerns)

## Context

Between PR #765 and issue #768 the platform carried a second way to drive an
agent: the **interactive-tmux path**. A workspace container ran the agent CLI as
an interactive TUI inside a tmux pane; the orchestrator drove it with
`send_message` / `await_completion` / `capture_response` against the pane, and a
phase opted in with `agent.provider: claude-interactive` plus an
`agent.agent_id` naming which pane (`claude` / `codex` / `gemini`).

It never became trustworthy:

- **Send race.** `send_message` had no acknowledgement. Prompts could land
  before the REPL was ready to receive them.
- **Completion by pane-scraping.** "Done" was a heuristic over rendered
  terminal output, not a protocol signal. `await_completion` returning
  `ready=False` was routine.
- **Empty observability.** The path emits no stream-json, so token counts,
  cost, and tool lifecycle were all zero. Session summaries were synthesised
  with zeros purely so the shape of the record existed. A timeline that says
  nothing is worse than an absent one because it looks like a working run.
- **Ownership drift in the processor.** It required a second `WorkspaceService`,
  a per-execution shared workspace held across phases, a follow-up provisioning
  path that skipped hydration, and an exactly-once teardown carve-out - all of
  which the headless path does not need and all of which had to be reasoned
  about on every change to the processor.

On 2026-07-22 the substrate decision reversed: the single supported way to run
an agent is programmatic docker-exec headless - `claude -p` and `codex exec` -
behind one `AgentRunSpec` / `RunExecutor` contract. That left interactive-tmux
as dead weight held "as a hedge" while continuing to constrain the shared code
it touched.

## Decision

Remove the interactive-tmux path from Syntropic137 entirely.

Concretely:

- `AgentProvider.CLAUDE_INTERACTIVE` is gone. `AgentProvider` is now exactly
  `{claude, codex}` - the two headless harnesses.
- `InteractiveTmuxIsolationAdapter` and the whole
  `syn_adapters.workspace_backends.interactive_tmux` package are deleted, along
  with `WorkspaceServiceConfig.provider_kind` (its only two values were
  `docker` and `interactive-tmux`).
- `WorkspaceImageProvider.INTERACTIVE_TMUX`, its pinned digest, and the
  `SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED` / `SYN_WORKSPACE_INTERACTIVE_TMUX_IMAGE`
  settings are removed.
- `AgentConfiguration.agent_id` is removed everywhere - domain, read model, API
  response, generated CLI/dashboard types, and the published workflow JSON
  schema. It only ever selected a tmux pane; with no panes there is nothing for
  it to select. The skills-CLI harness key now derives from `provider` alone.
- The shared-workspace / follow-up-phase machinery in
  `WorkflowExecutionProcessor` (`_shared_workspaces`, `_cleanup_shared_workspace`,
  `_is_interactive_tmux_backend`, `_workspace_service_for`) and
  `WorkspaceProvisionHandler.build_followup_result` are removed. Every phase
  provisions its own workspace, which is what the headless path always did.
- `docker/docker-compose.dev-interactive-tmux.yaml`, the `just dev-interactive`
  recipe, and the tmux example workflows are deleted.

### Workflows in the wild that still declare `provider: claude-interactive`

They are **rejected at parse time** with an error naming the removal, not
silently remapped to `claude`.

Remapping was the tempting option - it keeps old workflows running. It is the
wrong one. Those workflows were authored against an interactive REPL: their
prompts, their pane choice, and their expectations of a persistent shared
container are all specific to that path. Running them headless would change what
the phase actually does while reporting success, which is exactly the class of
silent behaviour change this codebase treats as a defect. A loud parse error
tells the author what happened and what to switch to.

The removed value is kept as a single named constant,
`syn_shared.agents.REMOVED_INTERACTIVE_PROVIDER`, deliberately NOT an
`AgentProvider` member so nothing can route on it. A `mode="before"` field
validator on `AgentYamlDefinition.provider` intercepts it ahead of the
`Literal["claude", "codex"]` check, so the author sees the removal rather than a
generic enum error.

## Consequences

- One agent execution path. `AgentExecutionHandler` streams a command through
  the workspace and parses stream-json; there is no second dispatch mode, no
  driver protocol, and no thread-based cancel race to reason about.
- Every phase now produces real observability. There is no longer a supported
  configuration that reports zeros.
- Every workspace is per-phase again, so the session-capture probe can answer a
  per-phase question honestly. The `#847` carve-out (shared containers are not
  probed) is no longer needed and is removed with the shared workspace itself.
- `get_workflow_detail`'s projection version is bumped because the stored phase
  shape lost `agent_id`.
- Existing `claude-interactive` workflows must be edited before they run again.
  This is a breaking change to the workflow schema and is why the parse error
  names the replacement providers explicitly.
- Multi-agent-in-one-container is not available and is not planned in this form.
  If cross-harness collaboration returns, it should ride the `AgentRunSpec` /
  `RunExecutor` contract (delegation via `allow_delegation` is the current
  supported shape), not a shared TUI.
