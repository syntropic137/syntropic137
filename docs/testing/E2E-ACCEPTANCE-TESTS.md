# AEF End-to-End Acceptance Tests

**Version:** 2.0.0
**Created:** 2025-12-02
**Updated:** 2025-12-03
**Status:** Active

---

## Overview

This document defines acceptance tests for validating the Agentic Engineering Framework (AEF) stack end-to-end. Tests are organized by feature and include specific validation criteria.

**Version 2.0** adds comprehensive testing for the Agentic SDK integration including:
- AgenticWorkflowExecutor with claude-agent-sdk
- Workspace management with hook integration
- Artifact bundle flow between phases
- Event bridge connecting hook events to event store

### Test Environment

| Component | Port | Technology |
|-----------|------|------------|
| PostgreSQL | 5432 | postgres:16-alpine |
| Event Store Server | 50051 | Rust gRPC service |
| Dashboard Backend | 8000 | FastAPI |
| Dashboard Frontend | 5173 | Vite + React |
| **Agent Workspace** | - | LocalWorkspace (filesystem) |
| **Hook Analytics** | - | JSONL files in workspace |

### Prerequisites

**Infrastructure:**
- Docker and Docker Compose installed
- Node.js 18+ (for frontend)
- Python 3.12+ with uv
- All dependencies installed (`uv sync`)

**Agentic SDK (F8-F12):**
- `ANTHROPIC_API_KEY` environment variable set (for live agent tests)
- `uv pip install aef-adapters[claude-agentic]` for claude-agent-sdk
- `agentic-primitives` submodule initialized

**Quick Setup:**
```bash
# Install all dependencies including agentic SDK
uv sync --all-extras

# Set API key for live tests (optional, mocks used otherwise)
export ANTHROPIC_API_KEY=sk-ant-...

# Verify installation
python -c "from claude_agent_sdk import query; print('SDK OK')"
```

---

## ⚠️ Mocking Policy: Test Environment Only

> **CRITICAL**: All mock objects in the AEF codebase are **strictly test-only**.

### Environment Variable Enforcement

All mock classes (`MockAgent`, `MockProjectionManager`, `MockEventStoreClient`, etc.) include an environment check that **throws an error** if instantiated outside of the test environment:

```python
def _assert_test_environment() -> None:
    """Assert that we're running in a test environment."""
    app_env = os.getenv("APP_ENVIRONMENT", "").lower()
    if app_env != "test":
        raise MockTestEnvironmentError(
            f"Mock objects can only be used in test environment. "
            f"Current APP_ENVIRONMENT: '{app_env}'. "
            f"Set APP_ENVIRONMENT=test to use mocks."
        )
```

### Why This Matters

1. **Production Safety**: Prevents accidental use of mocks in development/staging/production
2. **Real Integration Testing**: Forces E2E tests to use real implementations
3. **Early Detection**: Fails immediately with a clear error message if misconfigured
4. **Explicit Intent**: Makes it obvious when test code is being used

### Running Tests

Always set `APP_ENVIRONMENT=test` when running unit tests:

```bash
# Correct - mocks are allowed
APP_ENVIRONMENT=test pytest

# Will fail if mocks are used
APP_ENVIRONMENT=development pytest  # ❌ MockTestEnvironmentError
```

### Reference

See [ADR-004: Environment Configuration](/docs/adrs/ADR-004-environment-configuration.md) for the full environment configuration strategy.

---

## Feature 1: Infrastructure & Docker

### F1.1 Docker Compose Startup

**Given** the development environment is clean
**When** I run `just dev`
**Then** Docker Compose starts successfully

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 1.1.1 | PostgreSQL container starts and becomes healthy | ⬜ |
| 1.1.2 | Event Store Server container starts and becomes healthy | ⬜ |
| 1.1.3 | Containers are on the `aef-network` | ⬜ |
| 1.1.4 | PostgreSQL is accessible on localhost:5432 | ⬜ |
| 1.1.5 | Event Store Server is accessible on localhost:50051 | ⬜ |

**Validation Commands:**
```bash
just dev
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker network inspect aef-network
```

