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

Refusal happens twice, as for `execution_type` and the sandbox level: at parse
(`WorkflowDefinition.from_yaml`), naming the Phase and field, so a workflow is
rejected at registration; and again in `ExecuteWorkflowHandler` through one
`require_consistent_phase_kind(phase)` rule, because a stored template never
passes the YAML validator. Workflow-level `claude_plugins` and `skills` are not
merged into a command Phase. The existing fitness checks use fixed tables, so
they get explicit rows and kind-conditional cases, not an assumption that they
cover new fields.

### D3. Same to-do list, same Workspace, a different runner

No new `TodoAction`. The flow stays

`PROVISION_WORKSPACE -> RUN_AGENT -> COLLECT_ARTIFACTS -> COMPLETE_PHASE`

and the processor's `RUN_AGENT` branch routes by `phase.kind`: an agent Phase
goes to `AgentExecutionHandler` as today, a command Phase to a new
`CommandPhaseHandler` (<200 LOC). Keeping the action avoids a to-do projection
`VERSION` bump for a routing decision. The cost is that `RUN_AGENT` now means
"run the Phase's runner"; the glossary says so (D9).

Agent machinery is branched off by kind at every place that builds it today,
not by emptying one helper:

| where | agent Phase | command Phase |
|---|---|---|
| `ExecuteWorkflowHandler` (`ExecutablePhase` build) | agent config, plugins, skills, fallback | none; `kind` and `commands` carried |
| `WorkspaceProvisionHandler` (`_codex_auth_staged_for`, `_build_provision_result`, `_launch_for`) | prompt, argv, agent env, Claude/Codex auth | skipped: no prompt, no argv, no model credential |
| `phase_workspace` session start, `phase_runtime` finalise | `SessionLifecycleManager` | skipped: a command Phase has no agent session |
| `agent_attempts` | retries, fallback agent, cost limit, invocation registration | bypassed entirely |

`CommandPhaseHandler` runs each step through a new transport method,
`ManagedWorkspace.run_bounded(argv, *, timeout_seconds, working_directory,
tail_bytes, phase_deadline)`, on the same event-stream transport `stream()` uses, and
returning a typed `BoundedCommandResult`:

```
terminal: exited | timed_out | interrupted | failed_to_start
exit_code: int | None        # set only when terminal == exited
duration_ms: int
tail: str                    # last tail_bytes of COMBINED stdout+stderr, scrubbed
dropped_bytes: int           # output not retained
```

