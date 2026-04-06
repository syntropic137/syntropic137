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
│   ├── syn-cli-node/          # CLI tool ("syn") — Node.js, HTTP client for syn-api
│   ├── syn-dashboard-ui/      # Dashboard frontend (Vite + React) — operational UI
│   ├── syn-docs/              # Public-facing documentation site (Next.js + Fumadocs)
│   └── syn-pulse-ui/          # Pulse/heatmap UI
├── packages/
│   ├── syn-domain/            # Domain events, aggregates, ports
│   ├── syn-adapters/          # Orchestration + observability adapters
│   ├── syn-collector/         # Event ingestion API
│   └── syn-shared/            # Shared settings, configuration
├── lib/                       # Git submodules (we manage both — dogfooding)
│   ├── agentic-primitives/    # Composable agent building blocks, isolation providers
│   └── event-sourcing-platform/ # ES infrastructure, VSA tool, projections
├── infra/                     # Docker Compose, setup wizard, secrets
├── docs/                      # Internal/local development docs (ADRs, architecture notes,
│                              #   deployment guides) — NOT the public docs site
└── docs/adrs/                 # Architecture Decision Records
```

> **Docs vs syn-docs:** `docs/` is internal — local dev guides, ADRs, architecture references for contributors. `apps/syn-docs/` is the public-facing documentation site deployed externally. Content for the public docs site lives in `apps/syn-docs/content/`.

### Submodules (`lib/`)

Both are our own projects — we dogfood them. If something needs fixing, push the fix directly to the submodule repo. Don't work around it.

- **agentic-primitives**: Agent event recording/playback, Claude CLI/SDK adapters, workspace isolation providers
- **event-sourcing-platform**: Rust event store, Python SDK, VSA validation CLI, projection framework

## Non-Negotiable Rules

### Type Safety (ADR-001 s6, ADR-032)

Treat Python like TypeScript. Strict type safety everywhere.

- **pyright** — all code must pass (`standard` mode, ratcheting to `strict`)
- **No `Any`** without explicit justification
- **No `dict` for structured state** — use `@dataclass` or Pydantic `BaseModel`
- **No string-keyed lookups** when attribute access is possible
- **Pydantic** for all API boundaries, configs, and domain events (`frozen=True`, `extra="forbid"`)
- **All public interfaces fully typed** — no implicit signatures
- **API routes MUST use Pydantic response models** — never `-> dict[str, Any]`. FastAPI generates the OpenAPI spec from return type annotations. Untyped routes are invisible to the spec, which breaks the CLI type generation pipeline (`openAPI spec → openapi-typescript → CLI types`). Always define a response model and use it: `async def list_foos() -> FooListResponse:`

### API → CLI Type Pipeline

Single source of truth for the API contract, fully automated:

```
Pydantic models (syn-api/types.py)
  → FastAPI generates OpenAPI spec (/openapi.json)
    → openapi-typescript generates TypeScript types (syn-cli-node/src/generated/api-types.ts)
      → CLI commands use typed client (compile-time path + response validation)
