# Architecture Decision Records

## How to use

- Next available number: **ADR-063**
- Template: Status, Date, Context, Decision, Consequences (Nygard format)
- ADR-025 was never created (numbering gap)
- ADR-027 has two files: `ADR-027-sdk-wrapper-architecture.md` (superseded) and `ADR-027-unified-workflow-executor.md` (accepted)
- ADR-035 has two files: `ADR-035-conversation-storage-architecture.md` (proposed) and `ADR-035-qa-workflow-standard.md` (accepted)
- Event Sourcing Platform has separate ADRs: `lib/event-sourcing-platform/docs/adrs/`

## Index

### Event Sourcing & CQRS

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-003](ADR-003-event-sourcing-decorators.md) | Event Sourcing Decorator Patterns | Accepted |
| [ADR-007](ADR-007-event-store-integration.md) | Event Store Integration Architecture | Accepted |
| [ADR-008](ADR-008-vsa-projection-architecture.md) | VSA Projection Architecture for CQRS Read Side | Accepted |
| [ADR-010](ADR-010-event-subscription-architecture.md) | Event Subscription Architecture for Projections | Accepted (partially superseded by ADR-055) |
| [ADR-018](ADR-018-commands-vs-observations-event-architecture.md) | Commands vs Observations in Event-Driven Architecture | Accepted |
| [ADR-020](ADR-020-event-sourcing-projection-consistency.md) | Event Sourcing Projection Consistency | Accepted |
| [ADR-032](ADR-032-domain-event-type-safety.md) | Domain Event Type Safety | Accepted |
| [ADR-042](ADR-042-event-type-naming-standard.md) | Event Type Naming Standard | Accepted |
| [ADR-051](ADR-051-soft-delete-archive-pattern.md) | Soft-Delete (Archive) Pattern for Domain Aggregates | Accepted |
| [ADR-055](ADR-055-projection-checkpoint-coordinator-architecture.md) | Projection Checkpoint Coordinator Architecture | Accepted |

### Orchestration & Execution

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-009](ADR-009-agentic-execution-architecture.md) | Agentic Execution Architecture | Accepted |
| [ADR-014](ADR-014-workflow-execution-model.md) | Workflow Execution Model | Accepted |
| [ADR-019](ADR-019-websocket-control-plane.md) | WebSocket Control Plane Architecture | Accepted |
| [ADR-023](ADR-023-workspace-first-execution-model.md) | Workspace-First Execution Model | Accepted |
| [ADR-027](ADR-027-unified-workflow-executor.md) | Unified Workflow Executor Architecture | Accepted |
| [ADR-036](ADR-036-workspace-structure-convention.md) | Workspace Structure Convention | Accepted |
| [ADR-048](ADR-048-workflows-as-cc-commands.md) | Workflows as Claude Code Commands | Accepted |
| [ADR-049](ADR-049-sse-over-websocket-for-execution-streams.md) | Server-Sent Events (SSE) for Real-Time Execution Streams | Accepted |

### Infrastructure & Storage

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-monorepo-architecture.md) | Monorepo Architecture with VSA | Accepted (Revised) |
| [ADR-002](ADR-002-uv-monorepo-architecture.md) | uv Monorepo Architecture | Accepted |
| [ADR-004](ADR-004-environment-configuration.md) | Environment Configuration with Pydantic Settings | Accepted |
| [ADR-005](ADR-005-development-environments.md) | Development Environment Strategy | Accepted |
| [ADR-011](ADR-011-structured-logging.md) | Structured Logging with agentic-logging | Accepted |
| [ADR-012](ADR-012-artifact-storage.md) | Artifact Storage Architecture | Accepted |
| [ADR-026](ADR-026-timescaledb-observability-storage.md) | TimescaleDB for Observability Event Storage | Accepted |
| [ADR-028](ADR-028-otel-integration.md) | OpenTelemetry Integration for Agent Observability | Superseded |
| [ADR-030](ADR-030-database-consolidation.md) | Database Consolidation to Single TimescaleDB Instance | Accepted |
| [ADR-031](ADR-031-sql-schema-validation.md) | SQL Schema Validation for Raw SQL Operations | Accepted |
| [ADR-045](ADR-045-secrets-management-standard.md) | Secrets Management Standard | Accepted |
| [ADR-052](ADR-052-docs-site-vercel-deployment.md) | Documentation Site Deployment via Vercel | Superseded |
| [ADR-054](ADR-054-generated-docs-sync-pipeline.md) | Generated Documentation Sync Pipeline | Accepted |

