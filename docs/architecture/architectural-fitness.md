# Architectural Fitness

## Purpose

This is the standing reference for reviewing the structural health of
Syntropic137. It is not about any single bug or audit. It defines the
principles that make the system reliable, maintainable, and scalable by
construction - not by luck.

Use this document as the lens for every architectural review, every PR
that touches the trigger or execution pipeline, and every incident
post-mortem.

---

## The Fundamental Principle

Every component in the system must have **one job** and must belong to
**exactly one** of three concerns:

| Concern | What it does | What it must never do |
|---------|-------------|---------------------|
| **Observe** | Discover facts about the external world | Decide whether to act, or act |
| **Decide** | Evaluate policy, apply rules, check guards | Observe external state, or execute effects |
| **Execute** | Perform irreversible, expensive work | Decide policy, or observe facts |

When a single component spans two concerns, bugs become structural.
When all three blur into one component, the system is uncontrollable.

In an event-sourced agentic system where side effects cost real money
(LLM calls, container compute, GitHub API calls), a violated boundary
is a cost leakage vector.

---

## 1. Single Ownership

### Principle

For every behavior in the system, exactly one component owns the decision.

### What to check

- Can two components independently decide to start the same workflow?
- Can two event sources trigger the same action without converging first?
- Is there a clear chain of custody from external fact to expensive action?
- Can you draw a straight line from trigger to execution with no forks?

### Red flags

- The same decision made in two places "just in case"
- A poller that both discovers facts AND decides what to do about them
- A projection that both reconstructs state AND dispatches commands
- Retry logic that re-makes decisions instead of re-executing them

### The test

> "For this behavior, name the single component that owns the decision.
> If you cannot name exactly one, the ownership is unclear."

---

## 2. Separation of Concerns

### Principle

Observation, decision, and execution are separated by explicit boundaries
with well-defined interfaces between them.

### What to check

- Does each file in the pipeline map to exactly one concern?
- Are the interfaces between stages typed and narrow?
- Can you swap the observation layer (polling vs webhooks) without
  touching the decision layer?
- Can you replay the entire event store without triggering a single
  side effect?

### Red flags

- A handler that imports both an HTTP client and a domain aggregate
- A poller that emits commands instead of facts
- An event subscription that calls external APIs during catch-up
- Business rules embedded in infrastructure adapters

### The test

> "If I replace the observation layer with a test harness that feeds
> synthetic facts, does the rest of the system behave identically?"

---

## 3. Replay Safety

### Principle

Replaying events from the event store must never produce side effects.
Only forward-path processing through the live pipeline may cause action.

### What to check

- Are projections pure functions of events? (no side effects)
- Does catch-up subscription replay go through the same path as live
  processing? If so, is the side-effecting branch gated?
- Can a process restart cause historical events to re-trigger work?
- Is "reconstruction" cleanly separated from "reaction"?

### Red flags

- A projection that dispatches workflows when it processes events
- No distinction between "replaying historical event" and "processing
  new event" in subscription handlers
- Catch-up and live subscriptions sharing a callback that has side effects
- State rebuilt on startup that feeds directly into a trigger evaluator

### The test

> "Replay every event in the store from position 0. Assert that zero
> external calls were made, zero commands were issued, zero money was
> spent."

---

## 4. Idempotency

### Principle

Every trigger path has a stable, content-based dedup key that is
durably recorded before the side effect executes. The system enforces
"cannot have effect twice" - it does not assume "will not happen twice."

### What to check

- What is the dedup key for each trigger source?
- Is the dedup key content-based (deterministic from the fact) or
  synthetic (generated per attempt)?
- Is the dedup check durable (database) or volatile (in-memory)?
- Is the dedup recording atomic with command issuance?
- What happens when the dedup infrastructure is unavailable?

### Red flags

- Dedup keys in memory (lost on restart)
- Fail-open dedup (skip check when Redis is down)
- Dedup checked early in the pipeline but not at the last gate
- Synthetic IDs (UUIDs) used as dedup keys (every attempt looks new)
- "If not found in memory, create" patterns

### The test

> "Submit the same external fact 10 times through every possible entry
> point. Assert that exactly one workflow execution exists."

---

## 5. Startup Contract

### Principle

The service has an explicit, documented startup contract that
distinguishes between reconstruction (safe) and reconciliation
(dangerous). Startup never creates new expensive work without proving
the work is genuinely unseen.

### What to check

- What happens on startup? (rebuild projections, resume work, rescan
  external state, backfill triggers, emit commands?)
- Which of those actions can create new work?
- What guard prevents historical state from being mistaken for new state?
- Is the guard durable across restarts?

### Red flags

- Startup code that "syncs" external state and feeds it into the
  trigger pipeline without dedup
- Projection catch-up that replays side-effecting event handlers
- Pollers that start with no cursor and re-poll the entire history
- No distinction between "cold start" and "warm restart"