### F1.2 Database Initialization

**Given** Docker containers are running
**When** I connect to PostgreSQL
**Then** the database is ready for events

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 1.2.1 | Database `aef` exists | ⬜ |
| 1.2.2 | User `aef` can connect | ⬜ |
| 1.2.3 | Event Store Server has created `events` table | ⬜ |

**Validation Commands:**
```bash
docker exec aef-postgres psql -U aef -d aef -c "\dt"
```

---

## Feature 2: Event Store Integration

### F2.1 Event Persistence via gRPC

**Given** Event Store Server is running
**When** I seed workflows via CLI
**Then** events are persisted to PostgreSQL

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 2.1.1 | CLI connects to Event Store via gRPC | ⬜ |
| 2.1.2 | WorkflowCreated events are stored | ⬜ |
| 2.1.3 | Events have correct aggregate_type = 'Workflow' | ⬜ |
| 2.1.4 | Events have valid JSON payload | ⬜ |
| 2.1.5 | Events have sequential event_version | ⬜ |

**Validation Commands:**
```bash
just cli workflow seed
just validate-events
```

### F2.2 Event Store Validation Script

**Given** events have been persisted
**When** I run the validation script
**Then** I see a summary of all events

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 2.2.1 | Script connects to PostgreSQL | ⬜ |
| 2.2.2 | Shows total event count | ⬜ |
| 2.2.3 | Shows events by aggregate type | ⬜ |
| 2.2.4 | Shows events by event type | ⬜ |
| 2.2.5 | Shows recent events with details | ⬜ |
| 2.2.6 | Shows workflow aggregate summaries | ⬜ |

**Validation Commands:**
```bash
just validate-events
```

---

## Feature 3: CLI Workflow Management

### F3.1 Workflow Seeding

**Given** Event Store is running
**When** I run `just cli workflow seed`
**Then** sample workflows are created

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3.1.1 | Command completes without error | ⬜ |
| 3.1.2 | Shows success message for each workflow | ⬜ |
| 3.1.3 | Handles "already exists" gracefully | ⬜ |
| 3.1.4 | Shows summary (total/succeeded/skipped/failed) | ⬜ |

**Validation Commands:**
```bash
just cli workflow seed
just cli workflow seed  # Run again to test idempotency
```

### F3.2 Workflow Listing

**Given** workflows have been seeded
**When** I run `just cli workflow list`
**Then** I see all workflows

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3.2.1 | Command completes without error | ⬜ |
| 3.2.2 | Shows workflow IDs | ⬜ |
| 3.2.3 | Shows workflow names | ⬜ |
| 3.2.4 | Shows workflow types | ⬜ |
| 3.2.5 | Shows workflow status | ⬜ |

**Validation Commands:**
```bash
just cli workflow list
```

### F3.3 Workflow Status

**Given** a workflow exists
**When** I run `just cli workflow status <id>`
**Then** I see detailed workflow information

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3.3.1 | Shows workflow details | ⬜ |
| 3.3.2 | Shows phases | ⬜ |
| 3.3.3 | Returns error for non-existent workflow | ⬜ |

**Validation Commands:**
```bash
just cli workflow status <workflow-id>
just cli workflow status non-existent-id
```

---

## Feature 4: Dashboard Backend API

### F4.1 Health Check

**Given** the dashboard backend is running
**When** I request the health endpoint
**Then** I get a healthy response

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 4.1.1 | GET /health returns 200 | ⬜ |
| 4.1.2 | Response includes status: "healthy" | ⬜ |

**Validation Commands:**
```bash
curl -s http://localhost:8000/health | jq
```

### F4.2 Workflow Endpoints

**Given** workflows have been seeded
**When** I request workflow endpoints
**Then** I get correct data

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 4.2.1 | GET /api/workflows returns 200 | ⬜ |
| 4.2.2 | Response includes workflows array | ⬜ |
| 4.2.3 | Each workflow has id, name, workflow_type, status | ⬜ |
| 4.2.4 | Pagination works (page, page_size params) | ⬜ |
| 4.2.5 | GET /api/workflows/{id} returns workflow details | ⬜ |
| 4.2.6 | Workflow details include phases array | ⬜ |
| 4.2.7 | GET /api/workflows/{invalid-id} returns 404 | ⬜ |

