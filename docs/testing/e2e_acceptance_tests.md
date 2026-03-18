# Syn137 End-to-End Acceptance Tests

**Version:** 6.3.0
**Created:** 2025-12-02
**Updated:** 2025-12-15
**Status:** Active

---

## Overview

This document defines acceptance tests for validating the Syntropic137 stack end-to-end. Tests are organized by feature and include specific validation criteria.

**Version 6.3** adds:
- **WorkspaceService Architecture (F18)** - Full E2E validation of new event-sourced workspace domain
- **Deprecated WorkspaceRouter Removed** - Old module deleted, all references updated
- **Event-Sourced WorkspaceAggregate** - Immutable audit trail for workspace lifecycle
- **DI-First Adapters** - Docker, Memory, Token adapters with Protocol interfaces
- **70 New Test Criteria** - Comprehensive E2E coverage for workspace domain

**Version 6.2** adds:
- **Container Execution Robustness (F17)** - Phase counting, artifact collection, session persistence
- **Type-Safe Workspace Paths** - Shared constants module in `syn_shared.workspace_paths`
- **Git Attribution Control** - Disable Claude Co-Authored-By trailer via settings
- **Analytics Streaming** - Real-time hook events via sidecar
- **Stale Execution Cleanup** - Background job for stuck executions
- **60 New Test Criteria** - Comprehensive coverage for container execution

**Version 6.1** adds:
- **Workspace-First Execution (F16)** - ADR-023 enforcement (LocalWorkspace test-only, WorkspaceRouter required)
- **AgentExecutor Protocol** - Abstraction for running agents in isolated workspaces
- **InMemoryWorkspace** - Fast in-memory workspace for unit tests
- **Required DI** - WorkflowExecutionEngine requires execution_repository and workspace_router
- **Full Isolation Plan** - `docs/PLAN-FULL-WORKSPACE-ISOLATION.md`

**Version 6.0** adds:
- **GitHub App Integration** - Secure bot authentication with short-lived tokens
- **Token Vending Service** - Scoped, 5-minute TTL tokens per execution
- **Spend Tracker** - Budget allocation and cost limits per workflow
- **Sidecar Proxy** - Envoy-based token injection and request logging
- **E2E Test Script** - `scripts/e2e_github_app_test.py` for full flow testing

**Version 5.0** adds:
- **Isolated Workspace Architecture** - Docker/gVisor isolation for all agent workspaces
- **Git Identity Injection** - Configure commit author in containers
- **API Key Injection** - ANTHROPIC_API_KEY automatically available
- **Container Logging** - Structured JSON logs with secret redaction
- **Network Allowlist** - mitmproxy-based egress control
- **Dashboard Workspace Display** - Real-time workspace info in UI

**Version 4.0** adds:
- **WebSocket Control Plane** - Real-time execution control (pause/resume/cancel)
- **Control API Endpoints** - HTTP and WebSocket interfaces
- **Executor Integration** - Signal checking at yield points
- **Frontend Control UI** - Interactive control buttons
- **CLI Control Commands** - Terminal-based execution control

**Version 3.0** adds:
- **Workflow Execution Model** - Separate Templates from Executions/Runs
- **Event Store Verification** - Critical tests ensuring all events reach the event store
- **PhaseCompleted Events** - Verification of phase metrics propagation
- **Execution Detail API** - New endpoints for viewing individual runs

**Version 2.0** added comprehensive testing for the Agentic SDK integration including:
- AgenticWorkflowExecutor with claude-agent-sdk
- Workspace management with hook integration
- Artifact bundle flow between phases
- Event bridge connecting hook events to event store

---

## ⚠️ CRITICAL: Event Store is the Source of Truth

> **GOLDEN RULE: If it's not in the Event Store, it didn't happen.**

All state changes in Syn137 **MUST** be persisted to the event store via aggregates. This is non-negotiable because:

1. **Projections depend on events** - Read models are built from event streams
2. **Audit trail** - Events provide complete history of all actions
3. **Recovery** - System state can be rebuilt from events
4. **Consistency** - Single source of truth prevents data drift

### Event Emission Checklist

Every command handler MUST emit events. Verify these are in the event store:

| Action | Expected Event | Aggregate |
|--------|----------------|-----------|
| Start workflow execution | `WorkflowExecutionStarted` | WorkflowExecution |
| Complete phase | `PhaseCompleted` | WorkflowExecution |
| Complete workflow | `WorkflowCompleted` | WorkflowExecution |
| Fail workflow | `WorkflowFailed` | WorkflowExecution |
| Start session | `SessionStarted` | AgentSession |
| Record operation | `OperationRecorded` | AgentSession |
| Complete session | `SessionCompleted` | AgentSession |
| Create artifact | `ArtifactCreated` | Artifact |
| Create workflow | `WorkflowCreated` | Workflow |

### Verification Query

After any action, verify events exist:

```sql
-- Check events were persisted
SELECT event_type, aggregate_id, global_nonce, created_at
FROM events
WHERE event_type = 'PhaseCompleted'
ORDER BY global_nonce DESC
LIMIT 10;
```

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
- `uv pip install syn-adapters[claude-agentic]` for claude-agent-sdk
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

> **CRITICAL**: All mock objects in the Syn137 codebase are **strictly test-only**.

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
| 1.1.3 | Containers are on the `syn-network` | ⬜ |
| 1.1.4 | PostgreSQL is accessible on localhost:5432 | ⬜ |
| 1.1.5 | Event Store Server is accessible on localhost:50051 | ⬜ |

**Validation Commands:**
```bash
just dev
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker network inspect syn-network
```

### F1.2 Database Initialization

**Given** Docker containers are running
**When** I connect to PostgreSQL
**Then** the database is ready for events

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 1.2.1 | Database `syn` exists | ⬜ |
| 1.2.2 | User `syn` can connect | ⬜ |
| 1.2.3 | Event Store Server has created `events` table | ⬜ |

