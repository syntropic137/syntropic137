# Architecture Decision Records

This directory contains all ADRs for the Syntropic137 project. ADRs capture significant architectural decisions with context, rationale, and consequences.

## How to Use This Index

- Browse by category to find relevant decisions
- Each ADR links to the full document with detailed context
- For event-sourcing-platform ADRs, see `lib/event-sourcing-platform/docs/adrs/`

## Notes

- **ADR-025** was never created (numbering gap)
- **ADR-027** has two variant files: `ADR-027-sdk-wrapper-architecture.md` (superseded) and `ADR-027-unified-workflow-executor.md` (accepted)
- **ADR-035** has two variant files: `ADR-035-conversation-storage-architecture.md` (proposed) and `ADR-035-qa-workflow-standard.md` (accepted)
- Next available number: **ADR-056**

---

## Architecture & Standards

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-001](ADR-001-monorepo-architecture.md) | Monorepo Architecture with VSA | `apps/` + `packages/` flat monorepo structure with git submodules and DDD |
| [ADR-002](ADR-002-uv-monorepo-architecture.md) | uv Monorepo Architecture | Python workspace conventions using `uv` with `uv_build` backend |
| [ADR-004](ADR-004-environment-configuration.md) | Environment Configuration with Pydantic Settings | All config via `pydantic-settings` with startup validation and secret protection |
| [ADR-020](ADR-020-event-sourcing-projection-consistency.md) | Bounded Context and Aggregate Conventions | VSA folder conventions, aggregate naming rules, and projection placement |
| [ADR-042](ADR-042-event-type-naming-standard.md) | Event Type Naming Standard | Python identifier names must match their string values exactly |

---

## Event Sourcing & CQRS

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-003](ADR-003-event-sourcing-decorators.md) | Event Sourcing Decorator Patterns | Standard use of `@aggregate`, `@command`, `@event` decorators from the ESP SDK |
| [ADR-007](ADR-007-event-store-integration.md) | Event Store Integration Architecture | Use ESP's gRPC event store server rather than direct PostgreSQL queries |
| [ADR-008](ADR-008-vsa-projection-architecture.md) | VSA Projection Architecture for CQRS Read Side | CQRS read-side using VSA-compliant query slices instead of a monolithic read model |
| [ADR-010](ADR-010-event-subscription-architecture.md) | Event Subscription Architecture for Projections | Subscription mechanism connecting the event store to projections |
| [ADR-018](ADR-018-commands-vs-observations-event-architecture.md) | Commands vs Observations in Event-Driven Architecture | Separates domain events (command outcomes) from observability events (external facts) |
| [ADR-032](ADR-032-domain-event-type-safety.md) | Domain Event Type Safety | Pydantic models with `frozen=True` and `extra="forbid"` for all domain events |
| [ADR-051](ADR-051-soft-delete-archive-pattern.md) | Soft-Delete (Archive) Pattern for Domain Aggregates | Archive aggregates via domain events instead of hard deletion |
| [ADR-055](ADR-055-projection-checkpoint-coordinator-architecture.md) | Projection Checkpoint & Coordinator Architecture | Per-projection checkpoints replacing legacy global-checkpoint subscription service |

---

## Orchestration & Execution

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-009](ADR-009-agentic-execution-architecture.md) | Agentic Execution Architecture | Defines the agentic protocol and workspace concept (execution model superseded by ADR-023) |
| [ADR-014](ADR-014-workflow-execution-model.md) | Workflow Execution Model | Separates Workflow Templates from Workflow Executions for correct metrics and history |
| [ADR-019](ADR-019-websocket-control-plane.md) | WebSocket Control Plane Architecture | HTTP POST endpoints as canonical control plane for pause/resume/cancel/inject |
| [ADR-023](ADR-023-workspace-first-execution-model.md) | Workspace-First Execution Model | Enforces that `WorkflowExecutionEngine` always runs via `WorkspaceRouter` |
| [ADR-027](ADR-027-unified-workflow-executor.md) | Unified Workflow Executor Architecture | Single executor implementation for both CLI and Dashboard with consistent observability |
| [ADR-036](ADR-036-workspace-structure-convention.md) | Workspace Structure Convention | Standardized directory layout inside agent containers for reliable artifact passing |
| [ADR-048](ADR-048-workflows-as-cc-commands.md) | Workflows as Claude Code Commands | Workflow phases use Claude Code command Markdown files with `$ARGUMENTS` substitution |

---

## Infrastructure & Storage

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-005](ADR-005-development-environments.md) | Development Environment Strategy | Three-tier strategy (unit / local Docker / CI) with no SQLite shortcuts |
| [ADR-012](ADR-012-artifact-storage.md) | Artifact Storage Architecture | Artifact metadata in PostgreSQL projections, content in MinIO object storage |
| [ADR-026](ADR-026-timescaledb-observability-storage.md) | TimescaleDB for Observability Event Storage | Observability events stored in TimescaleDB hypertables, separate from domain event store |
| [ADR-030](ADR-030-database-consolidation.md) | Database Consolidation to Single TimescaleDB Instance | Merges two PostgreSQL instances into one TimescaleDB for both domain and observability data |
| [ADR-031](ADR-031-sql-schema-validation.md) | SQL Schema Validation for Raw SQL Operations | Compile-time schema validation for raw `asyncpg` queries to prevent column drift |
| [ADR-045](ADR-045-secrets-management-standard.md) | Secrets Management Standard | Canonical secret naming convention with 1Password `op://` resolver |
| [ADR-049](ADR-049-sse-over-websocket-for-execution-streams.md) | SSE over WebSocket for Real-Time Execution Streams | Server-Sent Events replace WebSocket for unidirectional server→client event streaming |
| [ADR-052](ADR-052-docs-site-vercel-deployment.md) | Documentation Site Deployment via Vercel | Public docs site (`apps/syn-docs/`) deployed via Vercel git integration |