### The test

> "Restart the service 20 times in one hour with 50 open PRs. Assert
> that zero spurious workflow executions are created."

---

## 6. Temporal Clarity

### Principle

The system has an explicit, consistent definition of "new" for each
event source. Progress is tracked with durable cursors. The system
does not pretend to have stronger ordering guarantees than reality
provides.

### What to check

- What makes an event "new"? (unseen ID, unseen SHA, unseen delivery,
  cursor position, wall clock?)
- Are cursors persisted durably and atomically with processing?
- Does the system handle out-of-order delivery from external sources?
- Does the system handle duplicate delivery from external sources?

### Red flags

- "New" means "not in memory" (everything is new after restart)
- Cursors not persisted (poller restarts from the beginning)
- Assuming GitHub events arrive in order
- Assuming polling sees intent history rather than current state snapshots

### The test

> "Deliver the same GitHub event via webhook, then again via polling,
> then again via a second webhook retry. Assert that one canonical
> event is recorded and one trigger evaluation occurs."

---

## 7. Cost Boundaries

### Principle

Every expensive action has a hard gate at the last responsible moment.
The gate is durable, atomic, and cannot be bypassed by retries, restarts,
or concurrent processing.

### What to check

- What is the last check before an LLM call, container launch, or
  API write?
- Is that check durable (survives restart)?
- Is that check atomic with the action (no gap between check and do)?
- Is there a rate limit or budget ceiling?
- What is the blast radius of a guard failure?

### Red flags

- Guards early in the pipeline but not at the point of spend
- No rate limit on workflow executions per repo per hour
- No budget ceiling per user or organization
- Guard checks that are advisory (logged but not enforced)

### The test

> "What is the maximum number of workflow executions that can be
> created in one hour for a single repo, and is that number bounded
> by design or unbounded by accident?"

---

## 8. Boundary Clarity

### Principle

Domain logic, integration logic, and orchestration glue are in separate
modules with explicit interfaces. No module mixes concerns.

### What to check

- Can you point to the domain logic and say "this is the domain"?
- Can you point to the integration adapters and say "these talk to
  external systems"?
- Is there orchestration glue? Does it contain business logic?
- Are bounded context boundaries respected?

### Red flags

- Domain aggregates that import infrastructure
- Integration adapters that contain business rules
- "God services" that coordinate everything
- Orchestration glue that makes policy decisions

### The test

> "Remove all infrastructure adapters and replace with in-memory fakes.
> Does the domain logic still pass all unit tests without modification?"

---

## 9. Scalability by Design

### Principle

The architecture does not rely on single-process guarantees (in-memory
state, asyncio locks, process-local singletons) for correctness. It is
safe under concurrent workers and horizontal scaling.

### What to check

- What state is in-memory only? What happens when it is lost?
- Are locks process-local (asyncio.Lock) or distributed?
- Can two instances of the service run simultaneously without conflict?
- Are projections and processors partitioned or globally exclusive?

### Red flags

- In-memory dedup sets or caches used for correctness (not just perf)
- asyncio.Lock used to prevent duplicate work (only works in one process)
- Singleton patterns that assume one instance
- "Leader election" as a TODO rather than an implementation

### The test

> "Run two instances of the service pointing at the same event store
> and the same external sources. Assert that each workflow is executed
> exactly once, not twice."

---

## How to Use This Document

### During feature development

Before implementing a feature that touches the trigger pipeline,
event processing, or workflow execution:

1. Identify which concern the new code belongs to (observe/decide/execute)
2. Verify it lives in the correct module for that concern
3. Verify it does not cross concern boundaries
4. Verify the dedup key covers the new trigger path
5. Run the restart safety test

### During code review

For any PR that touches the trigger or execution pipeline:

1. Check single ownership - does the PR introduce a second decision point?
2. Check replay safety - can the new code be reached via event replay?
3. Check idempotency - is there a durable dedup key for the new path?
4. Check startup safety - does the new code run during startup catch-up?

### During incident review

When a duplicate execution, cost overrun, or restart storm occurs:

1. Identify which boundary was violated
2. Trace the exact code path from fact to side effect
3. Identify the missing invariant
4. Determine whether the fix belongs in domain, application, or infra
5. Add a fitness function that prevents recurrence

---

## The North Star

A system is architecturally fit when you can answer these questions
without hesitation:

1. **Who owns the decision?** Exactly one component, and I can name it.
2. **Is it replay-safe?** Replaying the entire event store causes zero
   side effects.
3. **Is it restart-safe?** Restarting 20 times with 50 open PRs causes
   zero spurious executions.
4. **Is it dedup-safe?** The same fact arriving 10 times through 3
   different channels causes exactly one action.
5. **Is it cost-safe?** There is a hard, durable gate before every
   dollar spent.

If any answer is "I think so" or "usually," the architecture is not yet
under control.
