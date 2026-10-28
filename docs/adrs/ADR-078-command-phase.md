# ADR-078: Command Phase

- **Status**: Proposed
- **Date**: 2026-10-27
- **Issue**: #2141 (found by the DreamShip build lane, okrs-51p.30, #2140)
- **Related**: ADR-069 (harness-neutral phase definition, D5 apply-or-refuse),
  ADR-024 (setup phase and secret clearing), ADR-072 D9 (event epoch),
  docs/north-star.md

## Context

Every Phase runs an LLM agent. A Phase whose whole job is fixed shell
commands (a build probe, a test gate, an eval referee) still pays for one: the
DreamShip P0 probe runs Sonnet to type `cargo build` and `wasm-pack build`
and wait. That is tokens, latency and non-determinism spent on work with no
judgement in it, and it makes "is the build green" depend on a model obeying a
prompt.

The only no-LLM path today is the Scripted Agent (`syn_perf.loadtest`), which
replaces the agent CLI inside a stub image for load tests. It still runs the
agent path end to end and has no Python seam. The Workspace already exposes the
primitive needed: `ManagedWorkspace.execute(argv, timeout_seconds=...)` returns
an `ExecutionResult` with exit code, duration, stdout, stderr and `timed_out`,
and `run_setup_phase` (ADR-024) already uses it to run a script without an
agent.

## Decision

### D1. A Phase has a kind: `agent` (default) or `command`

`PhaseYamlDefinition`, `PhaseDefinition` and `ExecutablePhase` gain
`kind: PhaseKind = PhaseKind.AGENT`, a `StrEnum` of `agent | command`. A
missing `kind` is `agent`, so every existing workflow is unchanged (ADR-069 D4).

A command Phase declares an ordered, non-empty list of steps:

```yaml
- id: build
  name: Build probe
  order: 1
  kind: command
  timeout_seconds: 1800          # caps the whole Phase, as for agents
  clone_repos: true
  commands:
    - name: cargo-build
      run: cargo build --locked --release
      timeout_seconds: 900       # optional; defaults to the Phase's remaining budget
    - name: wasm
      run: wasm-pack build --release
    - name: report-only
      run: ./scripts/size-report.sh
      allow_failure: true        # recorded, does not fail the Phase
```

`run` is one string executed as `sh -c <run>` in `/workspace`, so `&&`, pipes
and `cd` behave as authors expect. Steps are fixed by the workflow author: no
`{{input}}` substitution into `run` in v1, because templating untrusted inputs
into a shell line is an injection path, and no execution inputs reach the
commands at all (see Not in v1).

`name` is unique within the Phase and matches `^[a-z0-9][a-z0-9-]{0,62}$`: it
names the step's log artifact.

### D2. Apply or refuse (ADR-069 D5)

| field | agent Phase | command Phase |
|---|---|---|
| `commands` | refused | required, non-empty |
| `prompt_template`, `prompt_file` | required | refused |
| `model`, `agent`, `fallback_agent`, `allowed_tools`, `max_cost_usd`, `claude_plugins`, `skills`, `argument_hint`, `max_tokens` | as today | refused |
| `requires_verdict: true` | as today | refused in v1 |
| `delivers_repo_changes` | default `true` | default `false`; `true` refused in v1 |
| `timeout_seconds`, `clone_repos`, `resources`, `input_artifacts`, `platform_access` | as today | applied, same meaning (a referee step may score an eval run under `eval`) |

Refusal happens at parse (`WorkflowDefinition.from_yaml`), naming the Phase and
field, so a workflow is rejected at registration, not mid-run. The two existing
fitness checks (`test_phase_definition_roundtrip`,
`test_phase_schema_fields_apply_or_refuse`) cover the new fields.

### D3. Same to-do list, same Workspace, a different runner

No new `TodoAction`. The flow stays

`PROVISION_WORKSPACE -> RUN_AGENT -> COLLECT_ARTIFACTS -> COMPLETE_PHASE`

and the processor's `RUN_AGENT` branch routes by `phase.kind`: an agent Phase
goes to `AgentExecutionHandler` as today, a command Phase to a new
`CommandPhaseHandler` (<200 LOC) that runs each step with
`workspace.execute(["sh", "-c", run], timeout_seconds=..., working_directory="/workspace")`.

Keeping the action avoids a to-do projection `VERSION` bump and a read-path
rebuild for a routing decision. The cost is that `RUN_AGENT` now means "run the
Phase's runner"; the glossary says so (D7). Renaming the stored action value is
a separate, projection-versioned change and is not worth it here.