**Validation Commands:**
```bash
curl -s http://localhost:8000/api/workflows | jq
curl -s http://localhost:8000/api/workflows?page=1&page_size=5 | jq
curl -s http://localhost:8000/api/workflows/<workflow-id> | jq
curl -s http://localhost:8000/api/workflows/invalid-id
```

### F4.3 Session Endpoints

**Given** the dashboard backend is running
**When** I request session endpoints
**Then** I get correct responses

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 4.3.1 | GET /api/sessions returns 200 | ⬜ |
| 4.3.2 | Response is an array (empty if no sessions) | ⬜ |
| 4.3.3 | Filter by workflow_id works | ⬜ |
| 4.3.4 | GET /api/sessions/{invalid-id} returns 404 | ⬜ |

**Validation Commands:**
```bash
curl -s http://localhost:8000/api/sessions | jq
curl -s "http://localhost:8000/api/sessions?workflow_id=<id>" | jq
```

### F4.4 Artifact Endpoints

**Given** the dashboard backend is running
**When** I request artifact endpoints
**Then** I get correct responses

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 4.4.1 | GET /api/artifacts returns 200 | ⬜ |
| 4.4.2 | Response is an array (empty if no artifacts) | ⬜ |
| 4.4.3 | Filter by workflow_id works | ⬜ |
| 4.4.4 | GET /api/artifacts/{invalid-id} returns 404 | ⬜ |

**Validation Commands:**
```bash
curl -s http://localhost:8000/api/artifacts | jq
curl -s "http://localhost:8000/api/artifacts?workflow_id=<id>" | jq
```

### F4.5 Metrics Endpoint

**Given** workflows have been seeded
**When** I request metrics
**Then** I get aggregated data

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 4.5.1 | GET /api/metrics returns 200 | ⬜ |
| 4.5.2 | Response includes total_workflows | ⬜ |
| 4.5.3 | Response includes total_sessions | ⬜ |
| 4.5.4 | Response includes total_artifacts | ⬜ |
| 4.5.5 | total_workflows matches seeded count | ⬜ |
| 4.5.6 | Filter by workflow_id works | ⬜ |

**Validation Commands:**
```bash
curl -s http://localhost:8000/api/metrics | jq
curl -s "http://localhost:8000/api/metrics?workflow_id=<id>" | jq
```

### F4.6 SSE Events Stream

**Given** the dashboard backend is running
**When** I connect to the events stream
**Then** I receive server-sent events

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 4.6.1 | GET /api/events/stream returns SSE content-type | ⬜ |
| 4.6.2 | Connection stays open | ⬜ |
| 4.6.3 | Receives heartbeat events | ⬜ |

**Validation Commands:**
```bash
curl -N http://localhost:8000/api/events/stream
```

---

## Feature 5: Dashboard Frontend

### F5.1 Application Load

**Given** the frontend dev server is running
**When** I navigate to http://localhost:5173
**Then** the application loads

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.1.1 | Page loads without JavaScript errors | ⬜ |
| 5.1.2 | Navigation sidebar is visible | ⬜ |
| 5.1.3 | Default route shows dashboard/home | ⬜ |

**Validation Steps:**
1. Open http://localhost:5173 in browser
2. Open browser DevTools → Console
3. Check for errors

### F5.2 Workflows Page

**Given** workflows have been seeded
**When** I navigate to the Workflows page
**Then** I see the workflow list

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.2.1 | Workflows page is accessible | ⬜ |
| 5.2.2 | Workflow cards/rows are displayed | ⬜ |
| 5.2.3 | Each workflow shows name | ⬜ |
| 5.2.4 | Each workflow shows type | ⬜ |
| 5.2.5 | Each workflow shows status | ⬜ |
| 5.2.6 | Clicking a workflow navigates to detail | ⬜ |

**Validation Steps:**
1. Click "Workflows" in navigation
2. Verify list is populated
3. Click on a workflow

### F5.3 Workflow Detail Page