**Validation Commands:**
```bash
docker exec syn-postgres psql -U syn -d syn -c "\dt"
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

## Feature 3b: Workflow Inputs and Task Execution (ISS-211)

### F3b.1 CLI Task Flag

**Given** a workflow with `inputs:` declarations exists (e.g., `research-workflow-v2`)
**When** I run `syn workflow run research-workflow-v2 --task "Research topic"`
**Then** the task is passed through to $ARGUMENTS substitution in prompts

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3b.1.1 | `--task` flag accepted by CLI | ⬜ |
| 3b.1.2 | Task displays in execution panel before run | ⬜ |
| 3b.1.3 | Task is included in API request body | ⬜ |
| 3b.1.4 | `--task` and `--input` flags coexist | ⬜ |

**Validation Commands:**
```bash
syn workflow run research-workflow-v2 --task "Test task" --dry-run
syn workflow run research-workflow-v2 --task "Test" --input topic=auth --dry-run
```

### F3b.2 $ARGUMENTS Substitution

**Given** a phase prompt contains `$ARGUMENTS`
**When** the workflow executes with `task="Investigate auth"`
**Then** `$ARGUMENTS` is replaced with the task string in the agent prompt

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3b.2.1 | `$ARGUMENTS` replaced with task string | ⬜ |
| 3b.2.2 | `$ARGUMENTS` and `{{variable}}` coexist in same prompt | ⬜ |
| 3b.2.3 | Missing task → `$ARGUMENTS` replaced with empty string | ⬜ |
| 3b.2.4 | Legacy `{{variable}}`-only prompts still work | ⬜ |

### F3b.3 Input Declarations in API

**Given** a workflow with `input_declarations` exists
**When** I GET `/api/v1/workflows/{id}`
**Then** the response includes `input_declarations` with name, description, required, default

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3b.3.1 | `input_declarations` array present in response | ⬜ |
| 3b.3.2 | Each declaration has name, description, required | ⬜ |
| 3b.3.3 | Workflows without declarations return `[]` | ⬜ |
| 3b.3.4 | `argument_hint` present on phase definitions | ⬜ |

**Validation Commands:**
```bash
curl -s http://localhost:8137/api/v1/workflows/research-workflow-v2 | jq '.input_declarations'
curl -s http://localhost:8137/api/v1/workflows/research-workflow-v2 | jq '.phases[0].argument_hint'
```

### F3b.4 Dashboard Task Input Form

**Given** I open the workflow detail page for a workflow with input declarations
**When** the page loads
**Then** I see a task textarea and dynamic input fields based on declarations

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 3b.4.1 | Task textarea is always visible | ⬜ |
| 3b.4.2 | Required inputs show asterisk indicator | ⬜ |
| 3b.4.3 | Default values pre-filled from declarations | ⬜ |
| 3b.4.4 | Run button disabled when required inputs missing | ⬜ |
| 3b.4.5 | Task and inputs passed to executeWorkflow API call | ⬜ |

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
curl -s http://localhost:8137/health | jq
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
curl -s http://localhost:8137/api/workflows | jq
curl -s http://localhost:8137/api/workflows?page=1&page_size=5 | jq
curl -s http://localhost:8137/api/workflows/<workflow-id> | jq
curl -s http://localhost:8137/api/workflows/invalid-id
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
curl -s http://localhost:8137/api/sessions | jq
curl -s "http://localhost:8137/api/sessions?workflow_id=<id>" | jq
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
curl -s http://localhost:8137/api/artifacts | jq
curl -s "http://localhost:8137/api/artifacts?workflow_id=<id>" | jq
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
curl -s http://localhost:8137/api/metrics | jq
curl -s "http://localhost:8137/api/metrics?workflow_id=<id>" | jq
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
curl -N http://localhost:8137/api/events/stream
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

### F5.6 Live Dashboard Updates ⭐ NEW

**Given** a workflow is running
**When** events occur during execution
**Then** the UI updates in real-time without refresh

#### F5.6.1 Live Execution Status

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.6.1.1 | ExecutionList shows "Live" connection indicator | ⬜ |
| 5.6.1.2 | New executions appear in list without refresh | ⬜ |
| 5.6.1.3 | Status badge updates (running → completed/failed) | ⬜ |
| 5.6.1.4 | Progress bar updates as phases complete | ⬜ |
| 5.6.1.5 | Token count updates as phases complete | ⬜ |

**Validation Steps:**
1. Open ExecutionList page
2. Verify "Live" indicator shows (green dot)
3. Start a workflow execution via API/CLI
4. Verify execution appears in list without refresh
5. Watch status badge change from "running" to "completed"

#### F5.6.2 Live Duration Timer

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.6.2.1 | Duration column shows elapsed time for running executions | ⬜ |
| 5.6.2.2 | Duration updates every second (watch for 5+ seconds) | ⬜ |
| 5.6.2.3 | Duration stops updating when execution completes | ⬜ |
| 5.6.2.4 | ExecutionDetail page duration also updates live | ⬜ |

**Validation Steps:**
1. Start a multi-phase workflow
2. Watch Duration column tick every second
3. Verify it stops when execution completes

#### F5.6.3 Tool Call Tracking

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.6.3.1 | Tool call count column visible in ExecutionList | ⬜ |
| 5.6.3.2 | Tool count increments as tools are used during execution | ⬜ |
| 5.6.3.3 | Final tool count matches total tools used | ⬜ |

**Validation Steps:**
1. Start a workflow that uses tools (Read, Write, etc.)
2. Watch tool count increment in real-time
3. Verify final count after completion

#### F5.6.4 Context Window Display

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.6.4.1 | ExecutionDetail shows context window percentage | ⬜ |
| 5.6.4.2 | Progress bar color changes based on usage (green → amber → red) | ⬜ |
| 5.6.4.3 | Shows token count as "X / 200,000 tokens" | ⬜ |
| 5.6.4.4 | Context percentage updates as phases complete | ⬜ |

**Validation Steps:**
1. Open ExecutionDetail for a running execution
2. Verify context window card shows percentage
3. Verify color coding: <50% green, 50-80% amber, >80% red

#### F5.6.5 Dashboard Live Metrics

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.6.5.1 | Dashboard shows "Live" connection indicator | ⬜ |
| 5.6.5.2 | Metrics refresh when workflows complete | ⬜ |
| 5.6.5.3 | Token distribution chart updates | ⬜ |

**Validation Steps:**
1. Open Dashboard page
2. Verify "Live" indicator shows
3. Complete a workflow and verify metrics update

#### F5.6.6 Live Token Streaming ⭐ NEW

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 5.6.6.1 | ExecutionDetail shows "live" indicator during execution | ⬜ |
| 5.6.6.2 | Token count updates in real-time via `turn_update` SSE events | ⬜ |
| 5.6.6.3 | Total Tokens card shows animated pulse when live | ⬜ |
| 5.6.6.4 | Input/Output token breakdown updates per turn | ⬜ |
| 5.6.6.5 | Live indicator disappears when execution completes | ⬜ |
| 5.6.6.6 | Final token counts match phase completion metrics | ⬜ |

**Validation Steps:**
1. Navigate to ExecutionDetail for a running execution
2. Watch Total Tokens card for pulsing "live" indicator
3. Observe token count incrementing as agent works
4. Verify counts stabilize when workflow completes

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
curl -s http://localhost:8137/api/workflows | jq '.total'
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

## Feature 7.5: Event Store Verification ⭐ CRITICAL

> **This feature tests the most critical invariant: all events reach the event store**

### F7.5.1 WorkflowExecutionStarted Event Persistence

**Given** I start a workflow execution via the dashboard
**When** the execution begins
**Then** `WorkflowExecutionStarted` event is in the event store

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.5.1.1 | Event exists in `events` table | ⬜ |
| 7.5.1.2 | `aggregate_type` = 'WorkflowExecution' | ⬜ |
| 7.5.1.3 | Payload contains `execution_id` | ⬜ |
| 7.5.1.4 | Payload contains `workflow_id` | ⬜ |
| 7.5.1.5 | Payload contains `total_phases` | ⬜ |

**Validation:**
```bash
# After starting a workflow
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, aggregate_id, global_nonce FROM events WHERE event_type = 'WorkflowExecutionStarted' ORDER BY global_nonce DESC LIMIT 1;"
```

### F7.5.2 PhaseCompleted Event Persistence

**Given** a phase completes during workflow execution
**When** the phase finishes successfully
**Then** `PhaseCompleted` event is in the event store with metrics

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.5.2.1 | Event exists in `events` table | ⬜ |
| 7.5.2.2 | Payload contains `phase_id` | ⬜ |
| 7.5.2.3 | Payload contains `input_tokens` > 0 | ⬜ |
| 7.5.2.4 | Payload contains `output_tokens` > 0 | ⬜ |
| 7.5.2.5 | Payload contains `duration_seconds` > 0 | ⬜ |
| 7.5.2.6 | Payload contains `cost_usd` | ⬜ |
| 7.5.2.7 | Payload contains `session_id` | ⬜ |

**Validation:**
```bash
# After a phase completes
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, convert_from(payload, 'UTF8')::json as payload FROM events WHERE event_type = 'PhaseCompleted' ORDER BY global_nonce DESC LIMIT 1;"
```

### F7.5.3 SessionStarted/Completed Event Persistence

**Given** a session runs during phase execution
**When** the session completes
**Then** both `SessionStarted` and `SessionCompleted` events exist

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.5.3.1 | `SessionStarted` event exists | ⬜ |
| 7.5.3.2 | `SessionCompleted` event exists | ⬜ |
| 7.5.3.3 | `OperationRecorded` event exists (if tokens used) | ⬜ |
| 7.5.3.4 | Session events have matching `session_id` | ⬜ |
| 7.5.3.5 | Completed event has `total_tokens` | ⬜ |

**Validation:**
```bash
# Check session events
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, aggregate_id FROM events WHERE aggregate_type = 'AgentSession' ORDER BY global_nonce;"
```

### F7.5.4 Event Store → Projection Consistency

**Given** events are in the event store
**When** I query the API
**Then** projection data matches event data

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.5.4.1 | Workflow detail reflects WorkflowExecutionStarted | ⬜ |
| 7.5.4.2 | Phase metrics reflect PhaseCompleted events | ⬜ |
| 7.5.4.3 | Session list reflects SessionStarted events | ⬜ |
| 7.5.4.4 | Session detail reflects OperationRecorded events | ⬜ |
| 7.5.4.5 | Dashboard metrics reflect all completed sessions | ⬜ |

**Validation:**
```bash
# Compare event store to API
EVENT_COUNT=$(docker exec syn-postgres psql -U syn -d syn -t -c "SELECT COUNT(*) FROM events WHERE event_type = 'SessionCompleted';")
API_COUNT=$(curl -s http://localhost:8137/api/sessions?status=completed | jq 'length')
echo "Event Store: $EVENT_COUNT, API: $API_COUNT"
```

### F7.5.5 Missing Event Detection (Regression Test)

**Given** a workflow executes end-to-end
**When** I count events by type
**Then** all expected event types are present

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.5.5.1 | WorkflowExecutionStarted count = executions started | ⬜ |
| 7.5.5.2 | PhaseCompleted count = phases completed | ⬜ |
| 7.5.5.3 | SessionStarted count = sessions started | ⬜ |
| 7.5.5.4 | SessionCompleted count = sessions completed | ⬜ |
| 7.5.5.5 | No orphan sessions (started without completed) | ⬜ |

**Validation:**
```bash
# Full event audit
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type;"
```

---

## Feature 7.6: Workflow Execution Model ⭐ NEW

> **Separates Workflow Templates from Workflow Executions (Runs)**

### Entity Model

```
┌──────────────────────────────────────────────────────────────────┐
│                     WORKFLOW EXECUTION MODEL                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   WorkflowDefinition (Template)                                   │
│   ├── id: "implementation-workflow-v1"                           │
│   ├── name: "Implementation Workflow"                            │
│   └── phases: [research, innovate, plan, execute, review]        │
│           │                                                       │
│           │ 1:N                                                   │
│           ▼                                                       │
│   WorkflowExecution (Run)                                         │
│   ├── execution_id: "exec-abc123"                                │
│   ├── workflow_id: "implementation-workflow-v1"                  │
│   ├── status: "completed"                                        │
│   ├── started_at / completed_at                                  │
│   ├── total_tokens, total_cost                                   │
│   └── phases: [{phase_id, status, tokens, cost, duration}, ...]  │
│           │                                                       │
│           │ 1:N                                                   │
│           ▼                                                       │
│   Session                                                         │
│   ├── session_id: "sess-xyz"                                     │
│   ├── execution_id: "exec-abc123"  ← Links to execution          │
│   ├── phase_id: "research"                                       │
│   └── tokens, cost, operations                                   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### F7.6.1 Workflow Runs List API

**Given** a workflow has been executed multiple times
**When** I request `/api/workflows/{id}/runs`
**Then** I get a list of all executions

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.6.1.1 | Endpoint returns 200 | ⬜ |
| 7.6.1.2 | Response includes `runs` array | ⬜ |
| 7.6.1.3 | Each run has `execution_id` | ⬜ |
| 7.6.1.4 | Each run has `status` | ⬜ |
| 7.6.1.5 | Each run has `started_at` | ⬜ |
| 7.6.1.6 | Each run has `completed_phases` / `total_phases` | ⬜ |
| 7.6.1.7 | Each run has `total_tokens` | ⬜ |
| 7.6.1.8 | Each run has `total_cost_usd` | ⬜ |
| 7.6.1.9 | Runs are ordered by `started_at` descending | ⬜ |

**Validation:**
```bash
curl -s http://localhost:8137/api/workflows/implementation-workflow-v1/runs | jq
```

### F7.6.2 Execution Detail API

**Given** a workflow execution exists
**When** I request `/api/executions/{execution_id}`
**Then** I get full execution details with phase metrics

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.6.2.1 | Endpoint returns 200 | ⬜ |
| 7.6.2.2 | Response includes `execution_id` | ⬜ |
| 7.6.2.3 | Response includes `workflow_id` | ⬜ |
| 7.6.2.4 | Response includes `status` | ⬜ |
| 7.6.2.5 | Response includes `phases` array | ⬜ |
| 7.6.2.6 | Each phase has `phase_id` and `name` | ⬜ |
| 7.6.2.7 | Each phase has `input_tokens` and `output_tokens` | ⬜ |
| 7.6.2.8 | Each phase has `duration_seconds` | ⬜ |
| 7.6.2.9 | Each phase has `cost_usd` | ⬜ |
| 7.6.2.10 | Each phase has `session_id` link | ⬜ |
| 7.6.2.11 | Response includes `artifact_ids` | ⬜ |

**Validation:**
```bash
curl -s http://localhost:8137/api/executions/<execution_id> | jq
```

### F7.6.3 Session → Execution Link

**Given** sessions are created during execution
**When** I query session detail
**Then** it includes `execution_id`

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.6.3.1 | Session response includes `execution_id` | ⬜ |
| 7.6.3.2 | Sessions can be filtered by `execution_id` | ⬜ |
| 7.6.3.3 | Session list shows execution link | ⬜ |

**Validation:**
```bash
curl -s http://localhost:8137/api/sessions/<session_id> | jq '.execution_id'
curl -s "http://localhost:8137/api/sessions?execution_id=<exec_id>" | jq
```

### F7.6.4 Workflow Template → Runs Count

**Given** a workflow has executions
**When** I request workflow detail
**Then** it shows total runs count with link

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.6.4.1 | Workflow detail includes `runs_count` | ⬜ |
| 7.6.4.2 | `runs_count` matches actual executions | ⬜ |
| 7.6.4.3 | Workflow detail includes `runs_link` | ⬜ |

**Validation:**
```bash
curl -s http://localhost:8137/api/workflows/implementation-workflow-v1 | jq '{runs_count, runs_link}'
```

### F7.6.5 UI: Workflow Runs Page

**Given** I'm on a workflow detail page
**When** I click "View Runs"
**Then** I see the runs list page

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.6.5.1 | "Runs" card shows count on template page | ⬜ |
| 7.6.5.2 | "View →" link navigates to `/workflows/{id}/runs` | ⬜ |
| 7.6.5.3 | Runs list shows all executions | ⬜ |
| 7.6.5.4 | Each run shows status badge | ⬜ |
| 7.6.5.5 | Each run shows token count and cost | ⬜ |
| 7.6.5.6 | Clicking a run navigates to execution detail | ⬜ |

### F7.6.6 UI: Execution Detail Page

**Given** I'm on the runs list
**When** I click an execution
**Then** I see the execution detail page

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 7.6.6.1 | URL is `/executions/{execution_id}` | ⬜ |
| 7.6.6.2 | Shows execution status and duration | ⬜ |
| 7.6.6.3 | Shows phase pipeline with status | ⬜ |
| 7.6.6.4 | Shows "Token Usage by Phase" chart with data | ⬜ |
| 7.6.6.5 | Shows sessions list for this execution | ⬜ |
| 7.6.6.6 | Shows artifacts generated | ⬜ |
| 7.6.6.7 | Back link returns to runs list | ⬜ |

---

## Feature 8: Agentic Workflow Execution ⭐ NEW

> **Requires:** `syn-adapters[claude-agentic]` installed

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
from syn_adapters.orchestration import AgenticWorkflowExecutor, get_agentic_agent

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
pytest packages/syn-adapters/tests/test_orchestration.py -v -k "test_executor"
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
pytest packages/syn-adapters/tests/test_orchestration.py -v -k "test_execute_simple"
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
pytest packages/syn-adapters/tests/test_orchestration.py -v -k "test_execute_multi"
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
pytest packages/syn-adapters/tests/test_orchestration.py -v -k "test_phase_failure"
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
from syn_adapters.agents import ClaudeAgenticAgent
from syn_adapters.agents.agentic_types import AgentExecutionConfig, Workspace

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
pytest packages/syn-adapters/tests/test_workspaces.py -v -k "test_local_workspace"
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
from syn_adapters.workspaces import LocalWorkspace, WorkspaceConfig
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
pytest packages/syn-adapters/tests/test_workspaces.py -v -k "test_inject"
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
pytest packages/syn-adapters/tests/test_artifacts.py -v -k "test_artifact_bundle"
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
pytest packages/syn-adapters/tests/test_artifacts.py -v -k "test_from_directory"
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
pytest packages/syn-adapters/tests/test_artifacts.py -v -k "test_serialization"
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
pytest packages/syn-adapters/tests/test_artifacts.py -v -k "test_phase_context"
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
pytest packages/syn-adapters/tests/test_events.py -v -k "test_watcher"
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
pytest packages/syn-adapters/tests/test_events.py -v -k "test_translator"
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
pytest packages/syn-adapters/tests/test_events.py -v -k "test_bridge"
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
pytest packages/syn-adapters/tests/test_orchestration.py -v -k "test_agent_factory"
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
from syn_adapters.agents import ClaudeAgenticAgent
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
from syn_adapters.agents import MockAgent

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

## Feature 13: WebSocket Control Plane ⭐ NEW

> **ADR:** [ADR-019: WebSocket Control Plane Architecture](/docs/adrs/ADR-019-websocket-control-plane.md)

### Overview

The WebSocket Control Plane enables real-time execution control:
- **Pause** running executions at yield points
- **Resume** paused executions
- **Cancel** running or paused executions
- **Inject context** into running executions (future)

### F13.1 Control Plane HTTP API

**Given** an execution is running
**When** I call control endpoints
**Then** control signals are queued

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 13.1.1 | `GET /api/executions/{id}/state` returns current state | ⬜ |
| 13.1.2 | State is one of: pending, running, paused, cancelled, completed, failed | ⬜ |
| 13.1.3 | `POST /api/executions/{id}/pause` queues pause signal | ⬜ |
| 13.1.4 | Pause returns success with "Pause signal queued" message | ⬜ |
| 13.1.5 | Pause on non-running execution returns 400 error | ⬜ |
| 13.1.6 | `POST /api/executions/{id}/resume` queues resume signal | ⬜ |
| 13.1.7 | Resume on non-paused execution returns 400 error | ⬜ |
| 13.1.8 | `POST /api/executions/{id}/cancel` queues cancel signal | ⬜ |
| 13.1.9 | Cancel on terminal execution returns 400 error | ⬜ |

**Validation Commands:**
```bash
# Get execution state
curl -s http://localhost:8137/api/executions/<execution_id>/state | jq

# Pause a running execution
curl -X POST http://localhost:8137/api/executions/<execution_id>/pause \
  -H "Content-Type: application/json" \
  -d '{"reason": "Testing pause"}' | jq

# Resume a paused execution
curl -X POST http://localhost:8137/api/executions/<execution_id>/resume | jq

# Cancel an execution
curl -X POST http://localhost:8137/api/executions/<execution_id>/cancel \
  -H "Content-Type: application/json" \
  -d '{"reason": "User cancelled"}' | jq
```

### F13.2 WebSocket Control Endpoint

**Given** I connect to the WebSocket control endpoint
**When** I send control commands
**Then** I receive real-time state updates

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 13.2.1 | WebSocket connects to `/api/ws/control/{execution_id}` | ⬜ |
| 13.2.2 | Initial message contains current state | ⬜ |
| 13.2.3 | `{"command": "pause"}` queues pause signal | ⬜ |
| 13.2.4 | `{"command": "resume"}` queues resume signal | ⬜ |
| 13.2.5 | `{"command": "cancel"}` queues cancel signal | ⬜ |
| 13.2.6 | Result messages include success/error status | ⬜ |
| 13.2.7 | Unknown commands return error type message | ⬜ |
| 13.2.8 | WebSocket stays connected for multiple commands | ⬜ |

**Validation (Browser Console):**
```javascript
const ws = new WebSocket('ws://localhost:8137/api/ws/control/exec-123');
ws.onmessage = (e) => console.log('Received:', JSON.parse(e.data));
ws.onopen = () => {
  console.log('Connected');
  ws.send(JSON.stringify({ command: 'pause', reason: 'Testing' }));
};
```

### F13.3 Executor Control Signal Integration

**Given** an executor with control signal checker configured
**When** the executor yields tool events
**Then** it checks for and handles control signals

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 13.3.1 | Executor accepts `control_signal_checker` parameter | ⬜ |
| 13.3.2 | Signal check occurs after each `TurnCompleted` event (agent turn boundary) | ⬜ |
| 13.3.3 | `ExecutionPaused` event emitted on pause signal | ⬜ |
| 13.3.4 | Execution waits (polling 500ms) while paused | ⬜ |
| 13.3.5 | `ExecutionResumed` event emitted on resume signal | ⬜ |
| 13.3.6 | Execution continues after resume | ⬜ |
| 13.3.7 | `ExecutionCancelled` event emitted on cancel signal | ⬜ |
| 13.3.8 | Execution exits phase on cancel | ⬜ |
| 13.3.9 | Cancel while paused works correctly | ⬜ |
| 13.3.10 | No signal check when checker is None | ⬜ |
| 13.3.11 | `TurnUpdate` event emitted after each turn with live token metrics | ⬜ |

**Validation (pytest):**
```bash
pytest packages/syn-adapters/tests/test_executor_control.py -v
```

### F13.4 Frontend Control UI

**Given** I'm viewing an execution detail page
**When** the execution is running or paused
**Then** I see control buttons

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 13.4.1 | Control buttons visible for running executions | ⬜ |
| 13.4.2 | Control buttons visible for paused executions | ⬜ |
| 13.4.3 | Control buttons hidden for terminal executions | ⬜ |
| 13.4.4 | Pause button visible when running | ⬜ |
| 13.4.5 | Resume button visible when paused | ⬜ |
| 13.4.6 | Cancel button visible when running or paused | ⬜ |
| 13.4.7 | Cancel shows confirmation prompt | ⬜ |
| 13.4.8 | State indicator shows current state with color | ⬜ |
| 13.4.9 | State updates in real-time via WebSocket | ⬜ |
| 13.4.10 | Connection status indicator shown | ⬜ |

**Validation Steps:**
1. Start a long-running workflow (multi-phase)
2. Navigate to execution detail page
3. Verify control buttons are visible
4. Click Pause - verify state changes to "paused"
5. Click Resume - verify execution continues
6. Start another execution
7. Click Cancel - verify confirmation, then cancellation

### F13.5 CLI Control Commands

**Given** the CLI is configured
**When** I run control commands
**Then** control signals are sent via HTTP API

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 13.5.1 | `syn control pause <id>` sends pause signal | ⬜ |
| 13.5.2 | `syn control pause <id> --reason "..."` includes reason | ⬜ |
| 13.5.3 | `syn control resume <id>` sends resume signal | ⬜ |
| 13.5.4 | `syn control cancel <id>` prompts for confirmation | ⬜ |
| 13.5.5 | `syn control cancel <id> --force` skips confirmation | ⬜ |
| 13.5.6 | `syn control status <id>` shows current state | ⬜ |
| 13.5.7 | Status shows colored output (green/yellow/red) | ⬜ |
| 13.5.8 | Error messages shown when API unavailable | ⬜ |
| 13.5.9 | `SYN_API_URL` environment variable supported | ⬜ |
| 13.5.10 | `--url` flag overrides default dashboard URL | ⬜ |

**Validation Commands:**
```bash
# Pause execution
syn control pause exec-123 --reason "Need to review"

# Resume execution
syn control resume exec-123

# Cancel with force
syn control cancel exec-123 --force --reason "Timeout"

# Check status
syn control status exec-123

# Use custom dashboard URL
SYN_API_URL=http://prod:8000 syn control status exec-123
```

### F13.6 End-to-End Control Flow ⭐ CRITICAL

**Given** a workflow is executing
**When** I pause, resume, and cancel
**Then** the entire flow works correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 13.6.1 | Start workflow via dashboard | ⬜ |
| 13.6.2 | Verify execution appears with "running" status | ⬜ |
| 13.6.3 | Click Pause in UI | ⬜ |
| 13.6.4 | Verify state changes to "paused" in UI | ⬜ |
| 13.6.5 | Verify `ExecutionPaused` event in SSE stream | ⬜ |
| 13.6.6 | Verify execution duration timer stops | ⬜ |
| 13.6.7 | Click Resume in UI | ⬜ |
| 13.6.8 | Verify state changes back to "running" | ⬜ |
| 13.6.9 | Verify `ExecutionResumed` event in SSE stream | ⬜ |
| 13.6.10 | Verify duration timer resumes | ⬜ |
| 13.6.11 | Start new execution | ⬜ |
| 13.6.12 | Click Cancel in UI | ⬜ |
| 13.6.13 | Confirm cancellation | ⬜ |
| 13.6.14 | Verify `ExecutionCancelled` event | ⬜ |
| 13.6.15 | Verify execution ends cleanly | ⬜ |

**Browser Automation Test:**
```javascript
// Example Playwright test
test('execution control flow', async ({ page }) => {
  // Start workflow
  await page.goto('http://localhost:5173/workflows');
  await page.click('[data-testid="execute-workflow"]');

  // Wait for running state
  await expect(page.locator('[data-testid="status-badge"]'))
    .toHaveText('running');

  // Pause
  await page.click('[data-testid="pause-button"]');
  await expect(page.locator('[data-testid="status-badge"]'))
    .toHaveText('paused');

  // Resume
  await page.click('[data-testid="resume-button"]');
  await expect(page.locator('[data-testid="status-badge"]'))
    .toHaveText('running');

  // Cancel
  await page.click('[data-testid="cancel-button"]');
  await page.click('[data-testid="confirm-cancel"]');
  await expect(page.locator('[data-testid="status-badge"]'))
    .toContainText(/cancelled|completed/);
});
```

---

## Feature 14: Isolated Workspace Architecture ⭐ NEW

> **ADR:** [ADR-021: Isolated Workspace Architecture](/docs/adrs/ADR-021-isolated-workspace-architecture.md)

### Overview

All agent workspaces run in isolated containers/VMs. This feature tests:
- Workspace creation with isolation backends
- Git identity injection
- API key injection
- Container logging with secret redaction
- Network allowlist enforcement
- Dashboard workspace info display

### F14.1 WorkspaceService & Backend Selection

**Given** the system is configured
**When** I create a workspace via WorkspaceService
**Then** the best available backend is selected

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.1.1 | WorkspaceService creates workspace with available backend | ⬜ |
| 14.1.2 | At least one backend available (docker_hardened fallback) | ⬜ |
| 14.1.3 | get_best_backend() returns highest priority available | ⬜ |
| 14.1.4 | WorkspaceCreating event emitted before creation | ⬜ |
| 14.1.5 | WorkspaceCreated event emitted after creation | ⬜ |
| 14.1.6 | Workspace has isolation_id (container/vm/sandbox ID) | ⬜ |
| 14.1.7 | Workspace can execute commands | ⬜ |
| 14.1.8 | WorkspaceDestroyed event emitted on cleanup | ⬜ |

**Validation Commands:**
```bash
# Check available backends
uv run python -m syn_perf check

# Run workspace router tests
uv run pytest packages/syn-adapters/tests/test_workspace_router.py -v
```

### F14.2 Git Identity Injection

**Given** SYN_GIT_* environment variables are set
**When** a workspace is created
**Then** git identity is configured inside the container

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.2.1 | GitIdentitySettings reads from SYN_GIT_* env vars | ⬜ |
| 14.2.2 | GitIdentityResolver follows precedence: workflow > env > local | ⬜ |
| 14.2.3 | git config user.name set in container | ⬜ |
| 14.2.4 | git config user.email set in container | ⬜ |
| 14.2.5 | HTTPS credentials stored in ~/.git-credentials | ⬜ |
| 14.2.6 | Git clone works inside container | ⬜ |
| 14.2.7 | Git commit has correct author | ⬜ |

**Validation Commands:**
```bash
# Run POC test
just poc-git-identity

# Expected output:
# Author: syn-bot[bot] <bot@syn137.dev>
# ✓ Git identity injection successful!
```

### F14.3 API Key Injection

**Given** ANTHROPIC_API_KEY is set
**When** a workspace is created
**Then** API keys are available inside the container

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.3.1 | EnvInjector detects configured API keys | ⬜ |
| 14.3.2 | ANTHROPIC_API_KEY written to ~/.bashrc | ⬜ |
| 14.3.3 | OPENAI_API_KEY written if configured | ⬜ |
| 14.3.4 | Python can import anthropic SDK in container | ⬜ |
| 14.3.5 | Claude API call succeeds from container | ⬜ |

**Validation Commands:**
```bash
# Set API key and run POC
export ANTHROPIC_API_KEY=sk-ant-xxx
just poc-claude-api

# Expected output:
# Claude API test response: ...
# ✓ Claude API works from container!
```

### F14.4 Container Logging

**Given** logging is configured
**When** agent executes commands
**Then** structured logs are written with secret redaction

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.4.1 | Log directory /workspace/.logs created | ⬜ |
| 14.4.2 | agent.jsonl file created | ⬜ |
| 14.4.3 | LogEntry has timestamp, level, message, event_type | ⬜ |
| 14.4.4 | Command logs include exit_code and duration_ms | ⬜ |
| 14.4.5 | Error logs include exception_type and exception_message | ⬜ |
| 14.4.6 | Secrets are redacted (API keys, tokens) | ⬜ |
| 14.4.7 | ContainerLogStreamer can read logs from outside | ⬜ |
| 14.4.8 | ViewContainerLogsTool works for inner agent | ⬜ |

**Validation Commands:**
```bash
# Run POC test
just poc-logging

# Expected output:
# {"timestamp":"...","level":"INFO","message":"Agent started",...}
# ✓ Container logging works!
```

### F14.5 Network Allowlist (Egress Proxy)

**Given** egress proxy is running
**When** container makes outbound requests
**Then** only allowed hosts succeed

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.5.1 | Egress proxy image builds successfully | ⬜ |
| 14.5.2 | Proxy starts on port 8080 | ⬜ |
| 14.5.3 | AllowlistAddon loads from ALLOWED_HOSTS | ⬜ |
| 14.5.4 | Request to allowed host (github.com) returns 200 | ⬜ |
| 14.5.5 | Request to blocked host (evil.com) returns 403 | ⬜ |
| 14.5.6 | Wildcard patterns work (*.github.com) | ⬜ |
| 14.5.7 | Blocked requests logged for audit | ⬜ |
| 14.5.8 | Container proxy env vars set automatically | ⬜ |

**Validation Commands:**
```bash
# Build and test proxy
just proxy-build
just poc-allowlist

# Expected output:
# 2. Testing ALLOWED host (github.com)...
# 200 <- Expected: 200
# 3. Testing BLOCKED host (evil.com)...
# 403 <- Expected: 403
# ✓ Network allowlist test complete!
```

### F14.6 Orchestration Integration

**Given** get_workspace() is called
**When** agent executes via executor
**Then** isolated workspace is used

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.6.1 | get_workspace() returns isolated workspace | ⬜ |
| 14.6.2 | Workspace has _router reference | ⬜ |
| 14.6.3 | execute_in_workspace() works correctly | ⬜ |
| 14.6.4 | LocalWorkspace raises error in production | ⬜ |
| 14.6.5 | get_workspace_local() explicitly available for dev/test | ⬜ |

**Validation Commands:**
```bash
# Run orchestration factory tests
uv run pytest packages/syn-adapters/tests/test_orchestration_factory.py -v
```

### F14.7 Dashboard Workspace Display

**Given** an execution has a workspace
**When** I view the execution detail page
**Then** I see workspace information

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.7.1 | ExecutionDetail includes WorkspaceInfoCard | ⬜ |
| 14.7.2 | Card shows isolation backend (Docker, gVisor, etc.) | ⬜ |
| 14.7.3 | Card shows container/VM/sandbox ID | ⬜ |
| 14.7.4 | Card shows status (creating/running/stopped/error) | ⬜ |
| 14.7.5 | Card shows memory usage | ⬜ |
| 14.7.6 | Card shows CPU time | ⬜ |
| 14.7.7 | Card shows commands executed count | ⬜ |
| 14.7.8 | Workspace events refresh UI via WebSocket | ⬜ |

**Validation Steps:**
1. Start a workflow execution
2. Navigate to execution detail page
3. Verify WorkspaceInfoCard appears
4. Verify isolation backend and container ID shown
5. Watch for status updates as execution progresses

### F14.8 End-to-End Isolated Execution ⭐ CRITICAL

**Given** all components are configured
**When** I execute a workflow that clones, modifies, and commits
**Then** the entire flow works in isolation

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.8.1 | Workspace created with Docker/gVisor backend | ⬜ |
| 14.8.2 | Git identity injected (commit author correct) | ⬜ |
| 14.8.3 | API key available (Claude calls work) | ⬜ |
| 14.8.4 | Commands logged to /workspace/.logs/agent.jsonl | ⬜ |
| 14.8.5 | Network restricted to allowed hosts | ⬜ |
| 14.8.6 | Workspace destroyed on completion | ⬜ |
| 14.8.7 | Dashboard shows workspace info during execution | ⬜ |
| 14.8.8 | All 95+ unit tests pass | ⬜ |

**Validation Commands:**
```bash
# Run all POC tests
just poc-git-identity
just poc-logging
just poc-allowlist

# Run full test suite
uv run pytest packages/syn-adapters/tests/workspaces/ \
  packages/syn-adapters/tests/test_orchestration_factory.py \
  packages/syn-shared/tests/test_workspace_settings.py -v

# Expected: 95+ tests pass
```

### F14.9 Performance Benchmarks

**Given** the isolated workspace system is running
**When** I run benchmarks
**Then** performance meets targets

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.9.1 | Container create time < 500ms | ⬜ |
| 14.9.2 | Parallel speedup > 9x for 10 containers | ⬜ |
| 14.9.3 | Throughput > 3 workspaces/min | ⬜ |
| 14.9.4 | Memory overhead < 100MB per container | ⬜ |

**Validation Commands:**
```bash
# Quick performance check
just perf-check

# Full benchmark suite
just perf-all

# Expected output:
# Create Time:  ~170ms
# Speedup (10x): ~9.5x
# Throughput:    ~5 workspaces/min
```

---

## Feature 15: GitHub App & Secure Token Architecture ⭐ NEW

> **ADR:** [ADR-022: Secure Token Architecture](/docs/adrs/ADR-022-secure-token-architecture.md)
> **Docs:** [GitHub App Security](/docs/deployment/github-app-security.md), [Claude API Security](/docs/deployment/claude-api-security.md)

### Overview

Secure token management for agentic operations at scale:
- GitHub App authentication (JWT → Installation Token)
- Token Vending Service (short-lived, scoped tokens)
- Spend Tracker (budget allocation, usage limits)
- Sidecar Proxy (token injection, audit trail)

### Prerequisites

```bash
# GitHub App environment variables
export SYN_GITHUB_APP_ID=2461312
export SYN_GITHUB_APP_NAME=aef-engineer-beta
export SYN_GITHUB_PRIVATE_KEY=$(cat path/to/private-key.pem | base64)

# Verify configuration
just cli config show | grep GITHUB
```

### F15.1 GitHub App Authentication

**Given** GitHub App credentials are configured
**When** I authenticate with the GitHub App
**Then** I get a valid installation token

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 15.1.1 | GitHubAppSettings reads from SYN_GITHUB_* env vars | ⬜ |
| 15.1.2 | Private key is base64 decoded correctly | ⬜ |
| 15.1.3 | JWT generated with correct claims (iss, iat, exp) | ⬜ |
| 15.1.4 | JWT expires in 10 minutes | ⬜ |
| 15.1.5 | Installation token obtained via GitHub API | ⬜ |
| 15.1.6 | Installation token has 1-hour TTL | ⬜ |
| 15.1.7 | Token cached until 5 min before expiry | ⬜ |
| 15.1.8 | Bot username is `{app_name}[bot]` | ⬜ |

**Validation Commands:**
```bash
# Run GitHub App client tests
uv run pytest packages/syn-adapters/tests/github/test_client.py -v

# Manual verification
uv run python scripts/e2e_github_app_test.py
```

### F15.2 Token Vending Service

**Given** TokenVendingService is initialized
**When** I vend tokens for an execution
**Then** tokens are scoped and short-lived

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 15.2.1 | TokenVendingService accepts in-memory or Redis store | ⬜ |
| 15.2.2 | vend_token() generates unique token ID | ⬜ |
| 15.2.3 | Token has 5-minute default TTL | ⬜ |
| 15.2.4 | Token scope includes allowed_apis, allowed_repos | ⬜ |
| 15.2.5 | Token scope includes max_cost_usd limit | ⬜ |
| 15.2.6 | validate_token() returns (True, None) for valid tokens | ⬜ |
| 15.2.7 | validate_token() returns (False, reason) for expired | ⬜ |
| 15.2.8 | revoke_token() deletes single token | ⬜ |
| 15.2.9 | revoke_tokens(execution_id) deletes all for execution | ⬜ |
| 15.2.10 | get_active_tokens() lists non-expired tokens | ⬜ |

**Validation Commands:**
```bash
# Run token vending tests
uv run pytest packages/syn-tokens/tests/test_vending.py -v
```

### F15.3 Spend Tracker

**Given** SpendTracker is initialized
**When** I allocate and track budget
**Then** usage is monitored with alerts

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 15.3.1 | allocate_budget() creates budget for workflow type | ⬜ |
| 15.3.2 | Research budget: 100k input, 50k output, $10 | ⬜ |
| 15.3.3 | Implementation budget: 500k input, 200k output, $50 | ⬜ |
| 15.3.4 | Review budget: 50k input, 20k output, $5 | ⬜ |
| 15.3.5 | Quick Fix budget: 10k input, 5k output, $1 | ⬜ |
| 15.3.6 | check_budget() returns allowed=True within limits | ⬜ |
| 15.3.7 | check_budget() returns allowed=False when exhausted | ⬜ |
| 15.3.8 | record_usage() updates used_input_tokens | ⬜ |
| 15.3.9 | record_usage() updates used_output_tokens | ⬜ |
| 15.3.10 | record_usage() calculates cost_usd correctly | ⬜ |
| 15.3.11 | Alert at 80% usage (warning threshold) | ⬜ |
| 15.3.12 | Alert at 95% usage (critical threshold) | ⬜ |
| 15.3.13 | release_budget() cleans up after execution | ⬜ |
| 15.3.14 | get_usage_summary() returns detailed stats | ⬜ |

**Validation Commands:**
```bash
# Run spend tracker tests
uv run pytest packages/syn-tokens/tests/test_spend.py -v
```

### F15.4 Git Credential Injection via GitHub App

**Given** GitHub App is configured
**When** workspace is created
**Then** Git credentials are injected for bot identity

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 15.4.1 | _inject_github_app_credentials() fetches installation token | ⬜ |
| 15.4.2 | Token written to ~/.git-credentials | ⬜ |
| 15.4.3 | Credential format: `https://x-access-token:TOKEN@github.com` | ⬜ |
| 15.4.4 | git config credential.helper set to "store" | ⬜ |
| 15.4.5 | git clone works with injected credentials | ⬜ |
| 15.4.6 | git push works with injected credentials | ⬜ |
| 15.4.7 | Commits attributed to `{app_name}[bot]` | ⬜ |

**Validation Commands:**
```bash
# Run git injection tests
uv run pytest packages/syn-adapters/tests/workspaces/test_git.py -v
```

### F15.5 Sidecar Proxy Configuration

**Given** Envoy sidecar is configured
**When** agent makes outbound requests
**Then** tokens are injected and requests logged

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 15.5.1 | Envoy config routes api.anthropic.com | ⬜ |
| 15.5.2 | Envoy config routes api.github.com | ⬜ |
| 15.5.3 | Envoy config routes raw.githubusercontent.com | ⬜ |
| 15.5.4 | All other hosts blocked with 403 | ⬜ |
| 15.5.5 | ext_authz filter configured for token injection | ⬜ |
| 15.5.6 | JSON access logs include execution_id | ⬜ |
| 15.5.7 | Rate limiter: 100 tokens, 10/s refill | ⬜ |
| 15.5.8 | token_injector.py injects x-api-key for Anthropic | ⬜ |
| 15.5.9 | token_injector.py injects Bearer for GitHub | ⬜ |

**Validation Commands:**
```bash
# Build sidecar
docker build -t syn137-sidecar:latest docker/sidecar-proxy/

# Start with profile
docker compose -f docker/docker-compose.dev.yaml --profile sidecar up -d
```

### F15.6 E2E: Full Stack with Secure Tokens ⭐ CRITICAL

**Given** full stack is running (Docker + Event Store + Dashboard)
**When** I execute a workflow with GitHub App
**Then** events flow through the system correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 15.6.1 | Start Docker stack with `just dev` | ⬜ |
| 15.6.2 | Event Store healthy on localhost:50051 | ⬜ |
| 15.6.3 | Dashboard API healthy on localhost:8137 | ⬜ |
| 15.6.4 | GitHub App configured (SYN_GITHUB_* vars) | ⬜ |
| 15.6.5 | Execute workflow via CLI or API | ⬜ |
| 15.6.6 | WorkflowExecutionStarted event in Event Store | ⬜ |
| 15.6.7 | Spend budget allocated for execution | ⬜ |
| 15.6.8 | Scoped token vended for execution | ⬜ |
| 15.6.9 | GitHub App token obtained (1-hour TTL) | ⬜ |
| 15.6.10 | Agent clones repo via bot credentials | ⬜ |
| 15.6.11 | Agent makes code changes | ⬜ |
| 15.6.12 | Agent commits with bot author | ⬜ |
| 15.6.13 | Agent pushes to remote | ⬜ |
| 15.6.14 | PhaseCompleted events in Event Store | ⬜ |
| 15.6.15 | WorkflowCompleted event in Event Store | ⬜ |
| 15.6.16 | Token usage recorded in spend tracker | ⬜ |
| 15.6.17 | Tokens revoked after execution completes | ⬜ |
| 15.6.18 | Budget released after execution | ⬜ |
| 15.6.19 | Dashboard shows execution with correct status | ⬜ |
| 15.6.20 | Dashboard shows token usage metrics | ⬜ |

**Validation Commands:**
```bash
# Full stack startup
just dev
sleep 30  # Wait for services

# Verify all healthy
docker ps --format "table {{.Names}}\t{{.Status}}"
curl -s http://localhost:8137/health | jq

# Run full e2e test
uv run python scripts/e2e_github_app_test.py

# Verify events in store
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type;"
```

---

## Feature 16: Workspace-First Execution Architecture ⭐ NEW

> **ADR:** [ADR-023: Workspace-First Execution Model](/docs/adrs/ADR-023-workspace-first-execution-model.md)
> **Plan:** [Full Workspace Isolation Plan](/docs/PLAN-FULL-WORKSPACE-ISOLATION.md)

### Overview

Enforces that all agent execution flows through isolated workspaces:
- `LocalWorkspace` and `InMemoryWorkspace` are TEST ONLY
- `WorkspaceRouter` required for development/production
- `WorkflowExecutionEngine` requires DI for `WorkspaceRouter` and `WorkflowExecutionRepository`
- `AgentExecutor` abstraction for running agents in isolation

### F16.1 LocalWorkspace Test-Only Enforcement

**Given** `APP_ENVIRONMENT` is not `test`
**When** I try to create a LocalWorkspace
**Then** it raises `NonIsolatedWorkspaceError`

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 16.1.1 | LocalWorkspace works in `test` environment | ⬜ |
| 16.1.2 | LocalWorkspace works in `testing` environment | ⬜ |
| 16.1.3 | LocalWorkspace raises error in `development` | ⬜ |
| 16.1.4 | LocalWorkspace raises error in `production` | ⬜ |
| 16.1.5 | Error message references WorkspaceService | ⬜ |
| 16.1.6 | Error message references ADR-023 | ⬜ |

**Validation Commands:**
```bash
# Should PASS (test environment)
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/tests/workspaces/test_environment_enforcement.py -v -k "local"

# Should FAIL if you manually test in dev
APP_ENVIRONMENT=development python -c "from syn_adapters.workspaces import LocalWorkspace"
```

### F16.2 InMemoryWorkspace Test-Only Enforcement

**Given** `APP_ENVIRONMENT` is not `test`
**When** I try to create an InMemoryWorkspace
**Then** it raises `TestEnvironmentRequiredError`

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 16.2.1 | InMemoryWorkspace works in `test` environment | ⬜ |
| 16.2.2 | InMemoryWorkspace raises error in `development` | ⬜ |
| 16.2.3 | File operations work in memory (no disk) | ⬜ |
| 16.2.4 | Command execution is mocked | ⬜ |
| 16.2.5 | Artifact collection works correctly | ⬜ |

**Validation Commands:**
```bash
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/tests/workspaces/test_environment_enforcement.py -v -k "inmemory"
```

### F16.3 WorkspaceService Enforcement

**Given** no isolated backend is available
**When** I call `get_best_backend()` in non-test environment
**Then** it raises `RuntimeError` with install instructions

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 16.3.1 | Returns backend when Docker available | ⬜ |
| 16.3.2 | Returns backend when gVisor available | ⬜ |
| 16.3.3 | Returns None in test env if no backend | ⬜ |
| 16.3.4 | Raises RuntimeError in dev if no backend | ⬜ |
| 16.3.5 | Error includes Docker install instructions | ⬜ |
| 16.3.6 | Error includes E2B config instructions | ⬜ |
| 16.3.7 | Router creates InMemoryWorkspace in test fallback | ⬜ |

**Validation Commands:**
```bash
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/tests/workspaces/test_environment_enforcement.py -v -k "router"
```

### F16.4 WorkflowExecutionEngine Required Dependencies

**Given** I create a WorkflowExecutionEngine
**When** `execution_repository` or `workspace_service` is None
**Then** it raises `ValueError` immediately

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 16.4.1 | Engine requires `execution_repository` (not None) | ⬜ |
| 16.4.2 | Engine requires `workspace_service` (not None) | ⬜ |
| 16.4.3 | ValueError references ADR-023 | ⬜ |
| 16.4.4 | Engine works with both dependencies provided | ⬜ |
| 16.4.5 | Engine saves aggregate after each phase | ⬜ |
| 16.4.6 | Events emitted via aggregate commands | ⬜ |

**Validation Commands:**
```bash
APP_ENVIRONMENT=test uv run pytest packages/syn-domain/tests/contexts/workflows/execute_workflow/ -v
```

### F16.5 AgentExecutor Protocol

**Given** I have an isolated workspace
**When** I execute a task via AgentExecutor
**Then** events stream correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 16.5.1 | AgentExecutor protocol defined | ⬜ |
| 16.5.2 | ClaudeAgentExecutor implements protocol | ⬜ |
| 16.5.3 | ExecutionStarted event emitted | ⬜ |
| 16.5.4 | ExecutionProgress events stream | ⬜ |
| 16.5.5 | ExecutionOutput events stream | ⬜ |
| 16.5.6 | ExecutionToolUse events stream | ⬜ |
| 16.5.7 | ExecutionCompleted event with result | ⬜ |
| 16.5.8 | WorkspaceExecutionResult contains metrics | ⬜ |
| 16.5.9 | get_claude_executor() factory works | ⬜ |
| 16.5.10 | AgentNotAvailableError if no API key | ⬜ |

**Validation Commands:**
```bash
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/tests/agents/test_executor.py -v
```

### F16.6 Full Enforcement Test Suite

**Given** all enforcement rules are in place
**When** I run the full test suite
**Then** all 40+ tests pass

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 16.6.1 | LocalWorkspace enforcement tests pass (6 tests) | ⬜ |
| 16.6.2 | InMemoryWorkspace enforcement tests pass (4 tests) | ⬜ |
| 16.6.3 | WorkspaceService enforcement tests pass (4 tests) | ⬜ |
| 16.6.4 | InMemoryWorkspace integration tests pass (2 tests) | ⬜ |
| 16.6.5 | AgentExecutor tests pass (15 tests) | ⬜ |
| 16.6.6 | WorkflowExecutionEngine DI tests pass (3 tests) | ⬜ |
| 16.6.7 | WorkflowExecutionEngine execution tests pass (17 tests) | ⬜ |
| 16.6.8 | All syn-domain tests pass (183+ tests) | ⬜ |
| 16.6.9 | All workspace tests pass (95+ tests) | ⬜ |

**Validation Commands:**
```bash
# Run all enforcement tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/tests/workspaces/test_environment_enforcement.py -v

# Run all executor tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/tests/agents/test_executor.py -v

# Run all workflow engine tests
APP_ENVIRONMENT=test uv run pytest packages/syn-domain/tests/contexts/workflows/execute_workflow/ -v

# Full domain test suite
APP_ENVIRONMENT=test uv run pytest packages/syn-domain/ -v --tb=short
```

---

## Feature 17: Container Execution Robustness ⭐ NEW

> **Project Plan:** `PROJECT-PLAN_20251214_container-execution-fixes.md`
> **ADRs:** ADR-021 (Isolated Workspaces), ADR-022 (Secure Tokens), ADR-023 (Workspace-First)

### Overview

Tests for the "agent-in-container" execution model robustness:
- Phase counting accuracy (no duplicates)
- Artifact collection from correct paths
- Session persistence and UI visibility
- Git attribution control
- Analytics streaming from hooks
- Stale execution cleanup

### F17.1 Phase Counting Accuracy ⭐ P0

**Given** a workflow executes in container mode
**When** phases complete
**Then** exactly one result per phase is recorded

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.1.1 | Single-phase workflow shows `completed_phases = 1` | ⬜ |
| 17.1.2 | Multi-phase workflow shows correct completed count | ⬜ |
| 17.1.3 | PhaseCompleted event count equals phase count | ⬜ |
| 17.1.4 | phase_results array length equals phase count | ⬜ |
| 17.1.5 | No duplicate PhaseCompleted events per phase | ⬜ |
| 17.1.6 | UI execution detail shows correct phase count | ⬜ |

**Validation Commands:**
```bash
# Run single-phase workflow
syn workflow run --container --workflow water-lightyear-calc

# Verify via API
curl -s http://localhost:8137/api/executions/<exec_id> | jq '{completed_phases, total_phases}'

# Verify event count in Event Store
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT COUNT(*) FROM events WHERE event_type = 'PhaseCompleted' AND aggregate_id = '<exec_id>';"
```

### F17.2 Artifact Collection ⭐ P0

**Given** an agent writes files in container
**When** execution completes
**Then** artifacts are collected from the correct directory

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.2.1 | Agent writes to `/workspace/artifacts` | ⬜ |
| 17.2.2 | `collect_artifacts()` reads from `/workspace/artifacts` | ⬜ |
| 17.2.3 | ArtifactCreated events emitted | ⬜ |
| 17.2.4 | Artifacts visible in execution detail API | ⬜ |
| 17.2.5 | Artifacts visible in UI execution detail | ⬜ |
| 17.2.6 | Type-safe workspace_paths module used | ⬜ |

**Validation Commands:**
```bash
# After workflow completes
curl -s http://localhost:8137/api/executions/<exec_id>/artifacts | jq

# Verify path constants
python -c "from syn_shared.workspace_paths import WORKSPACE_OUTPUT_DIR; print(WORKSPACE_OUTPUT_DIR)"
```

### F17.3 Session Persistence ⭐ P1

**Given** a phase executes in container
**When** the phase starts and completes
**Then** AgentSession aggregate events are emitted

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.3.1 | SessionStarted event emitted on phase start | ⬜ |
| 17.3.2 | SessionStarted includes workflow_id, execution_id, phase_id | ⬜ |
| 17.3.3 | SessionCompleted event emitted on phase complete | ⬜ |
| 17.3.4 | SessionCompleted has success=true for success | ⬜ |
| 17.3.5 | SessionCompleted has success=false, error_message for failure | ⬜ |
| 17.3.6 | Session visible in `/api/sessions` list | ⬜ |
| 17.3.7 | Session visible in UI sessions page | ⬜ |
| 17.3.8 | Session links to execution in UI | ⬜ |

**Validation Commands:**
```bash
# After workflow
curl -s "http://localhost:8137/api/sessions?execution_id=<exec_id>" | jq

# Event store verification
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, convert_from(payload, 'UTF8')::json->>'phase_id' as phase_id \
   FROM events WHERE aggregate_type = 'AgentSession' ORDER BY global_nonce DESC LIMIT 5;"
```

### F17.4 Git Attribution Control ⭐ P1

**Given** Claude SDK is configured with attribution settings
**When** agent commits code
**Then** no `Co-Authored-By: Claude` trailer appears

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.4.1 | settings.json includes `attribution.commits = false` | ⬜ |
| 17.4.2 | settings.json includes `attribution.pullRequests = false` | ⬜ |
| 17.4.3 | Settings copied from agentic-primitives | ⬜ |
| 17.4.4 | Commit in workflow has no Co-Authored-By trailer | ⬜ |
| 17.4.5 | PR description has no Claude attribution | ⬜ |

**Validation Commands:**
```bash
# After workflow creates PR
cd /path/to/sandbox-repo
git log -1 --format="%B"  # Should NOT contain Co-Authored-By

# Check settings in container
docker exec <container_id> cat /workspace/.claude/settings.json | jq '.attribution'
```

### F17.5 Real-Time Analytics Streaming ⭐ P2

**Given** hooks fire during agent execution
**When** events are written to analytics JSONL
**Then** events are streamed to control plane in real-time

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.5.1 | Hooks write to `.agentic/analytics/events.jsonl` | ⬜ |
| 17.5.2 | Analytics file watcher detects new lines | ⬜ |
| 17.5.3 | Events streamed to stdout with type="analytics" | ⬜ |
| 17.5.4 | Events visible in SSE stream | ⬜ |
| 17.5.5 | Events include session correlation data | ⬜ |
| 17.5.6 | Token usage updates in real-time in UI | ⬜ |

**Validation Commands:**
```bash
# During workflow execution
docker exec <container_id> tail -f /workspace/.agentic/analytics/events.jsonl

# Watch SSE stream for analytics events
curl -N http://localhost:8137/api/events/stream | grep analytics
```

### F17.6 Stale Execution Cleanup ⭐ P2

**Given** an execution is stuck in "running" state
**When** the cleanup job runs
**Then** stale executions are marked as failed

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.6.1 | Executions past TTL detected by cleanup query | ⬜ |
| 17.6.2 | Stale executions marked as "failed" | ⬜ |
| 17.6.3 | WorkflowFailed event emitted with reason="stale_timeout" | ⬜ |
| 17.6.4 | Non-stale executions unaffected | ⬜ |
| 17.6.5 | Cleanup API endpoint works | ⬜ |
| 17.6.6 | Cleanup CLI command works | ⬜ |
| 17.6.7 | Container crash triggers session failure | ⬜ |

**Validation Commands:**
```bash
# Run cleanup via API
curl -X POST http://localhost:8137/api/executions/cleanup \
  -H "Content-Type: application/json" \
  -d '{"threshold_hours": 2}'

# Run cleanup via CLI
syn execution cleanup --threshold 2h

# Verify stale executions marked failed
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, convert_from(payload, 'UTF8')::json->>'reason' \
   FROM events WHERE event_type = 'WorkflowFailed' ORDER BY global_nonce DESC LIMIT 5;"
```

### F17.7 Type-Safe Workspace Paths ⭐ P0

**Given** workspace paths are defined in syn_shared
**When** agent-runner and adapters import them
**Then** paths are consistent and type-safe

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.7.1 | `WORKSPACE_ROOT = /workspace` | ⬜ |
| 17.7.2 | `WORKSPACE_OUTPUT_DIR = /workspace/artifacts` | ⬜ |
| 17.7.3 | `WORKSPACE_CONTEXT_DIR = /workspace/.context` | ⬜ |
| 17.7.4 | `WORKSPACE_TASK_FILE = /workspace/.context/task.json` | ⬜ |
| 17.7.5 | `WORKSPACE_ANALYTICS_DIR = /workspace/.agentic/analytics` | ⬜ |
| 17.7.6 | All paths are `PurePosixPath` type | ⬜ |
| 17.7.7 | agentic_events available in container (ADR-029) | ⬜ |
| 17.7.8 | syn-adapters imports from syn_shared | ⬜ |
| 17.7.9 | Type checking passes (mypy/pyright) | ⬜ |

**Validation Commands:**
```bash
# Verify constants
python -c "
from syn_shared.workspace_paths import *
print(f'ROOT: {WORKSPACE_ROOT}')
print(f'OUTPUT: {WORKSPACE_OUTPUT_DIR}')
print(f'CONTEXT: {WORKSPACE_CONTEXT_DIR}')
print(f'TASK: {WORKSPACE_TASK_FILE}')
"

# Type check
cd packages/syn-shared && uv run mypy src/
cd packages/syn-domain && uv run mypy src/
```

### F17.8 End-to-End Container Execution ⭐ CRITICAL

**Given** full Syn137 stack is running
**When** I execute a container workflow
**Then** all F17 criteria are met

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 17.8.1 | Workflow starts via CLI or API | ⬜ |
| 17.8.2 | Container created with isolation | ⬜ |
| 17.8.3 | Agent clones repo successfully | ⬜ |
| 17.8.4 | Agent creates/modifies files | ⬜ |
| 17.8.5 | Agent commits with correct author | ⬜ |
| 17.8.6 | No Co-Authored-By trailer in commit | ⬜ |
| 17.8.7 | Agent opens PR | ⬜ |
| 17.8.8 | Exactly 1 phase result per phase | ⬜ |
| 17.8.9 | Artifacts collected and visible | ⬜ |
| 17.8.10 | Session visible in UI | ⬜ |
| 17.8.11 | Token usage tracked | ⬜ |
| 17.8.12 | Execution completes successfully | ⬜ |
| 17.8.13 | WorkflowCompleted event in store | ⬜ |

**Validation Commands:**
```bash
# Full E2E test
just dev  # Start stack
sleep 30  # Wait for services

# Execute workflow
syn workflow run --container --workflow water-lightyear-calc \
  --input '{"task": "Calculate H2O molecule count in light-year line"}'

# Verify all criteria
curl -s http://localhost:8137/api/executions/<exec_id> | jq

# Check events
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, COUNT(*) FROM events WHERE aggregate_id = '<exec_id>' GROUP BY event_type;"
```

### F17 Test Results Summary

| # | Sub-Feature | Criteria | Priority |
|---|-------------|----------|----------|
| 17.1 | Phase Counting Accuracy | 6 | P0 |
| 17.2 | Artifact Collection | 6 | P0 |
| 17.3 | Session Persistence | 8 | P1 |
| 17.4 | Git Attribution Control | 5 | P1 |
| 17.5 | Real-Time Analytics | 6 | P2 |
| 17.6 | Stale Execution Cleanup | 7 | P2 |
| 17.7 | Type-Safe Workspace Paths | 9 | P0 |
| 17.8 | E2E Container Execution | 13 | P0 |
| **TOTAL** | | **60** | |

---

## Feature 18: WorkspaceService Architecture ⭐ NEW

> **ADRs:** ADR-021 (Isolated Workspaces), ADR-022 (Secure Tokens), ADR-023 (Workspace-First)
> **Architecture:** Event-sourced, VSA-compliant, DI-first workspace domain

### Overview

Tests for the new `WorkspaceService` architecture that replaces the deprecated `WorkspaceRouter`:

```
WorkspaceService.create_workspace()
    ├── IsolationBackendPort (Docker/Memory)
    ├── SidecarPort (Token injection proxy)
    ├── TokenInjectionPort (Scoped token vending)
    └── EventStreamPort (Real-time output streaming)
```

**Key Components:**
- `WorkspaceAggregate` - Event-sourced aggregate with full audit trail
- `WorkspaceService` - Unified facade for lifecycle management
- `ManagedWorkspace` - Context manager with inject/execute/stream/collect operations
- Port interfaces - `IsolationBackendPort`, `SidecarPort`, `TokenInjectionPort`, `EventStreamPort`

### F18.1 WorkspaceService Factory Methods

**Given** the application needs a workspace service
**When** I call factory methods
**Then** the correct service is created

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.1.1 | `WorkspaceService.create_docker()` returns service with Docker adapter | ⬜ |
| 18.1.2 | `WorkspaceService.create_memory()` returns service with Memory adapter | ⬜ |
| 18.1.3 | Memory service only works in `APP_ENVIRONMENT=test` | ⬜ |
| 18.1.4 | Docker service includes sidecar and event stream adapters | ⬜ |
| 18.1.5 | Service accepts custom token vending service | ⬜ |

**Validation Commands:**
```bash
# Run factory tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_workspace_service.py -v -k "factory"
```

### F18.2 WorkspaceAggregate Event Sourcing

**Given** a workspace is created and used
**When** commands are executed
**Then** events are emitted and state is rebuilt correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.2.1 | `CreateWorkspaceCommand` emits `IsolationStartedEvent` | ⬜ |
| 18.2.2 | `ExecuteCommandCommand` emits `CommandExecutedEvent` on success | ⬜ |
| 18.2.3 | `ExecuteCommandCommand` emits `CommandFailedEvent` on failure | ⬜ |
| 18.2.4 | `InjectTokensCommand` emits `TokensInjectedEvent` | ⬜ |
| 18.2.5 | `TerminateWorkspaceCommand` emits `WorkspaceTerminatedEvent` | ⬜ |
| 18.2.6 | Aggregate rebuilds state from event stream | ⬜ |
| 18.2.7 | Event versions increment correctly | ⬜ |
| 18.2.8 | All events include workspace_id and timestamp | ⬜ |

**Validation Commands:**
```bash
# Run aggregate tests
APP_ENVIRONMENT=test uv run pytest packages/syn-domain/src/syn_domain/contexts/workspaces/test_workspace_integration.py -v
```

### F18.3 ManagedWorkspace Lifecycle

**Given** a workspace is created via WorkspaceService
**When** I use the ManagedWorkspace context manager
**Then** the full lifecycle is managed correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.3.1 | `create_workspace()` returns async context manager | ⬜ |
| 18.3.2 | Workspace is created on context entry | ⬜ |
| 18.3.3 | `inject_files()` writes files to workspace | ⬜ |
| 18.3.4 | `inject_tokens()` injects tokens via sidecar | ⬜ |
| 18.3.5 | `execute()` runs commands in workspace | ⬜ |
| 18.3.6 | `stream()` yields real-time output lines | ⬜ |
| 18.3.7 | `collect_files()` retrieves artifacts | ⬜ |
| 18.3.8 | Workspace is terminated on context exit | ⬜ |
| 18.3.9 | Cleanup happens even on exception | ⬜ |

**Validation Commands:**
```bash
# Run lifecycle tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_workspace_service.py -v -k "lifecycle"
```

### F18.4 Docker Isolation Adapter

**Given** DockerIsolationAdapter is configured
**When** I create and use a workspace
**Then** Docker containers are managed correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.4.1 | `create()` starts Docker container | ⬜ |
| 18.4.2 | Container uses configured image (syn-workspace-claude) | ⬜ |
| 18.4.3 | gVisor runtime used when `use_gvisor=True` | ⬜ |
| 18.4.4 | Network configured per security policy | ⬜ |
| 18.4.5 | Memory limits applied | ⬜ |
| 18.4.6 | `execute()` runs docker exec | ⬜ |
| 18.4.7 | `health_check()` returns container status | ⬜ |
| 18.4.8 | `destroy()` stops and removes container | ⬜ |
| 18.4.9 | `copy_to()` writes files to workspace dir | ⬜ |
| 18.4.10 | `copy_from()` reads files from workspace dir | ⬜ |

**Validation Commands:**
```bash
# Run Docker adapter tests (mocked)
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/src/syn_adapters/workspace_backends/docker/test_docker_adapters.py -v
```

### F18.5 Token Injection Flow

**Given** TokenVendingServiceAdapter is configured
**When** tokens are injected into workspace
**Then** scoped tokens flow through the sidecar

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.5.1 | `vend_token()` creates scoped token with TTL | ⬜ |
| 18.5.2 | Token scope includes allowed APIs | ⬜ |
| 18.5.3 | Token scope includes allowed repos | ⬜ |
| 18.5.4 | Sidecar receives token via injection port | ⬜ |
| 18.5.5 | `revoke_tokens()` cleans up all tokens for execution | ⬜ |
| 18.5.6 | Token validation works correctly | ⬜ |
| 18.5.7 | Expired tokens rejected | ⬜ |

**Validation Commands:**
```bash
# Run token adapter tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/src/syn_adapters/workspace_backends/tokens/test_token_adapters.py -v
```

### F18.6 Event Stream Adapter

**Given** DockerEventStreamAdapter is configured
**When** agent executes in container
**Then** stdout is streamed in real-time

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.6.1 | `stream()` yields lines from docker exec | ⬜ |
| 18.6.2 | Timeout is respected | ⬜ |
| 18.6.3 | Empty lines are handled | ⬜ |
| 18.6.4 | Stream closes cleanly on completion | ⬜ |

**Validation Commands:**
```bash
# Run event stream tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/src/syn_adapters/workspace_backends/docker/test_docker_adapters.py -v -k "stream"
```

### F18.7 Memory Adapter (Test Environment)

**Given** MemoryIsolationAdapter is configured
**When** used in test environment
**Then** all operations work in-memory

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.7.1 | Raises error if `APP_ENVIRONMENT != test` | ⬜ |
| 18.7.2 | `create()` initializes in-memory state | ⬜ |
| 18.7.3 | `execute()` returns mock results | ⬜ |
| 18.7.4 | File operations use in-memory dictionary | ⬜ |
| 18.7.5 | `destroy()` clears state | ⬜ |
| 18.7.6 | No Docker dependency | ⬜ |

**Validation Commands:**
```bash
# Run memory adapter tests
APP_ENVIRONMENT=test uv run pytest packages/syn-adapters/src/syn_adapters/workspace_backends/memory/test_memory_adapter.py -v
```

### F18.8 WorkflowExecutionEngine Integration

**Given** WorkflowExecutionEngine with WorkspaceService
**When** workflow executes phases in containers
**Then** WorkspaceService is used correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.8.1 | Engine requires `workspace_service` (not None) | ⬜ |
| 18.8.2 | `_execute_phase_in_container()` uses `create_workspace()` | ⬜ |
| 18.8.3 | Task.json injected via `inject_files()` | ⬜ |
| 18.8.4 | Agent output streamed via `stream()` | ⬜ |
| 18.8.5 | Artifacts collected via `collect_files()` | ⬜ |
| 18.8.6 | Workspace terminated after phase | ⬜ |
| 18.8.7 | Events emitted to event store | ⬜ |

**Validation Commands:**
```bash
# Run engine integration tests
APP_ENVIRONMENT=test uv run pytest packages/syn-domain/src/syn_domain/contexts/workflows/execute_workflow/test_execute_workflow.py -v
```

### F18.9 Full Stack E2E Validation ⭐ CRITICAL

**Given** all components are running (PostgreSQL, Event Store, Dashboard, Docker)
**When** I execute a workflow via UI or CLI
**Then** events flow through all layers correctly

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 18.9.1 | **Event Store Layer**: WorkflowExecutionStarted persisted | ⬜ |
| 18.9.2 | **Event Store Layer**: WorkspaceCreated event persisted | ⬜ |
| 18.9.3 | **Docker Layer**: Container created with correct image | ⬜ |
| 18.9.4 | **Docker Layer**: Container has correct network config | ⬜ |
| 18.9.5 | **Token Layer**: Token vended for execution | ⬜ |
| 18.9.6 | **Token Layer**: Token injected into container | ⬜ |
| 18.9.7 | **Agent Layer**: Agent runner starts correctly | ⬜ |
| 18.9.8 | **Agent Layer**: Task.json read by agent | ⬜ |
| 18.9.9 | **Stream Layer**: Agent output streamed to control plane | ⬜ |
| 18.9.10 | **Stream Layer**: SSE events reach dashboard | ⬜ |
| 18.9.11 | **Event Store Layer**: CommandExecutedEvent persisted | ⬜ |
| 18.9.12 | **Event Store Layer**: PhaseCompleted persisted | ⬜ |
| 18.9.13 | **Artifact Layer**: Files collected from container | ⬜ |
| 18.9.14 | **Artifact Layer**: Artifacts visible in API | ⬜ |
| 18.9.15 | **UI Layer**: Execution appears in list | ⬜ |
| 18.9.16 | **UI Layer**: Status updates in real-time | ⬜ |
| 18.9.17 | **UI Layer**: Token count updates | ⬜ |
| 18.9.18 | **UI Layer**: Phase progress shown | ⬜ |
| 18.9.19 | **Cleanup Layer**: Container destroyed after completion | ⬜ |
| 18.9.20 | **Cleanup Layer**: Tokens revoked after execution | ⬜ |

**Validation Commands:**
```bash
# Start full stack
just dev-force
sleep 30

# Execute workflow
source .env && uv run syn workflow run water-lightyear --container

# Verify events in store
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY COUNT(*) DESC;"

# Verify in UI
open http://localhost:5173/executions
```

### F18 Test Results Summary

| # | Sub-Feature | Criteria | Priority |
|---|-------------|----------|----------|
| 18.1 | WorkspaceService Factory Methods | 5 | P0 |
| 18.2 | WorkspaceAggregate Event Sourcing | 8 | P0 |
| 18.3 | ManagedWorkspace Lifecycle | 9 | P0 |
| 18.4 | Docker Isolation Adapter | 10 | P0 |
| 18.5 | Token Injection Flow | 7 | P1 |
| 18.6 | Event Stream Adapter | 4 | P1 |
| 18.7 | Memory Adapter (Test Environment) | 6 | P1 |
| 18.8 | WorkflowExecutionEngine Integration | 7 | P0 |
| 18.9 | Full Stack E2E Validation | 20 | P0 |
| **TOTAL** | | **76** | |

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

**Event Store & Execution Model (F7.5-F7.6) ⭐ CRITICAL:**
7.5. [ ] **F7.5: Event Store Verification** - Verify all events reach event store
7.6. [ ] **F7.6: Workflow Execution Model** - Test runs list and execution detail

**Agentic Integration (F8-F12):**
8. [ ] **F8: Agentic Execution** - AgenticWorkflowExecutor tests
9. [ ] **F9: Workspaces** - LocalWorkspace with hooks
10. [ ] **F10: Artifacts** - ArtifactBundle flow
11. [ ] **F11: Event Bridge** - Hook-to-domain events
12. [ ] **F12: Providers** - Agent factory and availability

**WebSocket Control Plane (F13) ⭐:**
13. [ ] **F13: WebSocket Control Plane** - Pause/Resume/Cancel with browser automation

**Isolated Workspace Architecture (F14) ⭐:**
14. [ ] **F14: Isolated Workspaces** - Docker isolation, git identity, logging, network allowlist

**GitHub App & Secure Token Architecture (F15) ⭐:**
15. [ ] **F15: Secure Tokens** - GitHub App auth, token vending, spend tracking, sidecar proxy

**Workspace-First Execution Architecture (F16) ⭐:**
16. [ ] **F16: Workspace-First Execution** - LocalWorkspace/InMemoryWorkspace test-only, WorkspaceService enforcement, AgentExecutor

**Container Execution Robustness (F17) ⭐:**
17. [ ] **F17: Container Execution Robustness** - Phase counting, artifact collection, session persistence, git attribution, analytics streaming, stale cleanup

**WorkspaceService Architecture (F18) ⭐ NEW:**
18. [ ] **F18: WorkspaceService Architecture** - Event-sourced workspace domain, Docker/Memory adapters, token injection, full stack E2E validation

### Quick Pytest Commands

```bash
# ⭐ CRITICAL: Run event store regression tests FIRST
APP_ENVIRONMENT=test pytest packages/syn-domain/tests/integration/test_event_projection_consistency.py -v

# Run all domain tests
APP_ENVIRONMENT=test pytest packages/syn-domain/ -v

# Run all agentic tests (F8-F12)
pytest packages/syn-adapters/tests/test_*.py -v

# Run specific feature tests
pytest packages/syn-adapters/tests/test_orchestration.py -v      # F8
pytest packages/syn-adapters/tests/test_workspaces.py -v         # F9
pytest packages/syn-adapters/tests/test_artifacts.py -v          # F10
pytest packages/syn-adapters/tests/test_events.py -v             # F11
pytest packages/syn-adapters/tests/test_claude_agentic.py -v     # F12

# Run isolated workspace tests (F14)
pytest packages/syn-adapters/tests/workspaces/ -v
pytest packages/syn-adapters/tests/test_orchestration_factory.py -v
pytest packages/syn-shared/tests/test_workspace_settings.py -v

# F14 POC validation (manual)
just poc-git-identity   # Git identity injection
just poc-claude-api     # Claude API connectivity
just poc-logging        # Container logging
just poc-allowlist      # Network allowlist

# Run Container Execution Robustness tests (F17)
APP_ENVIRONMENT=test pytest packages/syn-domain/tests/contexts/workflows/execute_workflow/test_container_execution.py -v
APP_ENVIRONMENT=test pytest packages/syn-shared/tests/test_workspace_paths.py -v
APP_ENVIRONMENT=test pytest packages/syn-adapters/tests/workspaces/test_artifact_collection.py -v
APP_ENVIRONMENT=test pytest packages/syn-domain/tests/contexts/workflows/cleanup/test_stale_cleaner.py -v

# Run GitHub App & Secure Token tests (F15)
pytest packages/syn-tokens/tests/ -v
pytest packages/syn-adapters/tests/github/ -v
uv run python scripts/e2e_github_app_test.py
# Full QA check (lint + type + test)
poetry run poe check-fix
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
| **F5.6** | **Live Dashboard Updates** ⭐ | **22** | ⬜ | ⬜ | ⬜ |
| F6 | Data Consistency | 6 | ⬜ | ⬜ | ⬜ |
| F7 | Error Handling | 6 | ⬜ | ⬜ | ⬜ |
| **F7.5** | **Event Store Verification** ⭐ | **22** | ⬜ | ⬜ | ⬜ |
| **F7.6** | **Workflow Execution Model** ⭐ | **30** | ⬜ | ⬜ | ⬜ |
| **F8** | **Agentic Workflow Execution** | **16** | ⬜ | ⬜ | ⬜ |
| **F9** | **Workspace & Hook Integration** | **13** | ⬜ | ⬜ | ⬜ |
| **F10** | **Artifact Bundle Flow** | **13** | ⬜ | ⬜ | ⬜ |
| **F11** | **Event Bridge** | **12** | ⬜ | ⬜ | ⬜ |
| **F12** | **Agent Provider Management** | **9** | ⬜ | ⬜ | ⬜ |
| **F13** | **WebSocket Control Plane** ⭐ | **55** | ⬜ | ⬜ | ⬜ |
| **F14** | **Isolated Workspace Architecture** ⭐ | **52** | ⬜ | ⬜ | ⬜ |
| **F15** | **GitHub App & Secure Tokens** ⭐ | **50** | ⬜ | ⬜ | ⬜ |
| **F16** | **Workspace-First Execution** ⭐ | **51** | ⬜ | ⬜ | ⬜ |
| **F17** | **Container Execution Robustness** ⭐ | **60** | ⬜ | ⬜ | ⬜ |
| **F18** | **WorkspaceService Architecture** ⭐ NEW | **76** | ⬜ | ⬜ | ⬜ |
| **TOTAL** | | **560** | ⬜ | ⬜ | ⬜ |

---

## Issues Found

| # | Feature | Description | Severity | Status |
|---|---------|-------------|----------|--------|
| | | | | |

---

## Notes

_Add any observations, recommendations, or follow-up items here._

### Migration Notes (v6.2 → v6.3)

- **WorkspaceService Architecture:** New F18 tests for event-sourced workspace domain
- **Deprecated WorkspaceRouter Removed:** Old `syn-adapters/workspaces/` module deleted (12,500+ lines)
- **WorkspaceService Facade:** Unified lifecycle management via `WorkspaceService.create_docker()` / `.create_memory()`
- **WorkspaceAggregate:** Event-sourced aggregate with commands: Create, Execute, InjectTokens, Terminate
- **Port Interfaces:** `IsolationBackendPort`, `SidecarPort`, `TokenInjectionPort`, `EventStreamPort`
- **Docker Adapters:** `DockerIsolationAdapter`, `DockerSidecarAdapter`, `DockerEventStreamAdapter`
- **Memory Adapters:** In-memory implementations for isolated unit testing (test env only)
- **Token Adapters:** `TokenVendingServiceAdapter`, `SidecarTokenInjectionAdapter`
- **WorkflowExecutionEngine:** Now requires `workspace_service` instead of `workspace_router`
- **Test Count:** Increased from 484 to 560 criteria
- **New Files:**
  - `packages/syn-domain/src/syn_domain/contexts/workspaces/_shared/` (Aggregate, Ports, Value Objects)
  - `packages/syn-domain/src/syn_domain/contexts/workspaces/*/` (Command slices)
  - `packages/syn-adapters/src/syn_adapters/workspace_backends/docker/` (Docker implementations)
  - `packages/syn-adapters/src/syn_adapters/workspace_backends/memory/` (Test implementations)
  - `packages/syn-adapters/src/syn_adapters/workspace_backends/tokens/` (Token adapters)
  - `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py` (Facade)

### Migration Notes (v6.1 → v6.2)

- **Container Execution Robustness:** New F17 tests for agent-in-container reliability
- **Type-Safe Workspace Paths:** New module `syn_shared.workspace_paths` for consistent path constants
- **Phase Counting Fix:** Removed duplicate `ctx.phase_results.append()` call
- **Artifact Collection Fix:** Unified output directory across agent-runner and adapters
- **Session Persistence:** AgentSessionAggregate now created/completed in container mode
- **Git Attribution:** Settings copied from agentic-primitives with attribution disabled
- **Analytics Streaming:** Real-time hook event streaming via sidecar (P2)
- **Stale Cleanup:** Background job to mark stuck executions as failed (P2)
- **Test Count:** Increased from 424 to 484 criteria
- **New Files:**
  - `packages/syn-shared/src/syn_shared/workspace_paths.py`
  - `packages/syn-domain/tests/contexts/workflows/execute_workflow/test_container_execution.py`
  - `packages/syn-shared/tests/test_workspace_paths.py`
  - `packages/syn-adapters/tests/workspaces/test_artifact_collection.py`
  - `packages/syn-domain/tests/contexts/workflows/cleanup/test_stale_cleaner.py`

### Migration Notes (v6.0 → v6.1)

- **Workspace-First Execution:** New F16 tests for ADR-023 enforcement
- **ADR-023:** Workspace-First Execution Model design decisions
- **LocalWorkspace:** Now TEST ONLY - raises `NonIsolatedWorkspaceError` in dev/prod
- **InMemoryWorkspace:** New fast test-only workspace (no disk I/O)
- **WorkspaceRouter:** Now enforces isolation in non-test environments
- **WorkflowExecutionEngine:** Requires `execution_repository` and `workspace_router` as DI
- **AgentExecutor Protocol:** New abstraction for running agents in isolated workspaces
- **ClaudeAgentExecutor:** Implementation that wraps ClaudeAgenticAgent
- **Test Count:** Increased from 373 to 424 criteria
- **New Files:**
  - `packages/syn-adapters/src/syn_adapters/agents/executor.py`
  - `packages/syn-adapters/src/syn_adapters/agents/claude_executor.py`
  - `packages/syn-adapters/src/syn_adapters/workspaces/memory.py`
  - `docs/PLAN-FULL-WORKSPACE-ISOLATION.md`

### Migration Notes (v5.0 → v6.0)

- **GitHub App Integration:** New F15 tests for secure authentication
- **ADR-022:** Secure Token Architecture design decisions
- **Token Vending:** Short-lived, scoped tokens (5-min TTL)
- **Spend Tracking:** Budget allocation per workflow type
- **Sidecar Proxy:** Envoy config for token injection
- **GitHub App Env Vars:** `SYN_GITHUB_APP_ID`, `SYN_GITHUB_PRIVATE_KEY`, etc.
- **Test Count:** Increased from 323 to 373 criteria
- **New E2E Script:** `scripts/e2e_github_app_test.py`

### Migration Notes (v4.0 → v5.0)

- **Isolated Workspace Architecture:** New F14 tests for workspace isolation
- **ADR-021:** Isolated Workspace Architecture design decisions
- **WorkspaceRouter:** Automatic backend selection (Firecracker > gVisor > Docker)
- **Git Identity:** `SYN_GIT_USER_NAME`, `SYN_GIT_USER_EMAIL`, `SYN_GIT_TOKEN` env vars
- **API Keys:** Automatic injection of `ANTHROPIC_API_KEY` into containers
- **Container Logging:** JSON logs at `/workspace/.logs/agent.jsonl`
- **Egress Proxy:** mitmproxy at `docker/egress-proxy/`
- **New POC Commands:** `just poc-git-identity`, `just poc-logging`, `just poc-allowlist`
- **Test Count:** Increased from 271 to 323 criteria
- **Unit Tests:** 95+ new tests for workspace isolation
### Migration Notes (v3.0 → v4.0)

- **WebSocket Control Plane:** New F13 tests for real-time execution control
- **Control API:** New endpoints `/api/executions/{id}/pause|resume|cancel|state`
- **WebSocket Endpoint:** `/api/ws/control/{execution_id}` for bidirectional control
- **New Events:** `ExecutionPaused`, `ExecutionResumed`, `ExecutionCancelled`
- **Executor Enhancement:** `control_signal_checker` parameter for signal handling
- **CLI Commands:** `syn control pause|resume|cancel|status`
- **Test Count:** Increased from 210 to 264 criteria
- **Browser Automation:** F13.6 tests recommended for Playwright/Cypress

### Migration Notes (v2.0 → v3.0)

- **Event Store Verification:** New F7.5 tests ensure all events reach event store
- **Workflow Execution Model:** New F7.6 tests for separating templates from runs
- **New Endpoints:** `/api/workflows/{id}/runs` and `/api/executions/{id}`
- **Session Updates:** Sessions now link to `execution_id`
- **Test Count:** Increased from 142 to 194 criteria
- **Critical Tests:** F7.5 tests should **never** be skipped - they catch event emission bugs

### Migration Notes (v1.0 → v2.0)

- **New Prerequisites:** ANTHROPIC_API_KEY required for live agent tests (F8.5)
- **New Dependencies:** `syn-adapters[claude-agentic]` adds claude-agent-sdk
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
| **Event Store** ⭐ | **F7.5** | **SQL + API (critical)** |
| **Execution Model** ⭐ | **F7.6** | **API + Browser** |
| **Agentic** | **F8-F12** | **pytest (automated)** |
| **Control Plane** ⭐ | **F13** | **Browser automation (Playwright)** |
| **Isolated Workspaces** ⭐ | **F14** | **pytest + just POC commands** |
| **Secure Tokens** ⭐ | **F15** | **pytest + e2e script** |
| **Workspace-First** ⭐ | **F16** | **pytest (fully automated)** |
| **Container Robustness** ⭐ | **F17** | **pytest + E2E workflow** |
| **WorkspaceService** ⭐ NEW | **F18** | **pytest + Docker E2E** |

### Known Issues & Learnings

| Issue | Root Cause | Fix | ADR |
|-------|------------|-----|-----|
| PhaseCompleted events missing | Command existed but not called in execution service | Added `_complete_phase()` method | ADR-013 |
| Operations not showing in UI | Projection didn't store operations array | Updated `on_operation_recorded` handler | ADR-013 |
| Workflow status inconsistent | List vs detail projections updated differently | Unified status update logic | ADR-013 |
| Sessions stuck in "running" | Session never completed if execution failed | Add cleanup on failure | - |

### Event Store Debugging Commands

```bash
# List all events
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type;"

# Find missing PhaseCompleted events
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT
     (SELECT COUNT(*) FROM events WHERE event_type = 'SessionCompleted') as session_completed,
     (SELECT COUNT(*) FROM events WHERE event_type = 'PhaseCompleted') as phase_completed;"

# Check projection sync
docker exec syn-postgres psql -U syn -d syn -c \
  "SELECT projection_name, last_event_position FROM projection_states;"

# Reset projections (DANGEROUS - rebuilds from scratch)
docker exec syn-postgres psql -U syn -d syn -c \
  "UPDATE projection_states SET last_event_position = 0 WHERE projection_name = 'global_subscription';"
```
