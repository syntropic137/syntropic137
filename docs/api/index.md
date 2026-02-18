# AEF API

Programmatic interface to the Syntropic137.

## Overview

`syn-api` is the single entry point for interacting with AEF programmatically. Everything — CLI commands, dashboard operations, third-party integrations, and LLM tool-use — goes through this API.

## Installation

```bash
# As part of the AEF workspace
uv sync
```

```python
import syn_api
print(syn_api.__version__)  # "0.1.0"
```

## Quick Start

```python
import syn_api
from syn_api import Ok, Err

# List workflows
result = await syn_api.v1.workflows.list_workflows()
match result:
    case Ok(workflows):
        for wf in workflows:
            print(f"{wf.name} ({wf.workflow_type})")
    case Err(error):
        print(f"Error: {error}")

# Create a workflow
result = await syn_api.v1.workflows.create_workflow(
    name="My Research Workflow",
    workflow_type="research",
    description="Automated research pipeline",
)
match result:
    case Ok(workflow_id):
        print(f"Created: {workflow_id}")
    case Err(error):
        print(f"Failed: {error.message}")
```

## Architecture

```
syn-api
├── types.py         # Result[T, E], Ok, Err, Pydantic models, error enums
├── auth.py          # AuthContext (optional parameter)
├── _wiring.py       # Internal: adapter composition root
└── v1/
    ├── workflows.py     # Workflow template CRUD + execution
    ├── workspaces.py    # Isolated workspace management
    ├── sessions.py      # Agent session lifecycle
    ├── artifacts.py     # Artifact storage (stub)
    ├── github.py        # GitHub integration (stub)
    └── observability.py # Metrics and telemetry (stub)
```

## Result Type

All API functions return `Result[T, E]` — either `Ok(value)` or `Err(error, message)`. Use pattern matching or `isinstance` checks:

```python
result = await syn_api.v1.workflows.get_workflow("wf-123")

# Pattern matching (recommended)
match result:
    case Ok(detail):
        print(detail.name)
    case Err(error, message):
        print(f"{error}: {message}")

# isinstance check
if isinstance(result, Ok):
    print(result.value.name)
```

## Modules

| Module | Status | Description |
|--------|--------|-------------|
| [workflows](v1/workflows.md) | Implemented | Workflow templates and executions |
| [workspaces](v1/workspaces.md) | Partial | Isolated workspace management |
| [sessions](v1/sessions.md) | Implemented | Agent session lifecycle |
| [artifacts](v1/artifacts.md) | Stub | Artifact storage and retrieval |
| [github](v1/github.md) | Stub | GitHub App integration |
| [observability](v1/observability.md) | Stub | Metrics and telemetry |

## Authentication

All functions accept an optional `AuthContext` parameter. When `None` (the default), operations run without authorization checks.

```python
from syn_api import AuthContext

auth = AuthContext(user_id="user-123", tenant_id="tenant-abc")
result = await syn_api.v1.workflows.list_workflows(auth=auth)
```

See [auth.md](v1/auth.md) for details.