### Testing & Quality

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-013](ADR-013-integration-testing-strategy.md) | Integration Testing Strategy with Event Store | Accepted |
| [ADR-029](ADR-029-ai-agent-testing-verification.md) | AI Agent Testing & Verification Philosophy | Accepted |
| [ADR-033](ADR-033-recording-based-integration-testing.md) | Recording-Based Integration Testing | Accepted |
| [ADR-034](ADR-034-test-infrastructure-architecture.md) | Test Infrastructure Architecture | Accepted |
| [ADR-035](ADR-035-qa-workflow-standard.md) | QA Workflow Standard | Accepted |
| [ADR-038](ADR-038-test-organization-standard.md) | Test Organization Standard | Accepted |
| [ADR-062](ADR-062-architectural-fitness-function-standard.md) | Architectural Fitness Function Standard | Accepted |

### GitHub Integration

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-040](ADR-040-github-trigger-architecture.md) | GitHub Trigger Architecture | Proposed |
| [ADR-041](ADR-041-offline-dev-and-webhook-recording.md) | Offline Development Mode and Webhook Recording | Accepted |
| [ADR-043](ADR-043-git-hook-event-pipeline.md) | Git Hook Event Pipeline | Accepted |
| [ADR-050](ADR-050-hybrid-webhook-polling-event-pipeline.md) | Hybrid Webhook + Polling Event Pipeline | Accepted |
| [ADR-060](ADR-060-restart-safe-trigger-deduplication.md) | Restart-Safe Trigger Deduplication | Accepted |

### UI & Communication

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-016](ADR-016-ui-feedback-module.md) | UI Feedback Module | Proposed |
| [ADR-044](ADR-044-cli-first-agent-native-interface.md) | CLI-First, Agent-Native Interface Design | Accepted |
| [ADR-053](ADR-053-plugin-schema-generation-strategy.md) | Plugin Schema Generation Strategy | Accepted |

### Agent Architecture

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-006](ADR-006-hook-architecture-agent-swarms.md) | Hook Architecture for Agent Swarms | Accepted |
| [ADR-015](ADR-015-agent-observability.md) | Agent Session Observability Architecture | Accepted |
| [ADR-017](ADR-017-scalable-event-collection-architecture.md) | Scalable Event Collection Architecture | Accepted |
| [ADR-021](ADR-021-isolated-workspace-architecture.md) | Isolated Workspace Architecture | Accepted |
| [ADR-022](ADR-022-secure-token-architecture.md) | Secure Token Architecture for Agentic Scale | On Hold |
| [ADR-024](ADR-024-setup-phase-secrets.md) | Setup Phase Secrets Pattern | Accepted |
| [ADR-027](ADR-027-sdk-wrapper-architecture.md) | SDK Wrapper Architecture via agentic-primitives | Superseded |
| [ADR-035](ADR-035-conversation-storage-architecture.md) | Agent Output Data Model and Storage | Proposed |
| [ADR-037](ADR-037-subagent-observability.md) | Subagent Observability | Accepted |
| [ADR-039](ADR-039-context-window-cost-tracking.md) | Context Window and Cost Tracking | Accepted |

### Organization & Repos

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-046](ADR-046-organization-query-insight-layer.md) | Organization Query & Insight Layer | Accepted |
| [ADR-047](ADR-047-repo-execution-correlation-pattern.md) | Repo-Execution Correlation Pattern | Accepted |
