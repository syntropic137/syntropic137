---
description:
globs:
alwaysApply: true
---
<!--
CANONICAL FILE. Edit this one. CLAUDE.md is a byte-identical copy: run
`just sync-agent-docs` after editing; `just preflight` fails if they differ.
Why a copy (not a symlink or @import stub): see the comment on
`sync-agent-docs` in the justfile.
This file loads on EVERY turn of every agent. Keep it to rules every coding
task needs; put task-specific detail in a linked doc or skill.
-->

# Syntropic137

Orchestrates AI agent execution in isolated Docker workspaces and captures every event for observability: **orchestration** (workspace lifecycle, secure tokens, GitHub App) and **observability** (tool use, tokens, costs, errors, streamed to a dashboard). End goal: a `gh`-style CLI (`syn`).

- **North star:** 20 concurrent executions now, 100 ASAP, 1,000 for production. Judge every design against [docs/north-star.md](docs/north-star.md).
- **Purpose:** scale quality development - reach the quality bar first, then make it cheaper and faster. Orchestrating or dogfooding the platform: read [.claude/skills/orchestrating/SKILL.md](.claude/skills/orchestrating/SKILL.md).
- **Architecture:** DDD + event sourcing (all state changes are events), Vertical Slice Architecture (validated by `vsa`), thin FastAPI wrapper, `syn` CLI wraps the API.

## Repository Structure

```
apps/syn-api/           FastAPI server (routes + v1 application services)
apps/syn-cli-node/      `syn` CLI (Node.js, HTTP client for syn-api)
apps/syn-dashboard-ui/  Dashboard (Vite + React)
apps/syn-docs/          PUBLIC docs site (Next.js + Fumadocs); content in apps/syn-docs/content/
packages/syn-domain/    Domain events, aggregates, ports
packages/syn-adapters/  Orchestration + observability adapters
packages/syn-collector/ Event ingestion API
packages/syn-shared/    Shared settings, configuration
lib/agentic-workspace/  submodule: workspace images, isolation, harness adapters
lib/event-sourcing-platform/ submodule: Rust event store, Python SDK, VSA, projections
infra/                  Docker Compose, setup wizard, secrets
docs/, docs/adrs/       INTERNAL contributor docs and ADRs (not the public site)
```

### Submodules (`lib/`)

Both are ours (dogfooded). If something needs fixing, push the fix to the submodule repo; don't work around it. agentic-primitives is gone; nothing depends on it.

> **If it changes when Anthropic or OpenAI ships a new CLI version, it belongs
> in agentic-workspace. If it changes when we decide what a cost, a session or
> an execution IS, it belongs here.**

Depend on a port (Protocol here), not on a format; never reimplement a harness detail here. A submodule change reaches workspaces only after merge -> image build -> `release` channel -> `PINNED_DIGESTS` bump (`main` publishes unreviewed `:edge` only). Full boundary table and delivery plan: [docs/architecture/agentic-workspace-boundary.md](docs/architecture/agentic-workspace-boundary.md).

## Non-Negotiable Rules

### Type Safety (ADR-001 s6, ADR-032)

Treat Python like TypeScript.

- **pyright** - all code must pass (`standard`, ratcheting to `strict`)
- **No `Any`** without explicit justification
- **No `dict` for structured state** - use `@dataclass` or Pydantic `BaseModel`. A `TypedDict` or `SimpleNamespace` is NOT a fix; `NamedTuple` is fine
- **No string-keyed lookups** when attribute access is possible
- **Pydantic** for API boundaries, configs, domain events (`frozen=True`, `extra="forbid"`)
- **All public interfaces fully typed**
- **API routes MUST return Pydantic response models**, never `dict[str, Any]` (untyped routes break the OpenAPI -> CLI type pipeline)

The typing ratchets (`untyped-dicts`, pyright) are fitness functions, not lint: never weaken them, never game them with renames or aliases. Budgets only decrease. Rationale, what the AST gate counts, and its history: [docs/architecture/type-safety-fitness.md](docs/architecture/type-safety-fitness.md). New whole-codebase static check -> `ci/fitness/` + `fitness-exceptions.toml`; behavioural assertion -> a test beside the code.

### API -> CLI Types

Pydantic model in `apps/syn-api/src/syn_api/types.py` -> route return type -> `just codegen` -> typed client (`api.GET`/`api.POST`) in the CLI. Never hand-edit `apps/syn-cli-node/src/generated/api-types.ts`. CLI field names MUST match API model field names. Details: [docs/architecture/api-cli-type-pipeline.md](docs/architecture/api-cli-type-pipeline.md).

### Bounded Contexts & Aggregates (ADR-020)

