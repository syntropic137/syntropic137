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

- **mypy strict mode** — all code must pass
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

## Tooling

- **uv** for Python package management (workspaces)
- **just** for task running
- **Docker Compose** for local and selfhost deployment
- QA: `just qa` runs lint, format, typecheck, test, coverage, vsa-validate