**Given** I click on a workflow
**When** the detail page loads
**Then** I see workflow details

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.3.1 | Workflow name is displayed | ⬜ |
| 5.3.2 | Workflow description is displayed | ⬜ |
| 5.3.3 | Phases are listed | ⬜ |
| 5.3.4 | Phase names are displayed | ⬜ |
| 5.3.5 | Back navigation works | ⬜ |

**Validation Steps:**
1. Navigate to workflow detail
2. Verify all information displays
3. Click back button

### F5.4 Metrics/Dashboard Page

**Given** workflows have been seeded
**When** I view the dashboard/metrics page
**Then** I see aggregated metrics

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.4.1 | Total workflows count is displayed | ⬜ |
| 5.4.2 | Count matches seeded workflows | ⬜ |
| 5.4.3 | Sessions count shows (may be 0) | ⬜ |
| 5.4.4 | Artifacts count shows (may be 0) | ⬜ |

**Validation Steps:**
1. Navigate to dashboard home
2. Check metric cards/numbers

### F5.5 Real-time Updates

**Given** the frontend is connected to SSE
**When** new events occur
**Then** the UI updates

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.5.1 | SSE connection established (Network tab) | ⬜ |
| 5.5.2 | No connection errors in console | ⬜ |

**Validation Steps:**
1. Open DevTools → Network
2. Filter by "EventStream" or "stream"
3. Verify connection is active

---

## Feature 6: Data Consistency

### F6.1 CLI ↔ Database Consistency

**Given** workflows are seeded via CLI
**When** I query the database directly
**Then** data matches CLI output

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 6.1.1 | Workflow count matches | ⬜ |
| 6.1.2 | Workflow IDs match | ⬜ |
| 6.1.3 | Workflow names match | ⬜ |

**Validation Commands:**
```bash
just cli workflow list
just validate-events
# Compare counts and IDs
```

### F6.2 Database ↔ API Consistency

**Given** events are in the database
**When** I query the API
**Then** data matches database

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 6.2.1 | API workflow count matches database | ⬜ |
| 6.2.2 | API workflow details match event payload | ⬜ |

**Validation Commands:**
```bash
just validate-events
curl -s http://localhost:8000/api/workflows | jq '.total'
# Compare counts
```

### F6.3 API ↔ Frontend Consistency

**Given** the API returns data
**When** the frontend displays it
**Then** data matches API response

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 6.3.1 | Frontend workflow count matches API | ⬜ |
| 6.3.2 | Frontend workflow names match API | ⬜ |

**Validation Steps:**
1. Note API response from curl
2. Compare with frontend display

---

## Feature 7: Error Handling

### F7.1 Graceful Degradation

**Given** a component is unavailable
**When** dependent services try to connect
**Then** errors are handled gracefully

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.1.1 | API handles database timeout gracefully | ⬜ |
| 7.1.2 | CLI handles Event Store unavailable | ⬜ |
| 7.1.3 | Frontend handles API errors | ⬜ |

### F7.2 Invalid Input Handling

**Given** invalid input is provided
**When** the system processes it
**Then** appropriate errors are returned

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.2.1 | API returns 404 for non-existent resources | ⬜ |
| 7.2.2 | API returns 400 for invalid parameters | ⬜ |
| 7.2.3 | CLI shows helpful error messages | ⬜ |

---

## Feature 8: Agentic Workflow Execution ⭐ NEW

> **Requires:** `aef-adapters[claude-agentic]` installed

### F8.1 AgenticWorkflowExecutor Initialization

**Given** the agentic SDK is configured
**When** I create an AgenticWorkflowExecutor
**Then** it initializes with correct dependencies

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 8.1.1 | Executor accepts agent_factory parameter | ⬜ |
| 8.1.2 | Executor accepts workspace_factory parameter | ⬜ |
| 8.1.3 | Executor accepts event_store parameter | ⬜ |
| 8.1.4 | Default agent factory returns ClaudeAgenticAgent | ⬜ |

