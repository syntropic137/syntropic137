# types

Result type, error enums, and shared Pydantic models.

## Result Type

All API functions return `Result[T, E]` — a discriminated union of `Ok[T]` and `Err[E]`.

```python
from syn_api import Ok, Err, Result
```

### Ok

```python
@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    value: T
```

### Err

```python
@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    error: E
    message: str | None = None
```

### Pattern Matching

```python
result = await syn_api.v1.workflows.get_workflow("wf-123")

match result:
    case Ok(detail):
        print(detail.name)
    case Err(error, message):
        print(f"{error}: {message}")
```

## Error Enums

### WorkflowError

| Value | Description |
|-------|-------------|
| `NOT_FOUND` | Workflow or execution not found |
| `ALREADY_EXISTS` | Workflow with same name exists |
| `INVALID_INPUT` | Invalid parameters |
| `EXECUTION_FAILED` | Execution encountered an error |
| `NOT_IMPLEMENTED` | Operation not yet implemented |

### SessionError

| Value | Description |
|-------|-------------|
| `NOT_FOUND` | Session not found |
| `ALREADY_COMPLETED` | Session already completed |
| `INVALID_INPUT` | Invalid parameters |
| `NOT_IMPLEMENTED` | Operation not yet implemented |

### ArtifactError

| Value | Description |
|-------|-------------|
| `NOT_FOUND` | Artifact not found |
| `INVALID_INPUT` | Invalid parameters |
| `STORAGE_ERROR` | Storage backend error |
| `NOT_IMPLEMENTED` | Operation not yet implemented |

### GitHubError

| Value | Description |
|-------|-------------|
| `NOT_FOUND` | Resource not found |
| `AUTH_REQUIRED` | Authentication required |
| `RATE_LIMITED` | GitHub API rate limited |
| `NOT_IMPLEMENTED` | Operation not yet implemented |

### ObservabilityError

| Value | Description |
|-------|-------------|
| `NOT_FOUND` | Resource not found |
| `QUERY_FAILED` | Query execution failed |
| `NOT_IMPLEMENTED` | Operation not yet implemented |

## Response Models

### WorkflowSummary

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Workflow template ID |
| `name` | `str` | Workflow name |
| `workflow_type` | `str` | Type (research, custom, etc.) |
| `classification` | `str` | Classification level |
| `phase_count` | `int` | Number of phases |
| `description` | `str \| None` | Description |
| `created_at` | `datetime \| None` | Creation timestamp |
| `runs_count` | `int` | Number of executions |

### WorkflowDetail

Extends WorkflowSummary with `phases: list[PhaseDefinitionResponse]`.

### ExecutionSummary

| Field | Type | Description |
|-------|------|-------------|
| `workflow_execution_id` | `str` | Execution ID |
| `workflow_id` | `str` | Workflow template ID |
| `workflow_name` | `str` | Workflow name |
| `status` | `str` | Execution status |
| `completed_phases` | `int` | Completed phase count |
| `total_phases` | `int` | Total phase count |
| `total_tokens` | `int` | Total tokens used |
| `total_cost_usd` | `Decimal` | Total cost |
| `error_message` | `str \| None` | Error if failed |

### ExecutionDetail

Extends ExecutionSummary with input/output token breakdowns, duration, and artifact IDs.

### SessionSummary

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Session ID |
| `workflow_id` | `str \| None` | Associated workflow |
| `execution_id` | `str \| None` | Associated execution |
| `status` | `str` | Session status |
| `agent_type` | `str` | Agent provider |
| `total_tokens` | `int` | Total tokens |
| `total_cost_usd` | `Decimal` | Total cost |

### ArtifactSummary

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Artifact ID |
| `workflow_id` | `str \| None` | Associated workflow |
| `artifact_type` | `str` | Artifact type |
| `title` | `str \| None` | Title |
| `size_bytes` | `int` | Content size |
