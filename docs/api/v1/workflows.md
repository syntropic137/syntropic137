# workflows

Workflow template management and execution.

## list_workflows()

List all workflow templates.

**Signature:**

```python
async def list_workflows(
    workflow_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[WorkflowSummary], WorkflowError]
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `workflow_type` | `str \| None` | `None` | Filter by type (research, planning, implementation, etc.) |
| `limit` | `int` | `100` | Maximum results |
| `offset` | `int` | `0` | Pagination offset |
| `auth` | `AuthContext \| None` | `None` | Optional auth context |

**Returns:** `Ok(list[WorkflowSummary])` on success.

**Errors:** None expected under normal operation.

**Example:**

```python
result = await syn_api.v1.workflows.list_workflows(workflow_type="research")
match result:
    case Ok(workflows):
        for wf in workflows:
            print(f"{wf.name} - {wf.phase_count} phases, {wf.runs_count} runs")
```

---

## get_workflow()

Get detailed information about a workflow template.

**Signature:**

```python
async def get_workflow(
    workflow_id: str,
    auth: AuthContext | None = None,
) -> Result[WorkflowDetail, WorkflowError]
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `workflow_id` | `str` | The workflow template ID |
| `auth` | `AuthContext \| None` | Optional auth context |

**Returns:** `Ok(WorkflowDetail)` on success.

**Errors:** `WorkflowError.NOT_FOUND` if the workflow doesn't exist.

**Example:**

```python
result = await syn_api.v1.workflows.get_workflow("wf-abc123")
match result:
    case Ok(detail):
        print(f"{detail.name}: {detail.description}")
    case Err(error, message):
        print(f"Not found: {message}")
```

---

## create_workflow()

Create a new workflow template.

**Signature:**

```python
async def create_workflow(
    name: str,
    workflow_type: str = "custom",
    classification: str = "standard",
    repository_url: str = "https://github.com/example/repo",
    repository_ref: str = "main",
    description: str | None = None,
    phases: list[dict[str, Any]] | None = None,
    auth: AuthContext | None = None,
) -> Result[str, WorkflowError]
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `name` | `str` | required | Workflow name |
| `workflow_type` | `str` | `"custom"` | Type: research, planning, implementation, review, deployment, custom |
| `classification` | `str` | `"standard"` | Classification: standard, advanced |
| `repository_url` | `str` | example URL | Repository URL |
| `repository_ref` | `str` | `"main"` | Git ref/branch |
| `description` | `str \| None` | `None` | Human-readable description |
| `phases` | `list[dict] \| None` | `None` | Phase definitions (auto-creates one if omitted) |
| `auth` | `AuthContext \| None` | `None` | Optional auth context |

**Returns:** `Ok(workflow_id)` on success.

**Errors:** `WorkflowError.INVALID_INPUT` on validation failure.

**Example:**

```python
result = await syn_api.v1.workflows.create_workflow(
    name="Research Pipeline",
    workflow_type="research",
    phases=[
        {"name": "Literature Review", "order": 1},
        {"name": "Analysis", "order": 2},
        {"name": "Summary", "order": 3},
    ],
)
```

---

## execute_workflow()

Execute a workflow.

**Signature:**

```python
async def execute_workflow(
    workflow_id: str,
    inputs: dict[str, str] | None = None,
    execution_id: str | None = None,
    task: str | None = None,
    auth: AuthContext | None = None,
) -> Result[ExecutionSummary, WorkflowError]
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `workflow_id` | `str` | required | Workflow template ID |
| `inputs` | `dict[str, str] \| None` | `None` | Named input variables — substituted for `{{variable}}` placeholders in prompts |
| `execution_id` | `str \| None` | `None` | Custom execution ID (auto-generated if omitted) |
| `task` | `str \| None` | `None` | Primary task description — substituted for `$ARGUMENTS` in prompts (ISS-211) |
| `auth` | `AuthContext \| None` | `None` | Optional auth context |

**Returns:** `Ok(ExecutionSummary)` on success.

**Errors:**
- `WorkflowError.NOT_FOUND` if the workflow doesn't exist
- `WorkflowError.EXECUTION_FAILED` on execution error

### Prompt Substitution

When a workflow executes, phase prompts are resolved in this order:

1. **Built-in variables:** `{{execution_id}}`, `{{workflow_id}}`, `{{repo_url}}`
2. **Named inputs:** Each key in `inputs` replaces `{{key}}` in the prompt
3. **Phase outputs:** Previous phase artifacts replace `{{phase-id}}` placeholders inline (e.g., `{{discovery}}` is replaced with the discovery phase's output). Phase outputs are also appended as a separate "Context from Previous Phases" section as a fallback.
4. **$ARGUMENTS:** The `task` string replaces `$ARGUMENTS` in the prompt (also available as `inputs["task"]`)

The `task` field is merged into `inputs` as `inputs["task"]`, so `$ARGUMENTS` and `{{task}}` are equivalent. When both the top-level `task` field and `inputs["task"]` are provided, the top-level `task` wins.

**Example:**

```python
# Using task for the primary goal + named inputs for context
result = await syn_api.v1.executions.execute(
    workflow_id="research-workflow-v2",
    task="Investigate how the auth middleware handles token rotation",
    inputs={"topic": "authentication"},
)

# Legacy style (still works — task injected via inputs)
result = await syn_api.v1.executions.execute(
    workflow_id="research-workflow-v2",
    inputs={"task": "Investigate auth middleware", "topic": "authentication"},
)
```

**HTTP API:**

```bash
curl -X POST /api/v1/workflows/research-workflow-v2/execute \
  -H "Content-Type: application/json" \
  -d '{"task": "Investigate auth middleware", "inputs": {"topic": "authentication"}}'
```

---

## get_execution()

Get detailed information about a workflow execution.

**Signature:**

```python
async def get_execution(
    execution_id: str,
    auth: AuthContext | None = None,
) -> Result[ExecutionDetail, WorkflowError]
```

**Returns:** `Ok(ExecutionDetail)` on success, `Err(WorkflowError.NOT_FOUND)` if missing.

---

## list_executions()

List workflow executions.

**Signature:**

```python
async def list_executions(
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[ExecutionSummary], WorkflowError]
```

**Returns:** `Ok(list[ExecutionSummary])` on success.