Provisioning is the same Workspace, image, limits, repo clone and ADR-024 setup
phase. One difference: `_agents_that_may_run(phase)` is empty for a command
Phase, so no Claude or Codex credential is staged and no agent argv is built.
GitHub repo credentials follow the existing policy and are cleared before the
commands run, exactly as before an agent.

### D4. Execution semantics

- Steps run in order. The first step that exits non-zero or times out, and is
  not `allow_failure`, stops the Phase; every later step is recorded `skipped`.
- A step's timeout is `min(step.timeout_seconds, phase budget remaining)`. A
  timeout is a failure with `timed_out: true`.
- The Phase succeeds iff no non-`allow_failure` step failed. A failed command
  Phase fails the Execution the same way a failed agent Phase does, with
  `error_message` naming the step and its exit code.
- Handlers stay idempotent (CLAUDE.md "Handler Idempotency Rule"): a re-run
  after a crash re-runs every step in a fresh Workspace. Authors of steps with
  external side effects own their idempotency, as agent prompts do today.

### D5. Events: a new `PhaseCommandsCompleted`, not a borrowed agent event

The command runner reports to the aggregate with a new command,
`CompletePhaseCommandsCommand`, which emits a new Lane 1 event
`PhaseCommandsCompleted` v1:

```
execution_id, phase_id, workspace_id, session_id,
success: bool,
steps: list[CommandStepResult]   # name, exit_code | None, duration_ms,
                                 # timed_out, skipped, allow_failure
```

It is not `AgentExecutionCompleted` with zero tokens. That event's name, its
`agent_provider`/`agent_model` fields and its verdict fields would all be lies
for a Phase with no agent, and every consumer reading "an agent ran" would
believe them.

The to-do projection maps `PhaseCommandsCompleted` to `COLLECT_ARTIFACTS`, as
it maps `AgentExecutionCompleted`. That adds a handler for an event type no
stream holds yet, so replay of existing streams is byte-identical and the
projection `VERSION` does not change. `ORCHESTRATION_EVENT_EPOCH` goes to 9 for
the new event type, and its schema snapshot is added.

Exit codes and timing are domain facts (did the gate pass, how long did it
take), so they are in the event. Output text is not.

### D6. Output tails are artifacts; cost is zero by construction

Before reporting, the runner writes into the Workspace's artifact output
directory:

- `commands.json`: the same step results as the event plus, per step, the last
  8 KiB of stdout and of stderr;
- `commands/<name>.log`: each step's combined tail.

The existing `ArtifactCollectionHandler` then collects them exactly as it
collects an agent's output, so they land in object storage, appear in
`syn artifacts`, and `commands.json` is the Phase output the next Phase's
`input_artifacts` receives. Full output stays out of the event store (Lane 1)
because nothing needs it after a restart to decide what happens next.

A command Phase writes no Lane 2 `session_summary` row, and cost is priced from
those rows, so its token count and cost are 0 by construction, not by a special
case. `PhaseCompleted` carries zero tokens and the real `duration_seconds`.

### D7. Vocabulary

`docs/architecture/orchestration-ubiquitous-language.md` gains **Phase Kind**,
**Command Phase**, **Command Step** and the event, and the **Phase** entry
stops saying every Phase has an agent and a model. A Command Phase is not a
Scripted Agent: the Scripted Agent pretends to be an agent for load tests; a
Command Phase is honestly not one.

## Not in v1

- Execution inputs in commands: neither `{{input}}` templating into `run` nor
  environment variables (e.g. `SYN_INPUT_<NAME>`, which a shell never parses as
  code and is the likely first step). Revisit with the first workflow that needs it.
- A verdict from a command Phase (`requires_verdict`), and pushing commits
  (`delivers_repo_changes`). An eval referee can exit non-zero today; a typed
  verdict is a follow-up.
- A no-credential run pool for command-only workflows (cf.
  `RunWorkload.SCRIPTED`). v1 runs in the normal pool.
- Parallel steps, retries per step, streaming output to Lane 2.

## Consequences

- Probes, build gates and referees cost 0 tokens and are deterministic.
- Command Phases and agent Phases compose in one workflow: an agent implements,
  a command Phase gates, at no model cost.
- Event epoch 8 -> 9. A server on epoch 8 cannot load `PhaseCommandsCompleted`;
  the existing `writer_epoch` claim check keeps old Executors off those runs.
- One more runner behind `RUN_AGENT`: anything that assumed `RUN_AGENT` implies
  an agent session (Lane 2 joins, session tools) sees a Phase with no session
  rows, which is the truth.
