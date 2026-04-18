# 20260413 - Architectural Fitness Audit

## Why This Audit Exists

On service restart, self-healing workflows fire for already-processed PRs,
burning user funds. But restart safety is the **symptom**, not the disease.

The disease is insufficient architectural separation between three concerns
that must never be blended:

1. **Observing facts** - discovering what happened in the external world
2. **Deciding policy** - evaluating whether a fact should cause action
3. **Performing side effects** - executing expensive, irreversible work

When these blur together, the system becomes brittle under restart, replay,
duplication, delay, and partial failure. Every future feature inherits that
brittleness.

This audit establishes clear mental models, finds where boundaries are
violated, fixes the immediate issues, and creates architectural fitness
functions so this class of problem cannot recur.

## The Anchor Question

> "What durable fact proves this workflow has already been considered
> for this exact trigger?"

If we cannot answer this crisply, we do not yet control the architecture.

## The Three-Way Split

Every component in the trigger pipeline must belong to exactly one of these:

| Concern | Responsibility | Replay safe? | Examples |
|---------|---------------|-------------|----------|
| **Fact observation** | Discover external state, normalize it, record it | Yes | Pollers, webhook receivers, event normalizers |
| **Policy decision** | Evaluate rules, check dedup, decide if action is warranted | Yes (deterministic) | Trigger policy, guard checks, dedup ledger |
| **Side-effect execution** | Launch workflows, call LLMs, spend money | **Never** | Workflow launcher, agent executor |

If a single component spans two columns, that is where bugs live.

## Reference

- [docs/architecture/architectural-fitness.md](../../architecture/architectural-fitness.md) --
  the standing checklist for reviewing structural health. Not specific to this
  audit. Use it as the lens for every architectural review going forward.

## Audit Structure

### Phase 1: Understand (Research)

Map the current system against the three-way split. Find where boundaries
are violated.

| # | Area | File | Question |
|---|------|------|----------|
| 1 | Ownership | [01-ownership.md](01-ownership.md) | For each behavior, which component is the single owner of the decision to trigger it? |
| 2 | Replay safety | [02-replay-safety.md](02-replay-safety.md) | Which handlers are replay-safe, and which produce side effects? |
| 3 | Idempotency | [03-idempotency.md](03-idempotency.md) | What is the idempotency key for each trigger, and where is it enforced? |
| 4 | Startup and recovery | [04-startup-recovery.md](04-startup-recovery.md) | What is the startup contract, and what can accidentally create new work? |
| 5 | Temporal | [05-temporal.md](05-temporal.md) | What is the system's definition of "new"? Where are cursors persisted? |
| 6 | Boundaries | [06-boundaries.md](06-boundaries.md) | What is domain logic, what is integration, what is orchestration glue? |
| 7 | Cost control | [07-cost-control.md](07-cost-control.md) | What are the last gates before spend, and are they sufficient? |
| 11 | ESP platform | [11-esp-platform-audit.md](11-esp-platform-audit.md) | What should ESP enforce at the framework level? |
| 12 | ESP gap plan | [12-esp-gap-plan.md](12-esp-gap-plan.md) | Full implementation plan for ESP enhancements |

### Phase 2: Fix (Remediation)

Address the concrete issues found in Phase 1.

| # | Deliverable | File |
|---|------------|------|
| 8 | Findings and fix plan | [08-findings.md](08-findings.md) |
| 9 | Current vs ideal trigger pipeline | [09-pipeline-map.md](09-pipeline-map.md) |

### Phase 3: Prevent (Fitness Functions)

Create automated checks that enforce the three-way split going forward, so
no future feature can reintroduce this class of bug.

| # | Deliverable | File |
|---|------------|------|
| 10 | Architectural fitness functions | [10-fitness-functions.md](10-fitness-functions.md) |

### Implementation Roadmap

| Deliverable | File |
|------------|------|
| Project plan (5 phases, timeline, dependencies) | [PROJECT-PLAN.md](PROJECT-PLAN.md) |
| ESP gap plan (7 sub-phases, full design) | [12-esp-gap-plan.md](12-esp-gap-plan.md) |
| Task tracker | [TASKS.md](TASKS.md) |

## Invariants We Expect to Prove (or Disprove)

1. A workflow trigger has a stable, content-based dedup key
2. No workflow may launch unless its dedup key is first atomically recorded
3. Startup reconciliation may observe state but must not issue new expensive
   work unless that state is proven unseen
4. Projection rebuilds and event replay are side-effect free
5. Polling and webhooks converge on the same canonical trigger identity
6. At most one active workflow exists for a given logical unit of work
7. Expensive actions are guarded at the last responsible moment

## Stress Test Scenario

> Assume the process crashes and restarts 20 times in one hour while 50 PRs
> are open. Walk through exactly what happens and identify every place money
> could be accidentally spent.

This scenario is the acceptance test for the audit.

## Smells to Watch For

If we find logic like this scattered around the codebase, we have a
structural problem, not a bug:

- "if PR open then maybe start workflow"
- "on startup sync open PRs"
- "if not found in memory then create"
- "rebuild state and continue"
- "retry if uncertain"

These indicate the absence of an explicit trigger state machine or
idempotency ledger. That is not code smell - it is cost leakage risk.