```

**Key files:**
- `apps/syn-api/src/syn_api/types.py` — All response/request models (single source)
- `apps/syn-cli-node/src/generated/api-types.ts` — Auto-generated, never hand-edit
- `apps/syn-cli-node/scripts/generate-types.ts` — Regeneration script
- `apps/syn-cli-node/scripts/check-api-drift.ts` — CI drift detection

**Workflow — adding/changing an endpoint:**
1. Define Pydantic response model in `apps/syn-api/src/syn_api/types.py`
2. Use it as the route return type: `async def list_foos() -> FooListResponse:`
3. Run `just codegen` — regenerates OpenAPI spec, API docs, CLI types, and CLI docs in one step
4. Use the typed client in CLI commands: `import { api } from "../client/typed.js";`

**Rules:**
- CLI field names MUST match API response model field names exactly — never use legacy/alias names
- Domain model field names (e.g. `event`, `repository`) flow through to API responses and CLI — keep them consistent across all three layers
- CI `check:api-drift` fails if generated types are stale
- New CLI commands SHOULD use the typed client (`api.GET`, `api.POST`) — existing commands are being migrated incrementally

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

| Context | Aggregates | Key Operations | Purpose |
|---------|------------|----------------|---------|
| `orchestration` | Workspace, Workflow, WorkflowExecution | Create, archive (soft-delete), execute, pause/resume/cancel | Workflow execution and workspace management |
| `agent_sessions` | AgentSession | Start, record operations, complete | Agent sessions and observability |
| `github` | Installation, TriggerRule | Register, configure, fire triggers | GitHub App integration, trigger rules, hybrid event pipeline (webhooks + Events API + Checks API polling with dedup) |
| `artifacts` | Artifact | Create, upload, retrieve | Artifact storage |
| `organization` | Organization, System, Repo | CRUD, assign/unassign repos to systems | Organization hierarchy, system/repo management, insights |

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

### Hybrid Event Ingestion (ADR-050, #602)

GitHub events enter the system through a unified `EventPipeline` that accepts events from three sources:

1. **Webhooks** — Real-time delivery (~1s) from GitHub. Primary path when the App is configured with a reachable URL.
2. **Events API polling** — Background `asyncio.Task` that polls GitHub's Events API for 17 event types (PR, push, etc.). Enabled by default for zero-config onboarding.
3. **Checks API polling** — Background `asyncio.Task` that polls `GET /repos/{o}/{r}/commits/{sha}/check-runs` for CI results. Triggered when a `pull_request` event registers a head SHA. Enables self-healing without webhooks (#602).

All three sources normalize payloads into `NormalizedEvent` and feed `EventPipeline.ingest()`. Content-based dedup keys (commit SHA, PR number, check run ID — not delivery IDs) ensure the same logical event is processed exactly once regardless of source.

| Source | API | What it gets | Config |
|--------|-----|-------------|--------|
| Events API poller | `GET /repos/{o}/{r}/events` | 17 event types (PR, push, etc.) | Always on |
| Webhooks | Push-based | All 60+ event types including `check_run` | Needs tunnel/public URL |
| Checks API poller | `GET /repos/{o}/{r}/commits/{sha}/check-runs` | CI results for specific SHAs | Auto when `check_run` triggers exist |

**Mode switching:** Both pollers adapt their interval based on webhook health:
- **ACTIVE_POLLING** (60s / 30s) — No webhooks received in 30 minutes; poll aggressively
- **SAFETY_NET** (300s / 120s) — Webhooks healthy; poll infrequently as a catch-up net

**Fail-open dedup:** If Redis is unavailable, events are processed anyway. Trigger safety guards (fire counts, cooldowns) provide second-layer protection against duplicates.

**Key files:**
- `packages/syn-domain/.../event_pipeline/pipeline.py` — Unified pipeline with dedup
- `packages/syn-domain/.../event_pipeline/dedup_keys.py` — Content-based dedup key extractors
- `packages/syn-domain/.../event_pipeline/check_run_synthesizer.py` — Synthesizes check_run events from Checks API
- `packages/syn-domain/.../event_pipeline/pending_sha_port.py` — PendingSHA domain port
- `apps/syn-api/src/syn_api/services/github_event_poller.py` — Events API poller
- `apps/syn-api/src/syn_api/services/check_run_poller.py` — Checks API poller (#602)
- `packages/syn-shared/src/syn_shared/settings/polling.py` — `SYN_POLLING_*` configuration

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

### Subscription Architecture

Production uses `CoordinatorSubscriptionService` with per-projection checkpoints ([ADR-055](docs/adrs/ADR-055-projection-checkpoint-coordinator-architecture.md)). Legacy `EventSubscriptionService` ([ADR-010](docs/adrs/ADR-010-event-subscription-architecture.md)) is deprecated. See `create_coordinator_service()` in `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py` for the 12-projection registry.

### Background Task Error Handling

FastAPI `BackgroundTasks` silently swallow exceptions and `Result` errors. Any `background_tasks.add_task()` closure MUST check `isinstance(result, Err)` and log explicitly. Reference pattern: `apps/syn-api/src/syn_api/routes/executions/commands.py:200-217`.

### Object Storage Bucket Initialization

MinIO buckets MUST be created eagerly at startup via `ensure_ready()`, not lazily on first upload. Downloads fail with `NoSuchBucket` before any upload happens. See `lifecycle.py:_init_artifact_storage()` and [ADR-012](docs/adrs/ADR-012-artifact-storage.md).

### Rules

- Aggregates MUST be the decision-makers — never let an engine/service decide "what's next"
- State MUST be derived from events — no mutable in-memory state (no `ExecutionContext` pattern)
- Observability MUST be separate from domain — telemetry never flows through aggregates
- Long-running processes MUST use Processor To-Do List — no imperative async loops

### References

- Martin Dilger, *Understanding Event Sourcing* — Ch. 37: Processor To-Do List pattern
- Event Modeling specification: https://eventmodeling.org/posts/what-is-event-modeling/
- To-Do List + Passage of Time patterns: https://event-driven.io/en/to_do_list_and_passage_of_time_patterns_combined/

## Project Board

Work is tracked on the org-level GitHub project board: [Syntropic137 — Launch & Roadmap](https://github.com/orgs/syntropic137/projects/1)

### Structure

- **Milestones** = which phase: `🚀 Open Source Launch` → `🟠 Post-Launch Polish` → `🔵 Scale & Vision`
- **Priority** = urgency within that phase: P0 (critical) → P1 (high) → P2 (medium) → P3 (low)

### For Agents

```bash
# List issues by milestone
gh issue list --repo syntropic137/syntropic137 --milestone "🚀 Open Source Launch"

