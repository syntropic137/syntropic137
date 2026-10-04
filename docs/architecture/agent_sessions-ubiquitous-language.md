# Ubiquitous Language: agent_sessions

## Purpose

The vocabulary of the `agent_sessions` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

For event-sourcing patterns - Event, Aggregate, Projection - see
`es-glossary.md`. A term belongs here when it names something this context's
users talk about, and there when it names a mechanism the platform provides.

Every bounded context has one of these, named
`<bounded-context>-ubiquitous-language.md`. See AGENTS.md, "Ubiquitous Language".

This context is Lane 2: observability. Nothing here is replayed to decide state.

---

## Session

One agent run inside one workspace, identified by a `session_id` the harness
itself emits. A Session belongs to a Phase of an Execution in
`orchestration`, and is the unit everything observable hangs from: tokens,
cost, tool calls, the transcript.

Started by `SessionStarted`, ended by `SessionCompleted`. A Session that never
completed is not an error in itself - the run may have been killed - but it has
no final totals.

## Operation

One thing an agent did inside a Session: a tool call, a file edit, a command.
Recorded by `OperationRecorded`, append-only, and never replayed to derive
state.

The unit the dashboard timeline draws, and the unit `tool_call_count` counts.

## Tool Call

One `tool_use` content block the agent's model emitted in the Session's own
transcript, identified by the harness's `tool_use_id`. The transcript is the
ground truth: a Session's tool calls, counted by tool name, are its transcript's
`tool_use` blocks counted by name, and nothing else.

A Tool Call is recorded as up to two Operations - a start and a completion -
which fold onto one call by `tool_use_id` (`session_tools.call_identity`). An
Agent/Task call whose rows are relabelled `subagent_started`/`subagent_stopped`
is still one Tool Call. `session_tools.is_tool_call` is the rule in code, and
the `GET /events/sessions/{id}/tools` summary counts by it.

These are Operations but **not** Tool Calls:

- **Git operations** (`git_commit`, `git_push`, `git_checkout`, ...). The
  `git` command was a Bash Tool Call and is counted there; the hook's row
  describes what it did. Counting both counted the work twice.
- **Session and phase lifecycle rows.** They have no tool name and used to
  surface in the summary as a tool called "unknown".
- **Event lines the agent printed.** A `tool_execution_started` line inside a
  tool's output - a recorded events file, a test log - is text, not a call.
  Only git hook events are read out of tool output (ADR-043,
  `syn_shared.events.GIT_HOOK_EVENT_TYPES`).
- **A subagent's calls.** Claude puts a subagent's turns on the parent's
  stream, each line marked with the `parent_tool_use_id` of the Agent/Task
  call that spawned it. Those `tool_use` blocks are in the subagent's
  transcript, not the Session's, so they are recorded with that owner and left
  out of the Session's count. The Agent/Task call itself is the Session's, and
  it is counted under the name the transcript has (`Task` or `Agent`), never under the task
  description the timeline shows for it (`ToolOperation.call_name`).

Whether a subagent should become a Session of its own, with its calls counted
there, is a separate question, the same one Delegation below leaves open (#792).

## Agent Launch

The moment a harness process started for a Session (`AgentLaunched`). Distinct
from the Session starting: the Session is the domain fact, the launch is the
process.

## Delegation

One agent handing work to another within a Session - a primary runner invoking
a sub-agent. Bounded by `DelegationStarted` and `DelegationFinished`, and tied
to its parent by `DelegationBound`.

**Unclear:** whether a delegated sub-agent gets a Session of its own or is only
ever Operations inside its parent's Session. The events allow both readings and
issue #792 is open on linking parent to child, so the vocabulary does not
settle it here. Resolve this entry when #792 lands.

## Observation

A recorded fact about an agent's behaviour that carries no domain decision -
token usage, a cost figure, a stream chunk. See `agent_observation.py` and
`observation_payloads.py`.

Observations are Lane 2. An Observation is never the reason state changed; if
something must be replayed to decide state, it belongs in `orchestration`.