**Validation (Python):**
```python
from aef_adapters.orchestration import AgenticWorkflowExecutor, get_agentic_agent

# Verify executor creation
executor = AgenticWorkflowExecutor(
    workflow_repository=mock_repo,
    session_repository=mock_session_repo,
    artifact_repository=mock_artifact_repo,
    event_store=mock_event_store,
    agent_factory=get_agentic_agent,
)
assert executor is not None
```

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_orchestration.py -v -k "test_executor"
```

### F8.2 Single-Phase Workflow Execution

**Given** a workflow with one phase
**When** I execute it with AgenticWorkflowExecutor
**Then** events are emitted in correct order

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 8.2.1 | WorkflowExecutionStarted event emitted first | ⬜ |
| 8.2.2 | PhaseStarted event contains phase_id and session_id | ⬜ |
| 8.2.3 | PhaseCompleted event contains token counts | ⬜ |
| 8.2.4 | WorkflowCompleted event contains artifact_ids | ⬜ |
| 8.2.5 | Execution creates workspace directory | ⬜ |
| 8.2.6 | Result status is COMPLETED on success | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_orchestration.py -v -k "test_execute_simple"
```

### F8.3 Multi-Phase Workflow Execution

**Given** a workflow with multiple phases
**When** I execute it with AgenticWorkflowExecutor
**Then** phases execute in order with context passing

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 8.3.1 | Phases execute in order (by phase.order) | ⬜ |
| 8.3.2 | Phase outputs are available to subsequent phases | ⬜ |
| 8.3.3 | Artifact bundles accumulate across phases | ⬜ |
| 8.3.4 | Total token count is sum of all phases | ⬜ |
| 8.3.5 | Previous phase output substituted in prompts | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_orchestration.py -v -k "test_execute_multi"
```

### F8.4 Execution Failure Handling

**Given** a phase fails during execution
**When** the executor handles the failure
**Then** proper error events are emitted

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 8.4.1 | PhaseCompleted event has success=False | ⬜ |
| 8.4.2 | WorkflowFailed event contains error_message | ⬜ |
| 8.4.3 | WorkflowFailed event contains failed_phase_id | ⬜ |
| 8.4.4 | Result status is FAILED | ⬜ |
| 8.4.5 | Partial results (completed phases) are preserved | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_orchestration.py -v -k "test_phase_failure"
```

### F8.5 Live Agent Execution (Requires ANTHROPIC_API_KEY)

**Given** `ANTHROPIC_API_KEY` is set
**When** I execute a simple task with ClaudeAgenticAgent
**Then** the agent completes using claude-agent-sdk

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 8.5.1 | Agent uses claude-agent-sdk under the hood | ⬜ |
| 8.5.2 | TaskCompleted event has result text | ⬜ |
| 8.5.3 | Token usage is reported accurately | ⬜ |
| 8.5.4 | Agent can use tools (if permitted) | ⬜ |

**Validation (Manual - requires API key):**
```python
import asyncio
from aef_adapters.agents import ClaudeAgenticAgent
from aef_adapters.agents.agentic_types import AgentExecutionConfig, Workspace

agent = ClaudeAgenticAgent()
assert agent.is_available, "Set ANTHROPIC_API_KEY"

config = AgentExecutionConfig(model="claude-sonnet-4-20250514")
workspace = Workspace(path=Path("/tmp/test-workspace"))

async def test():
    async for event in agent.execute("Say hello", workspace, config):
        print(event)

asyncio.run(test())
```

---

## Feature 9: Workspace & Hook Integration ⭐ NEW

> **Requires:** `agentic-primitives` submodule initialized

### F9.1 LocalWorkspace Creation

**Given** a WorkspaceConfig
**When** I create a LocalWorkspace
**Then** it sets up the directory structure

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 9.1.1 | Workspace directory is created | ⬜ |
| 9.1.2 | Context subdirectory exists | ⬜ |
| 9.1.3 | Output subdirectory exists | ⬜ |
| 9.1.4 | Workspace path property is correct | ⬜ |
| 9.1.5 | Workspace works as async context manager | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_workspaces.py -v -k "test_local_workspace"
```

### F9.2 Hook Settings Generation

**Given** a LocalWorkspace with hooks_source
**When** it initializes
**Then** .claude/settings.json is created with hook config

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 9.2.1 | .claude/settings.json is created | ⬜ |
| 9.2.2 | Settings include security validators | ⬜ |
| 9.2.3 | Settings include analytics collector | ⬜ |
| 9.2.4 | Analytics output_path points to workspace | ⬜ |

**Validation (Manual):**
```python
from aef_adapters.workspaces import LocalWorkspace, WorkspaceConfig
from pathlib import Path