# Add an issue to the board
gh project item-add 1 --owner syntropic137 --url <issue-url>

# Set priority (requires project item ID from item-add output)
gh project item-edit --project-id PVT_kwDOD5uLBM4BPw_5 --id <item-id> \
  --field-id PVTSSF_lADOD5uLBM4BPw_5zg_Yl2A \
  --single-select-option-id <priority-option-id>
```

**Priority option IDs:** P0=`ceb54537`, P1=`beeef7eb`, P2=`89d84138`, P3=`7e44e913`

### Repos on this board

- `syntropic137/syntropic137` — core platform
- `syntropic137/event-sourcing-platform` — ES foundation
- `syntropic137/syntropic137-claude-plugin` — Claude Code plugin (onboarding, commands, skills)
- `syntropic137/syntropic137-landing-page` — public landing page

### Rules

- Every issue must have a milestone and priority
- P0 = do first, P3 = do last (within each milestone)
- Launch milestone must be clear before open source release

## Branching & Release Process

The canonical release process lives in [docs/release-process.md](docs/release-process.md) — version bumping, workflow behavior, release steps, failure recovery, and docs deployment.

**Quick reference:**

- **`main`** — development trunk. All PRs target `main`.
- **`release`** — deployment branch. PRs from `main` only. Merge triggers the full release pipeline.
- **Beta releases** bypass `release`: `gh release create v0.20.0-beta.1 --prerelease --target main`
- **Version management:** `just bump-version 0.20.0` updates all 13 files. `just check-version` validates consistency.
- **Docs:** `release` → Vercel production, `main` → preview only.

Submodules (agentic-primitives, event-sourcing-platform) have independent versioning — never bumped by the release script.

## Security

- [Security Practices](docs/security-practices.md) — supply chain hardening, Docker runtime security, credential management
- [GitHub App Security Model](docs/deployment/github-app-security.md) — PEM handling, token lifecycle, network isolation, token injector architecture

## Tooling

- **uv** for Python package management (workspaces)
- **pnpm** for Node.js package management (all frontend apps — never npm or yarn)
- **just** for task running
- **Docker Compose** for local and selfhost deployment
- QA: `just qa` runs lint, format, typecheck, test, coverage, vsa-validate
