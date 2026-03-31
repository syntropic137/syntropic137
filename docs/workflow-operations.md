# Workflow Template Operations

Reference for all workflow template CRUD operations, covering the API, CLI, and domain behavior.

## Operations

### Create

Create a new workflow template with phases.

| | Detail |
|---|---|
| **API** | `POST /workflows` |
| **CLI** | `syn workflow create --type <type> --repo <owner/repo>` |
| **Domain** | `CreateWorkflowTemplateCommand` → `WorkflowTemplateCreatedEvent` |

### List

List workflow templates with optional filtering.

| | Detail |
|---|---|
| **API** | `GET /workflows?workflow_type=<type>&include_archived=true&limit=20&offset=0` |
| **CLI** | `syn workflow list [--include-archived]` |
| **Default** | Excludes archived templates |

### Get

Retrieve a single workflow template by ID. Always returns archived templates (with `is_archived` field).

| | Detail |
|---|---|
| **API** | `GET /workflows/{workflow_id}` |
| **CLI** | `syn workflow show <id>` |

### Delete (Archive)

Soft-delete a workflow template. See [ADR-051](adrs/ADR-051-soft-delete-archive-pattern.md).

| | Detail |
|---|---|
| **API** | `DELETE /workflows/{workflow_id}` |
| **CLI** | `syn workflow delete <id> [--force]` |
| **Domain** | `ArchiveWorkflowTemplateCommand` → `WorkflowTemplateArchivedEvent` |
| **Guard** | Rejects if workflow has active executions (running, paused, not_started) |
| **Idempotency** | Archiving an already-archived template returns `409 Conflict` |

**Response codes:**

| Code | Meaning |
|------|---------|
| 200 | Successfully archived |
| 404 | Workflow template not found |
| 409 | Has active executions, or already archived |

### Validate

Validate a workflow YAML definition file.

| | Detail |
|---|---|
| **API** | `POST /workflows/validate` |
| **CLI** | `syn workflow validate <path>` |

## Archive Filtering

Archived templates are excluded from listing by default across all layers:

- **Projection:** `WorkflowListProjection.query(include_archived=False)` filters at the read-model level.
- **API:** `GET /workflows?include_archived=true` passes through to the projection.
- **CLI:** `syn workflow list --include-archived` passes the query parameter.
- **Detail view:** `GET /workflows/{id}` always returns the template regardless of archive status, with `is_archived: bool` in the response.

## Cross-Aggregate Guard

The archive operation checks for active executions before proceeding. This guard lives in `ArchiveWorkflowTemplateHandler` (the application service), not in the `WorkflowTemplateAggregate`, because executions are a separate aggregate. The handler queries the `WorkflowExecutionListProjection` for executions with active statuses (`running`, `paused`, `not_started`).