config = WorkspaceConfig(
    session_id="test-session",
    base_dir=Path("/tmp/test-workspace"),
    workflow_id="wf-1",
    phase_id="p-1",
    hooks_source=Path("lib/agentic-primitives/examples/settings.json"),
)

async with await LocalWorkspace.create(config) as ws:
    settings_path = ws.path / ".claude" / "settings.json"
    assert settings_path.exists()
    print(settings_path.read_text())
```

### F9.3 Analytics JSONL File

**Given** a workspace with hook settings
**When** an agent executes (or hooks fire)
**Then** analytics events are written to JSONL

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 9.3.1 | analytics.jsonl file is created | ⬜ |
| 9.3.2 | Events are valid JSON lines | ⬜ |
| 9.3.3 | Events include session_id correlation | ⬜ |
| 9.3.4 | Events include workflow_id and phase_id | ⬜ |

**Validation (Manual after agent execution):**
```bash
cat /tmp/test-workspace/analytics.jsonl | jq -s '.'
```

### F9.4 Context Injection

**Given** a workspace and PhaseContext
**When** I inject context files
**Then** files are written to context directory

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 9.4.1 | inject_context writes files to workspace | ⬜ |
| 9.4.2 | Previous artifact contents available | ⬜ |
| 9.4.3 | Context files readable by agent | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_workspaces.py -v -k "test_inject"
```

---

## Feature 10: Artifact Bundle Flow ⭐ NEW

### F10.1 ArtifactBundle Creation

**Given** phase output files
**When** I create an ArtifactBundle
**Then** it contains files with metadata

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 10.1.1 | Bundle has unique bundle_id | ⬜ |
| 10.1.2 | Bundle tracks workflow_id | ⬜ |
| 10.1.3 | Bundle tracks phase_id and session_id | ⬜ |
| 10.1.4 | Files have content hashes (SHA-256) | ⬜ |
| 10.1.5 | Bundle has timestamp | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_artifacts.py -v -k "test_artifact_bundle"
```

### F10.2 Directory Collection

**Given** a directory with files
**When** I call ArtifactBundle.from_directory()
**Then** all files are collected recursively

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 10.2.1 | Nested files are included | ⬜ |
| 10.2.2 | Content types are inferred (.py → TEXT_PYTHON) | ⬜ |
| 10.2.3 | Binary files are handled correctly | ⬜ |
| 10.2.4 | Exclude patterns work (e.g., "*.log") | ⬜ |
| 10.2.5 | Include patterns work | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_artifacts.py -v -k "test_from_directory"
```

### F10.3 Serialization / Deserialization

**Given** an ArtifactBundle
**When** I serialize and deserialize it
**Then** content is preserved

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 10.3.1 | to_dict() produces valid JSON-serializable dict | ⬜ |
| 10.3.2 | from_dict() reconstructs identical bundle | ⬜ |
| 10.3.3 | File content is preserved through round-trip | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_artifacts.py -v -k "test_serialization"
```

### F10.4 PhaseContext Creation

**Given** previous phase artifacts
**When** I build PhaseContext
**Then** artifacts are accessible

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 10.4.1 | PhaseContext contains previous_artifacts list | ⬜ |
| 10.4.2 | PhaseContext has config dict | ⬜ |
| 10.4.3 | PhaseContext has environment dict | ⬜ |
| 10.4.4 | Serialization works correctly | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_artifacts.py -v -k "test_phase_context"
```

---

## Feature 11: Event Bridge ⭐ NEW

> **Requires:** `agentic-hooks` package installed

### F11.1 JSONLWatcher

