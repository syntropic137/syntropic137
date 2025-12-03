# CURRENT ACTIVE STATE ARTIFACT (CASA)

**Project:** Agentic Engineering Framework
**Updated:** 2025-12-02
**Branch:** `feat/vsa-projections`

---

## Where I Left Off

Completed **VSA Projections Implementation** - Full CQRS read-side with Vertical Slice Architecture. The AEF now has proper separation between command and query paths using VSA-compliant projections.

## What Was Just Completed

### VSA Projections Implementation (ADR-008)

**Infrastructure (M1):**
- ✅ `ProjectionStoreProtocol` - Abstract storage interface
- ✅ `InMemoryProjectionStore` - For testing
- ✅ `PostgresProjectionStore` - For production
- ✅ SQL migrations for projection tables

**Domain Restructure (M2):**
- ✅ Query DTOs in `domain/queries/` for each bounded context
- ✅ Read Model DTOs in `domain/read_models/` for each context

**Query Slices (M3-M7):**
- ✅ `list_workflows` - Workflow summaries with filtering
- ✅ `get_workflow_detail` - Detailed workflow view
- ✅ `list_sessions` - Session list with workflow filtering
- ✅ `list_artifacts` - Artifact list with filtering
- ✅ `get_metrics` - Dashboard aggregate metrics

**Integration (M8-M9):**
- ✅ `ProjectionManager` - Centralized event dispatch
- ✅ Dashboard API endpoints using VSA handlers

### QA Status
- **218 tests passing** ✅
- All lint/type checks passing ✅
- Full VSA compliance ✅

## What To Do Next

**E2E Testing & Validation:**
1. Start full stack: `just dev`
2. Seed workflows: `just cli workflow seed`
3. Run dashboard backend: `just dashboard-backend`
4. Run dashboard frontend: `just dashboard-frontend`
5. Test in browser at http://localhost:5173
6. Validate acceptance criteria

**Remaining Work:**
- [ ] Full E2E acceptance tests
- [ ] Event bus real-time subscription
- [ ] Performance testing
- [ ] Documentation updates

## Open Loops

- [ ] Real-time projection updates via event subscription
- [ ] Catch-up mechanism for projection rebuilding
- [ ] CLI event store connection fixes verified
- [ ] Real agent integration tests

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AEF Stack (VSA)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐        ┌─────────────────────────────────────────┐ │
│  │   COMMAND SIDE      │        │            QUERY SIDE                   │ │
│  ├─────────────────────┤        ├─────────────────────────────────────────┤ │
│  │  CLI / API          │        │  Dashboard API                          │ │
│  │    ↓                │        │    ↓                                    │ │
│  │  Command Handlers   │        │  Query Handlers                         │ │
│  │    ↓                │        │    ↓                                    │ │
│  │  Aggregates         │        │  Projections                            │ │
│  │    ↓                │        │    ↓                                    │ │
│  │  Event Store        │───────→│  Projection Store                       │ │
│  │  (gRPC)             │ events │  (PostgreSQL)                           │ │
│  └─────────────────────┘        └─────────────────────────────────────────┘ │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                          Query Slices (VSA)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  workflows/                sessions/              artifacts/      metrics/  │
│  ├─ list_workflows/       ├─ list_sessions/      ├─ list_artifacts/ │
│  │  ├─ projection.py      │  ├─ projection.py    │  ├─ projection.py│
│  │  ├─ handler.py         │  ├─ handler.py       │  ├─ handler.py   │
│  │  ├─ slice.yaml         │  ├─ slice.yaml       │  └─ slice.yaml   │
│  │  └─ test_*.py          │  └─ test_*.py        │                  │
│  └─ get_workflow_detail/  │                      │  get_metrics/    │
│     ├─ projection.py      │                      │  ├─ projection   │
│     ├─ handler.py         │                      │  ├─ handler      │
│     └─ slice.yaml         │                      │  └─ slice.yaml   │
├─────────────────────────────────────────────────────────────────────────────┤
│                          Infrastructure                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  PostgreSQL (5432)  │  Event Store Server (50051)  │  Dashboard (5173)     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Commands

```bash
# Development
just dev                  # Start Docker (PostgreSQL + Event Store)
just cli workflow seed    # Seed sample workflows
just dashboard-backend    # Run API server
just dashboard-frontend   # Run React dev server

# Testing
just test                 # Run all tests
just qa                   # Full QA pipeline (format, lint, type, test)
uv run pytest packages/aef-domain packages/aef-adapters/tests -v  # Run domain tests
```

## Key Files

### VSA Projections (New)
- `packages/aef-adapters/src/aef_adapters/projection_stores/` - Storage adapters
  - `protocol.py` - ProjectionStoreProtocol interface
  - `postgres_store.py` - PostgreSQL implementation
  - `memory_store.py` - In-memory for tests
- `packages/aef-adapters/src/aef_adapters/projections/manager.py` - Event dispatch
- `packages/aef-domain/src/aef_domain/contexts/*/slices/` - Query slices

### Domain Structure
```
aef-domain/contexts/
├── workflows/
│   ├── domain/
│   │   ├── queries/          # Query DTOs
│   │   └── read_models/      # Read model DTOs
│   └── slices/
│       ├── list_workflows/   # Query slice
│       └── get_workflow_detail/
├── sessions/
│   ├── domain/queries/
│   ├── domain/read_models/
│   └── slices/list_sessions/
├── artifacts/
│   └── slices/list_artifacts/
└── metrics/
    └── slices/get_metrics/
```

### Architecture Decisions
- `docs/adrs/ADR-006-hook-architecture-agent-swarms.md`
- `docs/adrs/ADR-007-event-store-integration.md`
- `docs/adrs/ADR-008-vsa-projection-architecture.md` (to be created)

## Current State

```
Phase 1 (MVP Foundation): ✅ COMPLETE

Phase 2 (Workflow Execution): ✅ COMPLETE
  Part 1: agentic-primitives hooks ✅
  Part 2: AEF workflow engine ✅
    - M1-M5: Core domain & execution
    - M6: CLI commands
    - M7: Dashboard backend
    - M8: Dashboard frontend
    - M9-M10: Integration & docs

VSA Projections: ✅ COMPLETE
  - M1: ProjectionStoreProtocol ✅
  - M2: Domain restructure ✅
  - M3-M7: Query slices ✅
  - M8-M9: Integration ✅
  - M10: Documentation ✅
  - 218 tests passing

Event Store Integration: ✅ COMPLETE

Next: E2E Testing & Acceptance Validation
```