Neither existing method fits. `execute` buffers both channels whole on the
executor (`docker_operations.py`). `stream` yields decoded lines, so
`LineDecoder` (`stream_adapter.py`) holds an unterminated line whole and a build
that prints without newlines grows executor memory; it also folds a provider
timeout into the exit code (`stream_adapter.py`), so `exit 124` and a timeout
look the same. `run_bounded` consumes raw chunks into a ring of `tail_bytes`
(8 KiB), keeps the terminal state separate from the exit code, and applies
the credential withholding `stream` applies (#1927) to each chunk with a
carry-over window as long as the longest withheld value, so a secret split
across chunks is still withheld before anything is retained. It also injects
the Phase's `platform_access` grant, as `stream` does.

Output is combined, not per channel: the transport already merges stdout and
stderr in arrival order, and an interleaved tail is what a person reads to see
why a build failed.

Cancellation is explicit, not inherited: the handler runs the existing
`CancelSignalPoller` pattern beside the step, so a cancel arrives during quiet
and noisy output alike. On cancel it calls `workspace.interrupt()`, the step
ends `interrupted`, partial results and the tail are kept, later steps are
`skipped`, and the handler returns a cancellation outcome that the processor
routes through `ExecutionCancelledEvent` as for an agent.

### D4. Execution semantics

- Every `timeout_seconds` (Phase and step) is a positive integer; zero,
  negative and non-integers are refused at parse. Zero would otherwise reach
  Docker as "no timeout" and fall back to the workspace default
  (`adapter.py`).
- One monotonic deadline per Phase, set when the first step starts. A step gets
  `min(step.timeout_seconds, deadline - now)`; when that is not positive the
  step is not started, it and every later step are recorded `skipped`, and the
  Phase fails as timed out.
- Steps run in order. The first step that exits non-zero or times out, and is
  not `allow_failure`, stops the Phase; later steps are recorded `skipped`.
- The Phase succeeds iff no non-`allow_failure` step failed AND the Phase
  deadline was not exhausted. `allow_failure` excuses a step's exit code and
  its own step timeout, never the Phase's.
- A re-run after a crash re-runs every step in a fresh Workspace (D6). Authors
  of steps with external side effects own their idempotency, as agent prompts
  do today.

### D5. Events and failure

The handler reports to the aggregate with `RecordPhaseCommandsCommand`, which
emits a new Lane 1 event, `PhaseCommandsCompleted` v1:

```
execution_id, phase_id, workspace_id,
success: bool, timed_out: bool,
steps: list[CommandStepResult]   # name, outcome (passed|failed|timed_out|skipped|interrupted|failed_to_start),
                                 # exit_code | None, duration_ms, allow_failure
```

No `session_id`, no agent provider or model: a command Phase has no agent
session, and the event says so by not carrying one. It is not
`AgentExecutionCompleted` with zero tokens, because that event's name, its
agent provenance and its verdict fields would all be false for a Phase with no
agent.

The to-do projection maps `PhaseCommandsCompleted` to `COLLECT_ARTIFACTS`
whatever `success` says, so the logs of a failed gate are kept. The aggregate
decides what that means: `artifacts_collected` for a Phase whose recorded
command outcome is a failure does NOT select the next Phase; it fails the
Execution with `WorkflowFailed`, the event `fail_execution()` writes on the
agent failure path today (`failure_teardown.py`), carrying `error_message`
naming the step and exit code and `failure_classification: gate`. That is new
aggregate behaviour (collection deciding failure), not a reuse of an existing
branch. `COMPLETE_PHASE` is never queued for a failed command Phase and no
later Phase runs.

`FailureClassification` gains `GATE = "gate"`: a step the author declared
exited non-zero or hit its own timeout. The platform ran it correctly and it
said no. It is kept out of `PLATFORM` for the reason #1357 exists: a red build
gate reported as a platform failure inflates the platform failure rate with
the system working as designed. A step that could not be started (exec error,
workspace lost) is `PLATFORM`.

The new event type, and the new fields in `ExecutablePhase` inside existing
events (`WorkflowExecutionStarted.pinned_phases`, template events), move
`ORCHESTRATION_EVENT_EPOCH` to 9 with a complete epoch-9 snapshot. The
projection manager's event routing (`manager_event_map.py`) registers the new
event. Replay of existing streams is unchanged: no stream holds the new event
and the new fields default to `agent`.

### D6. Restart recovery

| crash point | durable state | recovery |
|---|---|---|
| before `PhaseCommandsCompleted` | to-do is `RUN_AGENT` | re-provision, re-run every step |
| after `PhaseCommandsCompleted`, before collection | to-do is `COLLECT_ARTIFACTS`, workspace gone | collect from the event: write `commands.json` from the recorded step results, with `tails_lost: true` and no tails, then continue as normal (succeed or fail per D5) |
| after `ArtifactsCollectedForPhase` | artifacts in object storage | unchanged from agent Phases |

The exit codes and timing are the gate's result and are in the event, so a
lost workspace loses only the output tails, never the verdict. This replaces,
for command Phases, the agent-only stranded salvage that reads
`last_agent_message`.

### D7. Output, credentials and cost

Before reporting, the handler writes into the Workspace's artifact output
directory `commands.json` (the step results plus each step's combined tail,
at most 8 KiB, and `dropped_bytes`) and, for a step with output, `commands/<name>.log`. A step
with no output gets no log file, because the collector treats an empty file as
a failed artifact (`ArtifactCollector.py`); `commands.json` is never empty. The
collector is told to mark `commands.json` primary explicitly rather than
relying on collection order.

Tails are scrubbed inside `run_bounded` (D3) before they are retained, and
collection's own scrubbing applies again to the written files.

**Credentials, stated plainly.** No Claude or Codex credential is staged. The
GitHub authority is the existing policy's and is NOT cleared: ADR-024 keeps
`~/.git-credentials` and the `gh` credential for the Phase's repositories, so a
command step has the same GitHub reach as an agent in that workspace, including
the ability to push. `delivers_repo_changes: false` is a statement about what
the gate judges, not a permission. A command Phase is author-written code
running with the Phase's repository credentials; it adds no authority the
agent did not already have, and removes the model credentials.

**Cost.** A command Phase writes no Lane 2 `session_summary` and no
`token_usage` rows, the two sources cost is priced from, so its tokens and
cost are 0. `PhaseCompleted` carries zero tokens and the real
`duration_seconds`. Tests prove 0 through the API read (execution detail and
cost) for success, failure and resume, rather than inferring it.

### D8. Which repository state a command Phase sees

The Phase's workspace is checked out at the Execution's start pins
(`start_pins.py`), exactly like any fresh Phase. It does NOT see commits an
earlier agent Phase pushed. A command Phase therefore gates the start revision
(the DreamShip probe, an eval referee on a pinned case), not "the change the
previous Phase just made". Gating a previous Phase's branch needs a typed,
recorded head handoff and is not in v1.

### D9. Vocabulary

`docs/architecture/orchestration-ubiquitous-language.md` gains **Phase Kind**,
**Command Phase**, **Command Step**, `PhaseCommandsCompleted` and the `gate`
failure class, and **Phase** stops saying every Phase has an agent and a model.
`RUN_AGENT` is defined as "run the Phase's runner". A Command Phase is not a
Scripted Agent: the Scripted Agent pretends to be an agent for load tests; a
Command Phase is honestly not one.

## Not in v1

- Execution inputs in commands: neither `{{input}}` templating into `run` nor
  environment variables (e.g. `SYN_INPUT_<NAME>`, which a shell never parses as
  code and is the likely first step).
- Gating a previous Phase's pushed head (D8).
- A typed verdict from a command Phase (`requires_verdict`), and pushing as a
  deliverable (`delivers_repo_changes: true`).
- A no-credential run pool for command-only workflows (cf.
  `RunWorkload.SCRIPTED`). v1 runs in the normal pool.
- Parallel steps, per-step retries, streaming step output to Lane 2.

## Consequences

- Probes and gates on a pinned revision cost 0 tokens and are deterministic.
- A failed gate is `gate`, not `platform`, in every failure rate.
- Event epoch 8 -> 9. The `writer_epoch` claim check
  (`execution_runs/postgres.py`) keeps an epoch-8 Executor off runs written at 9.
- Anything that assumed every Phase has an agent session sees a Phase with
  none, which is the truth; dashboard session links must handle it.
