---
description:
globs:
alwaysApply: true
---
# Syntropic137

## What This Is

Syntropic137 — orchestrates AI agent execution in isolated Docker workspaces and captures every event for observability. Two capabilities: **orchestration** (workspace lifecycle, secure token handling, GitHub App integration) and **observability** (tool use, tokens, costs, errors — all streamed to a real-time dashboard).

The end goal: a `gh`-style CLI (`syn`) that integrates with Claude Code and OpenClaw for agentic workflow automation.

## Architecture

- **Domain-Driven Design** with event sourcing (all state changes are events)
- **Vertical Slice Architecture** — validated by the `vsa` CLI tool from event-sourcing-platform
- **Thin API wrapper** around the domain model (FastAPI)
- **CLI** (`syn`) wraps the API — GitHub CLI-inspired UX

## Repository Structure

```
syntropic137/
├── apps/
│   ├── syn-api/               # FastAPI HTTP server (routes + v1 application services)
│   ├── syn-cli/               # CLI tool ("syn") — HTTP client for syn-api
│   └── syn-dashboard-ui/      # Dashboard frontend (Vite + React)
├── packages/
│   ├── syn-domain/            # Domain events, aggregates, ports
│   ├── syn-adapters/          # Orchestration + observability adapters
│   ├── syn-collector/         # Event ingestion API
│   └── syn-shared/            # Shared settings, configuration
├── lib/                       # Git submodules (we manage both — dogfooding)
│   ├── agentic-primitives/    # Composable agent building blocks, isolation providers
│   └── event-sourcing-platform/ # ES infrastructure, VSA tool, projections
├── infra/                     # Docker Compose, setup wizard, secrets
└── docs/adrs/                 # Architecture Decision Records
```

### Submodules (`lib/`)

Both are our own projects — we dogfood them. If something needs fixing, push the fix directly to the submodule repo. Don't work around it.

- **agentic-primitives**: Agent event recording/playback, Claude CLI/SDK adapters, workspace isolation providers
- **event-sourcing-platform**: Rust event store, Python SDK, VSA validation CLI, projection framework

## Non-Negotiable Rules

### Type Safety (ADR-001 s6, ADR-032)

Treat Python like TypeScript. Strict type safety everywhere.

- **pyright strict mode** — all code must pass
- **No `Any`** without explicit justification
- **No `dict` for structured state** — use `@dataclass` or Pydantic `BaseModel`
- **No string-keyed lookups** when attribute access is possible
- **Pydantic** for all API boundaries, configs, and domain events (`frozen=True`, `extra="forbid"`)
- **All public interfaces fully typed** — no implicit signatures

### Bounded Contexts & Aggregates (ADR-020)

> Reference: [ADR-020](lib/event-sourcing-platform/docs/adrs/ADR-020-bounded-context-aggregate-convention.md), [VSA Quick Reference](lib/event-sourcing-platform/vsa/docs/QUICK-REFERENCE.md)

**Don't:**
- Create top-level context directories for projections — projections go in `slices/` of the owning context
- Put aggregate files directly in `domain/` — use `domain/aggregate_<name>/` folders
- Use generic file names — `WorkspaceAggregate.py` not `aggregate.py`

**Do:**
- Multiple aggregates in one bounded context when they share domain language
- Co-locate entities and value objects with their aggregate root
- A bounded context MUST have `aggregate_*/` folders; projection-only modules are not contexts

| Context | Aggregates | Purpose |
|---------|------------|---------|
| `orchestration` | Workspace, Workflow, WorkflowExecution | Workflow execution and workspace management |
| `agent_sessions` | AgentSession | Agent sessions and observability |
| `github` | Installation, TriggerRule | GitHub App integration, webhook trigger rules |
| `artifacts` | Artifact | Artifact storage |
| `organization` | Organization, System, Repo | Organization hierarchy, system/repo management, insights |

### TODO/FIXME Standard

All TODO and FIXME comments MUST reference a GitHub issue:
- `# TODO(#55): Add integration tests`
- `# FIXME(#72): Race condition in projection`
- Never: `# TODO: Add integration tests`

### Scratch Documentation Policy

Root-level `.md` files (except `README.md`, `AGENTS.md`, `CLAUDE.md`) are scratch — never commit them. Permanent docs go in `docs/` or `docs/adrs/`.

## Key Concepts

### Containerized Agent Execution

Claude CLI runs INSIDE Docker containers, not on the host. `WorkspaceService` creates isolated workspaces, injects secrets during a setup phase (ADR-024), then clears them before agent execution. Agent stdout (JSONL) is captured externally and flows through the observability pipeline.

### Event Storage

`WorkflowExecutionEngine` is the single owner of event recording. It parses Claude CLI JSONL output and records token usage, tool lifecycle, and subagent lifecycle events. All events keyed by `session_id`.

### Testing

Goal: manual testing finds zero bugs — everything caught by automated tests.

- **Unit**: Fast, parallel, no infra needed
- **Integration**: Recording-based playback (no API tokens spent) or ephemeral test stack (ports +10000)
- **E2E**: Real API calls (expensive, few)

Test fixtures auto-detect infrastructure: env vars > test-stack (port 15432) > testcontainers.

## Event Sourcing Architecture

### Two-Lane Architecture

