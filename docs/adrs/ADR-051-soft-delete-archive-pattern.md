# ADR-051: Soft-Delete (Archive) Pattern for Domain Aggregates

## Status

**Accepted** — 2026-03-30

## Context

Users need the ability to remove workflow templates (and eventually other aggregates) from active use. In an event-sourced system, hard deletion is problematic:

1. **Event history becomes inconsistent** — historical executions reference deleted templates, creating dangling references.
2. **Audit trail is lost** — no record that the resource ever existed.
3. **Recovery is impossible** — accidental deletion requires manual event store surgery.

The organization context already uses hard-delete (`OrganizationDeleted`, `SystemDeleted`) because those aggregates have no long-lived dependents. Workflow templates, however, are referenced by workflow executions that may span days and are preserved for historical analysis.

## Decision

Use **soft-delete via an `Archived` domain event** for aggregates that have long-lived dependents or historical significance.

### Pattern

1. **Command:** `Archive<Aggregate>Command` with `aggregate_id` and optional `archived_by`.
2. **Event:** `<Aggregate>ArchivedEvent` — immutable, recorded in the event store.
3. **Aggregate state:** `is_archived: bool` property, set by the event sourcing handler.
4. **Guard:** Aggregate rejects `Archive` command if already archived (`ValueError`).
5. **Cross-aggregate guard:** The handler (not the aggregate) checks for blocking conditions from other aggregates (e.g., active executions). This keeps the aggregate boundary clean — it only knows about its own state.
6. **Listing:** Queries exclude archived by default. An `include_archived` parameter opts in.
7. **Detail view:** `GET /<resource>/{id}` always returns archived resources with an `is_archived` field — dependents need to resolve references.

### When to use soft-delete vs hard-delete

| Criteria | Soft-delete (archive) | Hard-delete |
|----------|----------------------|-------------|
| Has long-lived dependents? | Yes (e.g., executions reference templates) | No |
| Historical significance? | Yes (audit, analytics) | No |
| Recovery expectation? | Users may want to unarchive | Deletion is intentional and final |

### API conventions

- **Endpoint:** `DELETE /<resource>/{id}` — returns `200` with `{"id": ..., "status": "archived"}`.
- **404:** Resource not found.
- **409:** Conflict — active dependents exist, or already archived.
- **CLI:** `syn <resource> delete <id>` with `--force` to skip confirmation. Help text clarifies this is a soft-delete.

## Consequences

- **Positive:** Full audit trail preserved. Accidental archival is recoverable (future `unarchive` command). Historical queries remain consistent.
- **Positive:** Cross-aggregate guards live in handlers, keeping aggregate boundaries clean.
- **Negative:** Queries must filter archived resources — slight complexity increase in projections.
- **Negative:** Storage grows monotonically (archived resources never purged). Acceptable at current scale; revisit if storage becomes a concern.

## References

- Issue #404: Add DELETE endpoint for workflow templates
- Organization context: uses hard-delete (`OrganizationDeleted`) — no long-lived dependents
- ADR-020: Bounded context and aggregate conventions
