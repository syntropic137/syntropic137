# ADR-047: Repo-Execution Correlation Pattern

## Status

Accepted

## Context

Workflow templates in Syntropic137 are reusable -- they are not tied to a specific repository. A single execution can touch zero, one, or many repos. Agent sessions can operate on multiple repos within one execution. Adding `repo_id` as a field on `WorkflowExecutionStarted` or `SessionStarted` events would:

1. Impose a false 1:1 relationship (executions are many-to-many with repos)
2. Couple execution semantics to repository semantics across bounded contexts
3. Require event schema migration for all existing events

We need a way to associate repos with executions for the insight layer (ADR-046) without modifying event schemas.

## Decision

### Correlation Projection

`RepoCorrelationProjection` observes two existing event types and builds a many-to-many mapping between repos and executions:

| Event | Source | Correlation Fields |
|-------|--------|--------------------|
| `github.TriggerFired` | GitHub context | `repository` (full name), `execution_id`, `workflow_id` |
| `WorkflowExecutionStarted` | Orchestration context | `inputs.repository_url` or `inputs.repository`, `execution_id`, `workflow_id` |

The projection extracts `owner/repo` from various URL formats (HTTPS, SSH, plain `owner/repo`) and stores correlation records keyed by `{execution_id}:{repo_full_name}`.

### Deduplication

When both `TriggerFired` and `WorkflowExecutionStarted` correlate the same execution-repo pair, the projection keeps only the first record (from `TriggerFired`, with `correlation_source="trigger"`). The `WorkflowExecutionStarted` handler checks for an existing key before writing.

### Correlation Sources

Each record tracks how the correlation was established:

| Source | Meaning |
|--------|---------|
| `trigger` | Derived from `TriggerFired` event (GitHub webhook triggered the execution) |
| `template` | Derived from `WorkflowExecutionStarted` template inputs (repository_url field) |

### Infrastructure

- Extends `AutoDispatchProjection` -- handler methods are `on_trigger_fired` and `on_workflow_execution_started`
- Persists via `ProjectionStore` (PostgreSQL-backed)
- Registered in `ProjectionManager.EVENT_HANDLERS` for `"github.TriggerFired"` and `"WorkflowExecutionStarted"`
- Snapshots position every 100 events for fast recovery

### Read Model

`RepoExecutionCorrelation` is a `@dataclass(frozen=True)` with fields:

- `repo_full_name` -- e.g. `"owner/repo"`
- `repo_id` -- linked `RepoAggregate` ID if registered, else `None`
- `execution_id` -- workflow execution ID
- `workflow_id` -- workflow template ID
- `correlation_source` -- `"trigger"` or `"template"`
- `correlated_at` -- ISO timestamp

### Bidirectional Queries

The projection provides two query methods:

- `get_repos_for_execution(execution_id)` -- all repos touched by an execution
- `get_executions_for_repo(repo_full_name)` -- all executions that touched a repo

These are the foundation for all repo-level insight queries in ADR-046.

## Consequences

### Positive

- Zero event schema changes -- correlation is entirely derived from existing events
- Many-to-many relationship is modeled correctly (not forced into 1:1)
- Multi-repo executions are first-class citizens
- Bidirectional queries support both "what repos did this execution touch?" and "what executions ran against this repo?"
- Deduplication prevents double-counting when both event sources fire

### Negative

- Executions that are not triggered by GitHub and do not include a `repository_url` in template inputs will have no repo correlation (acceptable -- these are repo-agnostic by definition)
- Query methods currently scan all records; indexing by execution_id and repo_full_name is a future optimization -- TODO(#176)

### Neutral

- The projection lives in `organization/slices/repo_correlation/` per ADR-020 convention
- `_extract_repo_name()` handles HTTPS URLs, SSH URLs, and plain `owner/repo` format

## References

- [ADR-046: Organization Query & Insight Layer](ADR-046-organization-query-insight-layer.md)
- Projection: `packages/syn-domain/src/syn_domain/contexts/organization/slices/repo_correlation/projection.py`
- Read model: `packages/syn-domain/src/syn_domain/contexts/organization/domain/read_models/repo_execution_correlation.py`
- Event routing: `packages/syn-adapters/src/syn_adapters/projections/manager.py` (EVENT_HANDLERS)
