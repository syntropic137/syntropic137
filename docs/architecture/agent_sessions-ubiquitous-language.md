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
