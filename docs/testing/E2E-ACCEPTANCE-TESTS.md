# AEF End-to-End Acceptance Tests

**Version:** 1.0.0  
**Created:** 2025-12-02  
**Status:** Draft  

---

## Overview

This document defines acceptance tests for validating the Agentic Engineering Framework (AEF) stack end-to-end. Tests are organized by feature and include specific validation criteria.

### Test Environment

| Component | Port | Technology |
|-----------|------|------------|
| PostgreSQL | 5432 | postgres:16-alpine |
| Event Store Server | 50051 | Rust gRPC service |
| Dashboard Backend | 8000 | FastAPI |
| Dashboard Frontend | 5173 | Vite + React |

### Prerequisites

- Docker and Docker Compose installed
- Node.js 18+ (for frontend)
- Python 3.12+ with uv
- All dependencies installed (`uv sync`)

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

## Test Execution Checklist

### Pre-Test Setup
- [ ] Clean Docker environment (`docker compose down -v`)
- [ ] Fresh database (no existing data)
- [ ] Dependencies installed (`uv sync`, `npm install`)

### Execution Order
1. [ ] **F1: Infrastructure** - Start Docker, verify containers
2. [ ] **F2: Event Store** - Seed data, validate events
3. [ ] **F3: CLI** - Test all CLI commands
4. [ ] **F4: Backend API** - Test all endpoints
5. [ ] **F5: Frontend** - Visual inspection in browser
6. [ ] **F6: Consistency** - Cross-component validation
7. [ ] **F7: Error Handling** - Edge cases

### Post-Test
- [ ] Document any failures
- [ ] Create issues for bugs found
- [ ] Update CASA with results

---

## Test Results Summary

| Feature | Total Tests | Passed | Failed | Skipped |
|---------|-------------|--------|--------|---------|
| F1: Infrastructure | 8 | ⬜ | ⬜ | ⬜ |
| F2: Event Store | 11 | ⬜ | ⬜ | ⬜ |
| F3: CLI | 12 | ⬜ | ⬜ | ⬜ |
| F4: Backend API | 21 | ⬜ | ⬜ | ⬜ |
| F5: Frontend | 15 | ⬜ | ⬜ | ⬜ |
| F6: Consistency | 6 | ⬜ | ⬜ | ⬜ |
| F7: Error Handling | 6 | ⬜ | ⬜ | ⬜ |
| **TOTAL** | **79** | ⬜ | ⬜ | ⬜ |

---

## Issues Found

| # | Feature | Description | Severity | Status |
|---|---------|-------------|----------|--------|
| | | | | |

---

## Notes

_Add any observations, recommendations, or follow-up items here._