Aggregates live in `domain/aggregate_<name>/` with specific file names (`WorkspaceAggregate.py`, not `aggregate.py`). Projections go in the owning context's `slices/`, never a top-level context. A context MUST have `aggregate_*/` folders. Refs: [ADR-020](lib/event-sourcing-platform/docs/adrs/ADR-020-bounded-context-aggregate-convention.md), [VSA Quick Reference](lib/event-sourcing-platform/vsa/docs/QUICK-REFERENCE.md).

| Context | Aggregates | Purpose |
|---------|------------|---------|
| `orchestration` | Workspace, Workflow, WorkflowExecution | Workflow execution, workspace management |
| `agent_sessions` | AgentSession | Agent sessions and observability |
| `github` | Installation, TriggerRule | GitHub App, triggers, hybrid event pipeline ([ADR-050](docs/adrs/ADR-050-hybrid-webhook-polling-event-pipeline.md)) |
| `artifacts` | Artifact | Artifact storage |
| `organization` | Organization, System, Repo | Org hierarchy, systems/repos, insights |

### Ubiquitous Language

Every bounded context owns `docs/architecture/<bounded-context>-ubiquitous-language.md` (segment = directory name under `packages/syn-domain/src/syn_domain/contexts/`; a fitness test enforces it). A term in the code MUST appear in its context's file; rejected/reserved words get their own section (`fork` is reserved in `orchestration`). Full rules: [docs/architecture/ubiquitous-language-convention.md](docs/architecture/ubiquitous-language-convention.md).

### Event Sourcing (summary; read [docs/architecture/event-sourcing-rules.md](docs/architecture/event-sourcing-rules.md) before touching aggregates, projections, processors or handlers)

- **Aggregates decide.** State derives from events; no engine/service decides "what's next"; no mutable in-memory execution state.
- **Two lanes:** domain events (event store) vs telemetry (observability recorder). Telemetry never flows through aggregates.
- **Long-running processes use Processor To-Do List**, never imperative async loops. Handlers MUST be idempotent.
- **Consumers:** a `CheckpointedProjection` never has side effects; anything that dispatches commands or calls APIs is a `ProcessManager` (`process_pending()` runs live only).
- **In-memory adapters** inherit `InMemoryAdapter` and refuse to construct outside test/offline ([ADR-060](docs/adrs/ADR-060-restart-safe-trigger-deduplication.md)). Production wiring fails fast; never fall back to in-memory.
- **Background tasks:** any `background_tasks.add_task()` closure MUST check `isinstance(result, Err)` and log.
- If you need it after a restart, it must be an event.

### TODO/FIXME and scratch docs

- Every TODO/FIXME references an issue: `# TODO(#55): ...`. Never a bare `# TODO:`.
- Root-level `.md` files other than `README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md` are scratch; never commit them. Permanent docs go in `docs/` or `docs/adrs/`.

## Testing

Goal: manual testing finds zero bugs. **Unit** (fast, no infra), **Integration** (recording playback or test stack on ports +10000), **E2E** (real API calls, few). Fixtures auto-detect infra: env vars > test-stack (port 15432) > testcontainers. Test doubles in production code must refuse to construct outside test/offline ([ADR-060 s5](docs/adrs/ADR-060-restart-safe-trigger-deduplication.md#5-inmemoryadapter-base-class-production-guard)).

## Tooling and Configuration

- **uv** for Python, **pnpm** for Node (never npm/yarn), **just** for tasks, Docker Compose for local/selfhost.
- Env vars live in Pydantic Settings classes (auto-generated into `.env.example`); read ADR-004 first. Never hardcode ports/URLs: use `syn_shared.settings.constants` / `constants.ts`.

## Before Opening a PR (mandatory)

- `just qa-ci` - every PR-gating CI job runnable locally (~3m30s). Run before pushing.
- `just preflight` - static half only (~1m); what the pre-push hook runs. Not a CI guarantee.
- `just preflight-agent` - inside an agent workspace container only.
- Add a PR-gating CI job -> map it in `scripts/check_ci_parity.py`. Add a static gate -> `preflight`, never CI alone.

What each covers and what can never run locally: [docs/development/pre-pr-checklist.md](docs/development/pre-pr-checklist.md).

## Branching, Release, Board, Security

- All PRs target `main`. `release` takes PRs from `main` only; merging it publishes. Before any release or publish work read [docs/release-process.md](docs/release-process.md) (betas create NO GitHub release; `just bump-version X.Y.Z`). Submodules version independently.
- Every issue needs a milestone and priority on the [project board](https://github.com/orgs/syntropic137/projects/1); `gh` commands and field IDs: [.claude/skills/devops/project_board.md](.claude/skills/devops/project_board.md).
- Security: [docs/security-practices.md](docs/security-practices.md), [docs/deployment/github-app-security.md](docs/deployment/github-app-security.md).