---

## Testing & Quality

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-013](ADR-013-integration-testing-strategy.md) | Integration Testing Strategy with Event Store | Integration tests run against a real event store to catch serialization bugs |
| [ADR-029](ADR-029-ai-agent-testing-verification.md) | AI Agent Testing & Verification Philosophy | Tests must verify real observable behavior, not mock-passing stubs |
| [ADR-033](ADR-033-recording-based-integration-testing.md) | Recording-Based Integration Testing | Record real agent JSONL streams and replay them in tests to avoid API token spend |
| [ADR-034](ADR-034-test-infrastructure-architecture.md) | Test Infrastructure Architecture | Ephemeral test stack on ports +10000 enables parallel dev and integration test runs |
| [ADR-035](ADR-035-qa-workflow-standard.md) | QA Workflow Standard | Two-tier parallel QA suite targeting sub-1-minute full validation |
| [ADR-038](ADR-038-test-organization-standard.md) | Test Organization Standard | Co-locate unit tests with slices; keep integration tests in a top-level `tests/` directory |
| [ADR-041](ADR-041-offline-dev-and-webhook-recording.md) | Offline Development Mode and Webhook Recording | Record and replay webhook payloads for GitHub trigger testing without a live tunnel |

---

## GitHub Integration

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-040](ADR-040-github-trigger-architecture.md) | GitHub Trigger Architecture | First-class trigger resources for auto-firing workflows from GitHub CI and review events |
| [ADR-043](ADR-043-git-hook-event-pipeline.md) | Git Hook Event Pipeline | Record real git operations via tool result scanning rather than command inference |
| [ADR-050](ADR-050-hybrid-webhook-polling-event-pipeline.md) | Hybrid Webhook + Polling Event Pipeline | Unified pipeline accepts both webhook deliveries and Events API polling with dedup |

---

## UI & Communication

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-011](ADR-011-structured-logging.md) | Structured Logging with agentic-logging | JSON structured logging across all components for agent-parseable debug output |
| [ADR-016](ADR-016-ui-feedback-module.md) | UI Feedback Module | In-context feedback capture widget stored in PostgreSQL, queryable by agents |
| [ADR-044](ADR-044-cli-first-agent-native-interface.md) | CLI-First, Agent-Native Interface Design | CLI is the canonical interface; API serves it, dashboard is a consumer like any other |
| [ADR-053](ADR-053-plugin-schema-generation-strategy.md) | Plugin Schema Generation Strategy | Generate JSON Schema from Pydantic models for all plugin file formats |
| [ADR-054](ADR-054-generated-docs-sync-pipeline.md) | Generated Documentation Sync Pipeline | Node.js CLI drives docs generation; CI drift detection prevents stale reference docs |

---

## Agent Architecture

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-006](ADR-006-hook-architecture-agent-swarms.md) | Hook Architecture for Agent Swarms | Async hook client library replacing subprocess hooks for 1000+ concurrent agents |
| [ADR-021](ADR-021-isolated-workspace-architecture.md) | Isolated Workspace Architecture | Docker/Firecracker/gVisor isolation for agent containers with hook event transport |
| [ADR-022](ADR-022-secure-token-architecture.md) | Secure Token Architecture for Agentic Scale | Shared Envoy cluster for token vending (on hold pending auth/multi-tenant work) |
| [ADR-024](ADR-024-setup-phase-secrets.md) | Setup Phase Secrets Pattern | Inject secrets during a pre-execution setup phase and clear them before agent starts |
| [ADR-037](ADR-037-subagent-observability.md) | Subagent Observability | Track parent-child agent hierarchies with per-subagent tool attribution and cost |
| [ADR-048](ADR-048-workflows-as-cc-commands.md) | Workflows as Claude Code Commands | (see also Orchestration) Phases use Claude Code command Markdown with `$ARGUMENTS` |

---

## Organization & Observability

| ADR | Title | Summary |
|-----|-------|---------|
| [ADR-015](ADR-015-agent-observability.md) | Agent Session Observability Architecture | Tool call timeline and token tracking per session via JSONL hook parsing |
| [ADR-017](ADR-017-scalable-event-collection-architecture.md) | Scalable Event Collection Architecture | `syn-collector` service ingests hook events and writes to TimescaleDB |
| [ADR-028](ADR-028-otel-integration.md) | OpenTelemetry Integration *(superseded by ADR-029)* | OTel proposed as observability transport, replaced by direct JSONL parsing |
| [ADR-039](ADR-039-context-window-cost-tracking.md) | Context Window and Cost Tracking | Use the final `result` event `total_cost_usd` as authoritative; per-turn usage for streaming |
| [ADR-046](ADR-046-organization-query-insight-layer.md) | Organization Query & Insight Layer | Read-side analytics projection for per-repo health, cost rollup, and failure patterns |
| [ADR-047](ADR-047-repo-execution-correlation-pattern.md) | Repo-Execution Correlation Pattern | Correlation projection links executions to repos without coupling event schemas |
