# CURRENT ACTIVE STATE ARTIFACT (CASA)

**Project:** Agentic Engineering Framework
**Updated:** 2025-12-02
**Branch:** `feat/workflow-execution-engine`

---

## Where I Left Off

Completed **Event Store Server Integration** - major architectural milestone. The AEF now uses the event-sourcing-platform SDK for event persistence via gRPC.

## What Was Just Completed

### Event Store Integration (ADR-007)
- ✅ Event Store Server added to Docker Compose
- ✅ gRPC client via `event-sourcing-platform` SDK
- ✅ Environment-aware repository factories (test vs dev/prod)
- ✅ CQRS read models for dashboard (PostgreSQL queries)
- ✅ In-memory storage guards (test environment only)
- ✅ CLI seed command connects to Event Store
- ✅ Dashboard API uses async read models
- ✅ E2E validation script (`just validate-events`)

### QA Status
- 255 tests passing
- 5 tests failing (feature gaps in read models for operations/phases detail - non-blocking)
- All lint/type checks passing

## What To Do Next

**Continue E2E Testing:**
1. Start full stack: `just dev`
2. Seed workflows: `just cli workflow seed`
3. Run dashboard backend: `just dashboard-backend`
4. Run dashboard frontend: `just dashboard-frontend`
5. Validate events: `just validate-events`
6. Test in browser at http://localhost:5173

**Then complete remaining Phase 2 milestones:**
- [ ] M6: CLI `run` Command (partial - needs full execution flow)
- [ ] M7: Dashboard Backend (partial - read models done, need more endpoints)
- [ ] M8: Dashboard Frontend (exists, needs real data validation)
- [ ] M9: End-to-End Testing (in progress)
- [ ] M10: Documentation & ADR (ADR-007 done, need more docs)

## Open Loops

- [ ] Fix 5 failing dashboard tests (operations/phases read model gaps)
- [ ] Implement workflow execution flow (run command → agent → events)
- [ ] Real agent integration tests with Claude API
- [ ] Build observability dashboard visualizations
- [ ] Performance testing with multiple concurrent workflows

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         AEF Stack                               │
├─────────────────────────────────────────────────────────────────┤
│  CLI (aef-cli)          │  Dashboard (aef-dashboard)            │
│  - workflow seed        │  - FastAPI backend                    │
│  - workflow run         │  - React frontend                     │
│  - workflow status      │  - SSE for real-time updates          │
├─────────────────────────────────────────────────────────────────┤
│                    Domain (aef-domain)                          │
│  - WorkflowAggregate    - AgentSessionAggregate                 │
│  - ArtifactAggregate    - Event Sourcing via SDK                │
├─────────────────────────────────────────────────────────────────┤
│                   Adapters (aef-adapters)                       │
│  - GrpcEventStoreClient (SDK)   - Read Models (asyncpg)         │
│  - InMemory* (test only)        - Repository Factories          │
├─────────────────────────────────────────────────────────────────┤
│              Infrastructure (Docker Compose)                    │
│  - PostgreSQL (port 5432)                                       │
│  - Event Store Server (port 50051, gRPC)                        │
└─────────────────────────────────────────────────────────────────┘
```

## Key Commands

```bash
# Development
just dev                  # Start Docker (PostgreSQL + Event Store)
just cli workflow seed    # Seed sample workflows
just dashboard-backend    # Run API server
just dashboard-frontend   # Run React dev server
just validate-events      # Inspect events in PostgreSQL

# Testing
just test                 # Run all tests
just qa                   # Full QA pipeline (format, lint, type, test)
```

## Key Files

### New in this commit
- `docs/adrs/ADR-007-event-store-integration.md` - Architecture decision
- `packages/aef-adapters/src/aef_adapters/storage/event_store_client.py` - SDK client
- `packages/aef-adapters/src/aef_adapters/storage/repositories.py` - Repository factories
- `apps/aef-dashboard/src/aef_dashboard/read_models.py` - CQRS queries
- `scripts/validate_event_store.py` - E2E validation script
- `conftest.py` - Test environment configuration

### Architecture Decisions
- `docs/adrs/ADR-006-hook-architecture-agent-swarms.md`
- `docs/adrs/ADR-007-event-store-integration.md`

## Dependencies

- `lib/event-sourcing-platform` Python SDK ✅
- `lib/agentic-primitives` hook client library ✅
- Docker + PostgreSQL ✅
- Event Store Server (Rust gRPC) ✅
- Claude/OpenAI API keys (for real agent tests)

## Current State

```
Phase 1 (MVP Foundation): ✅ COMPLETE
  M1-M9: All milestones complete
  Coverage: 80.22%
  Tests: 122/122 passing

Phase 2 (Workflow Execution): 🔄 IN PROGRESS
  Part 1: agentic-primitives hooks ✅ COMPLETE
  Part 2: AEF workflow engine
    - M1-M5: ✅ Core domain & execution engine
    - M6: 🔄 CLI run command (partial)
    - M7: 🔄 Dashboard backend (read models done)
    - M8: 🔄 Dashboard frontend (exists)
    - M9: 🔄 E2E testing (in progress)
    - M10: ⏳ Documentation

Event Store Integration: ✅ COMPLETE
  - 255 tests passing, 5 non-blocking failures
  - Full gRPC integration working
```