**Given** a JSONL file with hook events
**When** I watch it with JSONLWatcher
**Then** I receive HookEvent objects

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 11.1.1 | Existing lines are read on start | ⬜ |
| 11.1.2 | New lines trigger events (streaming) | ⬜ |
| 11.1.3 | Invalid JSON is logged and skipped | ⬜ |
| 11.1.4 | File creation is handled if missing | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_events.py -v -k "test_watcher"
```

### F11.2 HookToDomainTranslator

**Given** a HookEvent
**When** I translate it
**Then** I get the appropriate DomainEvent

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 11.2.1 | SESSION_STARTED → SessionStarted | ⬜ |
| 11.2.2 | SESSION_COMPLETED → SessionCompleted | ⬜ |
| 11.2.3 | TOOL_EXECUTION_STARTED → ToolExecutionStarted | ⬜ |
| 11.2.4 | TOOL_EXECUTION_COMPLETED → ToolExecutionCompleted | ⬜ |
| 11.2.5 | AGENT_REQUEST_STARTED → AgentRequestStarted | ⬜ |
| 11.2.6 | AGENT_REQUEST_COMPLETED → AgentRequestCompleted | ⬜ |
| 11.2.7 | Unknown event types return None | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_events.py -v -k "test_translator"
```

### F11.3 EventBridge Integration

**Given** an EventBridge with event store
**When** hook events are written to JSONL
**Then** they appear in the event store

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 11.3.1 | process_file() reads existing events | ⬜ |
| 11.3.2 | Events are appended to store with correct aggregate_id | ⬜ |
| 11.3.3 | Metadata includes hook_event_id for tracing | ⬜ |
| 11.3.4 | watch() streams new events in real-time | ⬜ |
| 11.3.5 | Callbacks are invoked for each bridged event | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_events.py -v -k "test_bridge"
```

---

## Feature 12: Agent Provider Management ⭐ NEW

### F12.1 Agent Factory

**Given** a provider name
**When** I call get_agentic_agent()
**Then** I get the correct agent implementation

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 12.1.1 | "claude" returns ClaudeAgenticAgent | ⬜ |
| 12.1.2 | Unknown provider raises ValueError | ⬜ |
| 12.1.3 | Provider names are case-insensitive | ⬜ |

**Validation (pytest):**
```bash
pytest packages/aef-adapters/tests/test_orchestration.py -v -k "test_agent_factory"
```

### F12.2 Agent Availability

**Given** an agent instance
**When** I check is_available property
**Then** it reflects configuration state

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 12.2.1 | Returns False if ANTHROPIC_API_KEY missing | ⬜ |
| 12.2.2 | Returns False if claude-agent-sdk not installed | ⬜ |
| 12.2.3 | Returns True if properly configured | ⬜ |

**Validation (Python):**
```python
from aef_adapters.agents import ClaudeAgenticAgent
import os

# Without API key
os.environ.pop("ANTHROPIC_API_KEY", None)
agent = ClaudeAgenticAgent()
assert agent.is_available == False

# With API key
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
agent = ClaudeAgenticAgent()
assert agent.is_available == True  # (assuming SDK installed)
```

### F12.3 MockAgent Safety

**Given** MockAgent is instantiated
**When** APP_ENVIRONMENT is not "test"
**Then** it raises an error

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 12.3.1 | MockAgent raises error in development env | ⬜ |
| 12.3.2 | MockAgent raises error in production env | ⬜ |
| 12.3.3 | MockAgent works in test environment | ⬜ |

**Validation (Python):**
```python
import os
from aef_adapters.agents import MockAgent

# This should raise RuntimeError
os.environ["APP_ENVIRONMENT"] = "development"
try:
    agent = MockAgent()
    assert False, "Should have raised"
except RuntimeError as e:
    assert "test environment" in str(e)

