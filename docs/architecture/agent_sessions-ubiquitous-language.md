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

## Observability

Telemetry about how the running platform and its agents behave: tokens, cost,
tool calls, timing, and operational signals such as API request latency
(ADR-075). Lane 2: append-only, never replayed, never read by an aggregate.
Served under `GET /observability/*` and the `syn observe` command group
(`tools`, `tokens`, `latency`). Observability is the concept; `observe` is the
CLI verb for it.

Not **Insight**. "Insights" is reserved for learning-loop analytics, lessons
about how to improve workflows, speed and cost, owned by `organization` (see
`organization-ubiquitous-language.md`). We do NOT call request latency an
insight.

## Session

One agent run inside one workspace, identified by a `session_id` the harness
itself emits. A Session belongs to a Phase of an Execution in
`orchestration`, and is the unit everything observable hangs from: tokens,
cost, tool calls, the transcript.

Started by `SessionStarted`, ended by `SessionCompleted`. A Session that never
completed is not an error in itself - the run may have been killed - but it has
no final totals.

## Requested Model and Observed Model

Two different facts about which model a Session used, never conflated
(ADR-067 D9). The **requested model** is what the phase asked for, often an
alias such as `gpt-sol`; `SessionStarted` records it (as `agent_model`, its
historical name) and the session summary keeps it as `requested_model`. The
**observed model** is what the harness reported it ran, such as
`gpt-6.1-sol`, carried on Lane 2 observations as `model` and served as
`agent_model`.

A running codex Session has only the requested model until its stream ends,
and is displayed as `gpt-sol (requested)`. The observed model replaces that
display once it is known.

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

## Cost by Token Type

A Session's priced cost split into input, output, cache write and cache read
(`SessionCost.cost_by_token_type`). Its parts sum to the priced total, and its
**basis** says how they were arrived at:

- `rate_table` - every priced part is tokens x that type's rate.
- `allocated` - some part of the total was a harness-reported figure, which
  states no split; it is apportioned in the rate table's proportions. An
  estimate, and labelled as one.

Absent (null), never zeroes, when no split can be stated: a read path that
does not compute it, or a reported total for a model with no rate, which has
no proportions to apportion by. Unpriced work is in neither the total nor the
split, the same rule as cost by model.

## Inventory Reconciliation

Rebuilding one run's session inventory snapshot from host evidence, one durable
`InventoryReconciliation` job per evidence watermark. The job advances in steps
(pending, publishing, then a terminal stage), and each step is an event.

- **Stale step:** the job's projected row is behind its aggregate in the event
  store, so the step handler runs nothing. A stale step is not progress and is
  never counted as processed (#1528).
- **Park:** after a step runs or turns out stale, its job is set aside until
  the manager projects a newer event for it. A park has no timer.
- **Re-arm:** projecting a newer open step makes a parked job claimable again.
  A newer terminal step drops the job instead.
- **Coalesce:** while a run has an open job, new evidence for that run waits.
  The next job picks up the latest watermark, so one job is minted per
  catch-up and not one per watermark.
