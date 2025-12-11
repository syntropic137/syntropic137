# AEF End-to-End Acceptance Tests

**Version:** 5.0.0
**Created:** 2025-12-02
**Updated:** 2025-12-11
**Status:** Active

---

## Overview

This document defines acceptance tests for validating the Agentic Engineering Framework (AEF) stack end-to-end. Tests are organized by feature and include specific validation criteria.

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

All state changes in AEF **MUST** be persisted to the event store via aggregates. This is non-negotiable because:

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
docker exec aef-postgres psql -U aef -d aef -c \
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
docker exec aef-postgres psql -U aef -d aef -c \
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
docker exec aef-postgres psql -U aef -d aef -c \
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
EVENT_COUNT=$(docker exec aef-postgres psql -U aef -d aef -t -c "SELECT COUNT(*) FROM events WHERE event_type = 'SessionCompleted';")
API_COUNT=$(curl -s http://localhost:8000/api/sessions?status=completed | jq 'length')
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
docker exec aef-postgres psql -U aef -d aef -c \
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
curl -s http://localhost:8000/api/workflows/implementation-workflow-v1/runs | jq
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
curl -s http://localhost:8000/api/executions/<execution_id> | jq
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
curl -s http://localhost:8000/api/sessions/<session_id> | jq '.execution_id'
curl -s "http://localhost:8000/api/sessions?execution_id=<exec_id>" | jq
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
curl -s http://localhost:8000/api/workflows/implementation-workflow-v1 | jq '{runs_count, runs_link}'
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
curl -s http://localhost:8000/api/executions/<execution_id>/state | jq

# Pause a running execution
curl -X POST http://localhost:8000/api/executions/<execution_id>/pause \
  -H "Content-Type: application/json" \
  -d '{"reason": "Testing pause"}' | jq

# Resume a paused execution
curl -X POST http://localhost:8000/api/executions/<execution_id>/resume | jq

# Cancel an execution
curl -X POST http://localhost:8000/api/executions/<execution_id>/cancel \
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
const ws = new WebSocket('ws://localhost:8000/api/ws/control/exec-123');
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
pytest packages/aef-adapters/tests/test_executor_control.py -v
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
| 13.5.1 | `aef control pause <id>` sends pause signal | ⬜ |
| 13.5.2 | `aef control pause <id> --reason "..."` includes reason | ⬜ |
| 13.5.3 | `aef control resume <id>` sends resume signal | ⬜ |
| 13.5.4 | `aef control cancel <id>` prompts for confirmation | ⬜ |
| 13.5.5 | `aef control cancel <id> --force` skips confirmation | ⬜ |
| 13.5.6 | `aef control status <id>` shows current state | ⬜ |
| 13.5.7 | Status shows colored output (green/yellow/red) | ⬜ |
| 13.5.8 | Error messages shown when API unavailable | ⬜ |
| 13.5.9 | `AEF_DASHBOARD_URL` environment variable supported | ⬜ |
| 13.5.10 | `--url` flag overrides default dashboard URL | ⬜ |

**Validation Commands:**
```bash
# Pause execution
aef control pause exec-123 --reason "Need to review"

# Resume execution
aef control resume exec-123

# Cancel with force
aef control cancel exec-123 --force --reason "Timeout"

# Check status
aef control status exec-123

# Use custom dashboard URL
AEF_DASHBOARD_URL=http://prod:8000 aef control status exec-123
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

<<<<<<< HEAD
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

### F14.1 Workspace Router & Backend Selection

**Given** the system is configured
**When** I create a workspace via WorkspaceRouter
**Then** the best available backend is selected

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.1.1 | WorkspaceRouter.get_available_backends() returns list | ⬜ |
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
uv run python -m aef_perf check

# Run workspace router tests
uv run pytest packages/aef-adapters/tests/test_workspace_router.py -v
```

### F14.2 Git Identity Injection

**Given** AEF_GIT_* environment variables are set
**When** a workspace is created
**Then** git identity is configured inside the container

| # | Acceptance Criteria | Status |
|---|---------------------|--------|
| 14.2.1 | GitIdentitySettings reads from AEF_GIT_* env vars | ⬜ |
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
# Author: aef-bot[bot] <bot@aef.dev>
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
uv run pytest packages/aef-adapters/tests/test_orchestration_factory.py -v
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
uv run pytest packages/aef-adapters/tests/workspaces/ \
  packages/aef-adapters/tests/test_orchestration_factory.py \
  packages/aef-shared/tests/test_workspace_settings.py -v

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

=======
>>>>>>> origin/main
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

<<<<<<< HEAD
**WebSocket Control Plane (F13) ⭐:**
13. [ ] **F13: WebSocket Control Plane** - Pause/Resume/Cancel with browser automation

**Isolated Workspace Architecture (F14) ⭐ NEW:**
14. [ ] **F14: Isolated Workspaces** - Docker isolation, git identity, logging, network allowlist

=======
**WebSocket Control Plane (F13) ⭐ NEW:**
13. [ ] **F13: WebSocket Control Plane** - Pause/Resume/Cancel with browser automation

>>>>>>> origin/main
### Quick Pytest Commands

```bash
# ⭐ CRITICAL: Run event store regression tests FIRST
APP_ENVIRONMENT=test pytest packages/aef-domain/tests/integration/test_event_projection_consistency.py -v

# Run all domain tests
APP_ENVIRONMENT=test pytest packages/aef-domain/ -v

# Run all agentic tests (F8-F12)
pytest packages/aef-adapters/tests/test_*.py -v

# Run specific feature tests
pytest packages/aef-adapters/tests/test_orchestration.py -v      # F8
pytest packages/aef-adapters/tests/test_workspaces.py -v         # F9
pytest packages/aef-adapters/tests/test_artifacts.py -v          # F10
pytest packages/aef-adapters/tests/test_events.py -v             # F11
pytest packages/aef-adapters/tests/test_claude_agentic.py -v     # F12

<<<<<<< HEAD
# Run isolated workspace tests (F14)
pytest packages/aef-adapters/tests/workspaces/ -v
pytest packages/aef-adapters/tests/test_orchestration_factory.py -v
pytest packages/aef-shared/tests/test_workspace_settings.py -v

# F14 POC validation (manual)
just poc-git-identity   # Git identity injection
just poc-claude-api     # Claude API connectivity
just poc-logging        # Container logging
just poc-allowlist      # Network allowlist

=======
>>>>>>> origin/main
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
<<<<<<< HEAD
| **F14** | **Isolated Workspace Architecture** ⭐ | **52** | ⬜ | ⬜ | ⬜ |
| **TOTAL** | | **323** | ⬜ | ⬜ | ⬜ |
=======
| **TOTAL** | | **271** | ⬜ | ⬜ | ⬜ |
>>>>>>> origin/main

---

## Issues Found

| # | Feature | Description | Severity | Status |
|---|---------|-------------|----------|--------|
| | | | | |

---

## Notes

_Add any observations, recommendations, or follow-up items here._

<<<<<<< HEAD
### Migration Notes (v4.0 → v5.0)

- **Isolated Workspace Architecture:** New F14 tests for workspace isolation
- **ADR-021:** Isolated Workspace Architecture design decisions
- **WorkspaceRouter:** Automatic backend selection (Firecracker > gVisor > Docker)
- **Git Identity:** `AEF_GIT_USER_NAME`, `AEF_GIT_USER_EMAIL`, `AEF_GIT_TOKEN` env vars
- **API Keys:** Automatic injection of `ANTHROPIC_API_KEY` into containers
- **Container Logging:** JSON logs at `/workspace/.logs/agent.jsonl`
- **Egress Proxy:** mitmproxy at `docker/egress-proxy/`
- **New POC Commands:** `just poc-git-identity`, `just poc-logging`, `just poc-allowlist`
- **Test Count:** Increased from 271 to 323 criteria
- **Unit Tests:** 95+ new tests for workspace isolation

=======
>>>>>>> origin/main
### Migration Notes (v3.0 → v4.0)

- **WebSocket Control Plane:** New F13 tests for real-time execution control
- **Control API:** New endpoints `/api/executions/{id}/pause|resume|cancel|state`
- **WebSocket Endpoint:** `/api/ws/control/{execution_id}` for bidirectional control
- **New Events:** `ExecutionPaused`, `ExecutionResumed`, `ExecutionCancelled`
- **Executor Enhancement:** `control_signal_checker` parameter for signal handling
- **CLI Commands:** `aef control pause|resume|cancel|status`
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
| **Event Store** ⭐ | **F7.5** | **SQL + API (critical)** |
| **Execution Model** ⭐ | **F7.6** | **API + Browser** |
| **Agentic** | **F8-F12** | **pytest (automated)** |
| **Control Plane** ⭐ | **F13** | **Browser automation (Playwright)** |
<<<<<<< HEAD
| **Isolated Workspaces** ⭐ | **F14** | **pytest + just POC commands** |
=======
>>>>>>> origin/main

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
docker exec aef-postgres psql -U aef -d aef -c \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY event_type;"

# Find missing PhaseCompleted events
docker exec aef-postgres psql -U aef -d aef -c \
  "SELECT
     (SELECT COUNT(*) FROM events WHERE event_type = 'SessionCompleted') as session_completed,
     (SELECT COUNT(*) FROM events WHERE event_type = 'PhaseCompleted') as phase_completed;"

# Check projection sync
docker exec aef-postgres psql -U aef -d aef -c \
  "SELECT projection_name, last_event_position FROM projection_states;"

# Reset projections (DANGEROUS - rebuilds from scratch)
docker exec aef-postgres psql -U aef -d aef -c \
  "UPDATE projection_states SET last_event_position = 0 WHERE projection_name = 'global_subscription';"
```
