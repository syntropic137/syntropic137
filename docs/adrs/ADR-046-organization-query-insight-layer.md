# ADR-046: Organization Query & Insight Layer

## Status

Accepted

## Context

The organization bounded context (ISS-175, ADR not yet numbered) introduced CRUD aggregates for Organization, System, and Repo. These aggregates manage the structural hierarchy -- organizations own systems, systems group repos -- but provide no read-side analytics.

To understand health, cost, failures, and patterns across repos and systems, we need a query layer that:

- Correlates workflow executions with repositories (executions do not carry `repo_id`)
- Surfaces per-repo health metrics (success rate, trend, windowed cost/tokens)
- Detects recurring failure and cost patterns at the system level
- Provides a global overview across all organizations and systems

The existing projection infrastructure (`AutoDispatchProjection` + `ProjectionStore`) is proven in other contexts and supports PostgreSQL-backed persistence with checkpoint-based recovery.

## Decision

### 1. Correlation-Based Repo Association

Workflow templates are reusable and not repo-specific. Executions can touch zero, one, or many repos. Rather than adding `repo_id` to execution or session events (which would violate their domain semantics), we derive repo-execution mappings via a dedicated `RepoCorrelationProjection`. See [ADR-047](ADR-047-repo-execution-correlation-pattern.md) for the full pattern.

### 2. All Projections Use AutoDispatchProjection + ProjectionStore

New insight projections follow the same infrastructure pattern as existing projections:

- Extend `AutoDispatchProjection` with `on_<snake_case_event>` handler methods
- Persist read models via `ProjectionStore` (PostgreSQL-backed)
- Register event routing in `ProjectionManager.EVENT_HANDLERS`
- No in-memory singletons -- all state survives process restarts

### 3. Three Query Tiers

| Tier | Scope | Read Models | Key Fields |
|------|-------|-------------|------------|
| **Repo-level** | Single repository | `RepoHealth` | success_rate, trend, window_cost_usd, window_tokens, last_execution_at |
| **System-level** | System (group of repos) | `SystemPatterns` | failure_patterns (type, count, affected repos), cost_outliers (deviation factor) |
| **Global** | All organizations | `GlobalOverview` | total_systems, total_repos, unassigned_repos, active_executions, per-system entries |

Repo-level queries depend on `RepoCorrelationProjection` to identify which executions belong to a given repo. System-level queries aggregate repo-level data. Global queries aggregate system-level data.

### 4. Frozen Dataclass Read Models with Dict Serialization

All read models are `@dataclass(frozen=True)` with `to_dict()` and `from_dict()` methods:

- **Frozen** ensures immutability after construction -- read models are snapshots, not mutable state
- **`to_dict()`** serializes for `ProjectionStore` persistence (JSON-compatible dict)
- **`from_dict()`** deserializes from stored data with safe defaults
- `Decimal` fields (costs) are serialized as strings to preserve precision

Composite read models use nested serialization (e.g., `GlobalOverview.systems` contains `SystemOverviewEntry` instances, each with its own `to_dict`/`from_dict`).

### 5. Frozen Dataclass Query DTOs

Query parameters use `@dataclass(frozen=True)` with `__post_init__` validation where constraints exist (e.g., time window bounds). This keeps query interfaces strongly typed without introducing Pydantic at the domain layer.

## Consequences

### Positive

- Enables analytics dashboards without modifying existing event schemas
- All insight data is derived from existing events -- no new commands or aggregates needed
- Frozen dataclasses enforce read-model immutability at the type level
- Three-tier query structure maps cleanly to dashboard UI hierarchy (global > system > repo)
- Consistent with existing projection patterns -- no new infrastructure

### Negative

- Repo-level queries depend on `RepoCorrelationProjection` staying in sync; if correlation events are missed, repo metrics will be incomplete
- Additional projections increase event processing load (mitigated by `AutoDispatchProjection` efficiency)

### Neutral

- Read models live in `organization/domain/read_models/` alongside the aggregates they serve
- Projections live in `organization/slices/` per ADR-020 convention

## References

- [ADR-047: Repo-Execution Correlation Pattern](ADR-047-repo-execution-correlation-pattern.md)
- [ADR-020: Bounded Context and Aggregate Convention](../../lib/event-sourcing-platform/docs/adrs/ADR-020-bounded-context-aggregate-convention.md)
- Read models: `packages/syn-domain/src/syn_domain/contexts/organization/domain/read_models/`
- Projection manager: `packages/syn-adapters/src/syn_adapters/projections/manager.py`