All state and telemetry flows through two strictly separated lanes:

1. **Lane 1: Event Sourcing (Domain Truth)** — Aggregates are the sole decision-makers for state transitions. Commands go in, events come out. The aggregate owns the rules. Infrastructure handlers react to events, do work, and report results back via new commands.

2. **Lane 2: Observability (Telemetry)** — Token counts, tool traces, timing, stream chunks. Append-only, never replayed for state. Writes to observability recorder, NOT the event store. No interaction with aggregates.

### Long-Running Process Orchestration

When orchestrating multi-step processes (e.g., workflow execution with multiple phases):

**Do NOT** use imperative async/await orchestration:
```python
# WRONG — imperative orchestrator
async def execute(workflow):
    for phase in workflow.phases:
        workspace = await provision_workspace(phase)
        result = await run_agent(workspace)
        await collect_artifacts(result)
```

**DO** use the Processor To-Do List pattern:
- **Aggregate** handles commands and emits events, enforces rules, decides "what's next"
- **To-Do List Projection** (read model) builds a list of pending work from events
- **Processor** reads the to-do list and dispatches commands — zero business logic
- **Infrastructure Handlers** react to commands, do async work, emit result events

Flow: `Event → Projection updates to-do list → Processor reads list → Dispatches command → Handler does work → Emits event → cycle repeats`

Key properties:
- Crash-resilient: to-do list persists, processor restarts and picks up where it left off
- All business logic in aggregates and projections, never in the processor
- Each handler is single-responsibility, <200 LOC, independently testable

### When to Use Which Pattern

| Scenario | Pattern | Example |
|----------|---------|---------|
| Multi-step process with infrastructure work | Processor To-Do List | Workflow execution (provision → run → collect → next phase) |
| Simple command → event → done | Direct aggregate command | Creating a workspace, pausing an execution |
| Querying derived state | Projection (read model) | Dashboard metrics, execution list, session tools |
| Time-based triggers (timeouts, SLA deadlines) | Passage of Time (clock events) | Stale execution detection, phase timeout enforcement |

### Projection Consistency in Processor Loops

When a processor needs immediate feedback from its own commands (e.g., "I just completed phase 1, what's the next todo?"), the event subscription pipeline introduces eventual consistency delays. Two strategies:

- **In-process synchronous projection:** The processor maintains a local projection instance. After each `repository.save(aggregate)`, it reads the aggregate's uncommitted events and applies them directly to the local projection. The persistent projection catches up asynchronously for external consumers (dashboard, API). This is the preferred approach for process-local to-do lists.
- **Never** poll the persistent projection waiting for it to catch up — this creates fragile timing dependencies.

### Crash Recovery and Restart Guarantees

The Processor To-Do List pattern is crash-resilient by design:
- **Domain state** is in the event store — fully recoverable by replaying events onto the aggregate
- **To-Do list** is a projection — rebuilt from the event stream on restart (catch-up subscription)
- **Infrastructure state** (active Docker containers, open connections) is ephemeral and NOT in the event stream. On crash, infrastructure is assumed lost. The processor re-provisions from the last completed domain event.
- **Key invariant:** If the processor crashes between "handler did work" and "command reported to aggregate," the to-do item still shows as pending. On restart, the handler re-executes. Handlers MUST be idempotent — re-provisioning a workspace or re-collecting artifacts should be safe.

### Handler Idempotency Rule

Infrastructure handlers MUST be idempotent. If called twice with the same todo item:
- `WorkspaceProvisionHandler`: Creates a new workspace (old one is gone after crash) — safe
- `AgentExecutionHandler`: Re-runs the agent from scratch — safe (stateless container)
- `ArtifactCollectionHandler`: Re-collects from workspace — safe (idempotent writes)

The aggregate enforces ordering via command guards (e.g., reject `CompletePhaseCommand` if phase not in RUNNING state).

### What Goes in the Event Store vs. What Doesn't

| In Event Store (Lane 1) | NOT in Event Store |
|---|---|
| Phase started/completed | Docker container IDs |
| Workspace provisioned (fact that it happened) | Active workspace handles |
| Agent execution completed (tokens, cost, duration) | JSONL stream bytes |
| Artifacts collected (artifact IDs) | Temporary file paths |
| Workflow completed/failed | In-memory caches |

Rule: If you need it after a restart, it must be an event. If it's only needed during the current process lifecycle, hold it in the processor.

### Rules

- Aggregates MUST be the decision-makers — never let an engine/service decide "what's next"
- State MUST be derived from events — no mutable in-memory state (no `ExecutionContext` pattern)
- Observability MUST be separate from domain — telemetry never flows through aggregates
- Long-running processes MUST use Processor To-Do List — no imperative async loops

### References

- Martin Dilger, *Understanding Event Sourcing* — Ch. 37: Processor To-Do List pattern
- Event Modeling specification: https://eventmodeling.org/posts/what-is-event-modeling/
- To-Do List + Passage of Time patterns: https://event-driven.io/en/to_do_list_and_passage_of_time_patterns_combined/

## Tooling

- **uv** for Python package management (workspaces)
- **just** for task running
- **Docker Compose** for local and selfhost deployment
- QA: `just qa` runs lint, format, typecheck, test, coverage, vsa-validate