# This should work
os.environ["APP_ENVIRONMENT"] = "test"
agent = MockAgent()
assert agent is not None
```

---

## Test Execution Checklist

### Pre-Test Setup
- [ ] Clean Docker environment (`docker compose down -v`)
- [ ] Fresh database (no existing data)
- [ ] Dependencies installed (`uv sync --all-extras`, `npm install`)
- [ ] **NEW:** `ANTHROPIC_API_KEY` set (for F8.5 live tests)
- [ ] **NEW:** Submodules initialized (`git submodule update --init`)

### Execution Order

**Infrastructure & Core (F1-F7):**
1. [ ] **F1: Infrastructure** - Start Docker, verify containers
2. [ ] **F2: Event Store** - Seed data, validate events
3. [ ] **F3: CLI** - Test all CLI commands
4. [ ] **F4: Backend API** - Test all endpoints
5. [ ] **F5: Frontend** - Visual inspection in browser
6. [ ] **F6: Consistency** - Cross-component validation
7. [ ] **F7: Error Handling** - Edge cases

**Agentic Integration (F8-F12):**
8. [ ] **F8: Agentic Execution** - AgenticWorkflowExecutor tests
9. [ ] **F9: Workspaces** - LocalWorkspace with hooks
10. [ ] **F10: Artifacts** - ArtifactBundle flow
11. [ ] **F11: Event Bridge** - Hook-to-domain events
12. [ ] **F12: Providers** - Agent factory and availability

### Quick Pytest Commands

```bash
# Run all agentic tests (F8-F12)
pytest packages/aef-adapters/tests/test_*.py -v

# Run specific feature tests
pytest packages/aef-adapters/tests/test_orchestration.py -v      # F8
pytest packages/aef-adapters/tests/test_workspaces.py -v         # F9
pytest packages/aef-adapters/tests/test_artifacts.py -v          # F10
pytest packages/aef-adapters/tests/test_events.py -v             # F11
pytest packages/aef-adapters/tests/test_claude_agentic.py -v     # F12
```

### Post-Test
- [ ] Document any failures
- [ ] Create issues for bugs found
- [ ] Update CASA with results

---

## Test Results Summary

| Feature | Description | Criteria | Passed | Failed | Skipped |
|---------|-------------|----------|--------|--------|---------|
| F1 | Infrastructure & Docker | 8 | ⬜ | ⬜ | ⬜ |
| F2 | Event Store Integration | 11 | ⬜ | ⬜ | ⬜ |
| F3 | CLI Workflow Management | 12 | ⬜ | ⬜ | ⬜ |
| F4 | Dashboard Backend API | 21 | ⬜ | ⬜ | ⬜ |
| F5 | Dashboard Frontend | 15 | ⬜ | ⬜ | ⬜ |
| F6 | Data Consistency | 6 | ⬜ | ⬜ | ⬜ |
| F7 | Error Handling | 6 | ⬜ | ⬜ | ⬜ |
| **F8** | **Agentic Workflow Execution** | **16** | ⬜ | ⬜ | ⬜ |
| **F9** | **Workspace & Hook Integration** | **13** | ⬜ | ⬜ | ⬜ |
| **F10** | **Artifact Bundle Flow** | **13** | ⬜ | ⬜ | ⬜ |
| **F11** | **Event Bridge** | **12** | ⬜ | ⬜ | ⬜ |
| **F12** | **Agent Provider Management** | **9** | ⬜ | ⬜ | ⬜ |
| **TOTAL** | | **142** | ⬜ | ⬜ | ⬜ |

---

## Issues Found

| # | Feature | Description | Severity | Status |
|---|---------|-------------|----------|--------|
| | | | | |

---

## Notes

_Add any observations, recommendations, or follow-up items here._

### Migration Notes (v1.0 → v2.0)

- **New Prerequisites:** ANTHROPIC_API_KEY required for live agent tests (F8.5)
- **New Dependencies:** `aef-adapters[claude-agentic]` adds claude-agent-sdk
- **Test Count:** Increased from 79 to 142 criteria
- **Automation:** F8-F12 tests are fully automatable via pytest

### Test Categories

| Category | Features | Automation |
|----------|----------|------------|
| Infrastructure | F1, F2 | Shell + Docker |
| CLI | F3 | Shell scripts |
| API | F4 | curl/httpie or pytest |
| Frontend | F5 | Manual browser |
| Integration | F6, F7 | Mixed |
| **Agentic** | **F8-F12** | **pytest (automated)** |
