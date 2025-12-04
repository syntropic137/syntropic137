# CURRENT ACTIVE STATE ARTIFACT (CASA)

**Project:** Agentic Engineering Framework
**Updated:** 2025-12-03
**Branch:** `feat/agentic-sdk-full-integration`

---

## Where I Left Off

Completed **Event Sourcing Subscriptions** - The critical fix for CQRS projection updates. The AEF now has proper pub/sub from event store to projections, fixing the systemic issue where seeded workflows weren't appearing in the dashboard.

## What Was Just Completed

### Event Sourcing Subscriptions (ADR-010) ✅

**Milestone 1: Subscribe Method**
- ✅ Added `subscribe()` async generator to `EventStoreClient` protocol
- ✅ Implemented in `GrpcEventStoreClient` (live streaming)
- ✅ Implemented in `MemoryEventStoreClient` (for tests)

**Milestone 2: EventSubscriptionService**
- ✅ Catch-up subscription from last known position
- ✅ Live subscription loop for real-time updates
- ✅ Position tracking via `projection_states` table
- ✅ Graceful shutdown handling
- ✅ 8 unit tests passing

**Milestone 3: Dashboard Integration**
- ✅ Subscription starts on app startup in `lifespan`
- ✅ Health endpoint shows subscription status
- ✅ Graceful shutdown on app stop

**Milestone 4: Cleanup**
- ✅ Removed `NoOpEventPublisher` pattern
- ✅ Created ADR-010 documenting architecture

**Milestone 5: E2E Validation**
- ✅ Workflows seeded → appear in dashboard within seconds
- ✅ Catch-up recovery works after restart
- ✅ Health shows `caught_up: true, events_processed: 2`

### Agentic SDK Integration (M1-M6 Complete)

- ✅ `AgenticProtocol` - New task execution interface
- ✅ `ClaudeAgenticAgent` - SDK wrapper for Claude
- ✅ `WorkspaceProtocol` - Environment abstraction
- ✅ `LocalWorkspace` - Local file system implementation
- ✅ `ArtifactBundle` - Phase-to-phase context flow
- ✅ `EventBridge` - Hook events → domain events
- ✅ `AgenticWorkflowExecutor` - Orchestration engine
- ✅ Dashboard execution endpoint (`POST /api/workflows/{id}/execute`)

### QA Status
- **233 tests passing** ✅
- All lint/type checks passing ✅
- Event subscription health check working ✅

## What To Do Next

**1. Full E2E Validation with Real Claude Agent:**
```bash
# Ensure API key is set in .env
ANTHROPIC_API_KEY=sk-ant-...

# Start the system
just dev
just dashboard-backend
just dashboard-frontend

# Seed and execute
just seed-workflows
# Click "Run Workflow" in UI
```

**2. Remaining Work:**
- [ ] E2E test with real Claude agent (requires API key)
- [ ] Hook auto-fire validation (`.claude/settings.json`)
- [ ] Deprecate old `AgentProtocol` (M7)
- [ ] Docker workspace implementation (M8 - stretch)

## Open Loops

- [ ] Real Claude agent integration test
- [ ] Validate hooks fire from `.claude/settings.json`
- [ ] Update `agentic-primitives` submodule reference
- [ ] PR merge to main

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     AEF CQRS ARCHITECTURE WITH SUBSCRIPTIONS                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WRITE PATH                          READ PATH                              │
│  ──────────                          ─────────                              │
│  CLI / API                           Dashboard API                          │
│     ↓                                     ↑                                 │
│  Command Handlers                    Query Handlers                         │
│     ↓                                     ↑                                 │
│  Aggregates                          Projections                            │
│     ↓                                     ↑                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         EVENT STORE (gRPC)                            │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │  Events:  WorkflowCreated  |  SessionStarted  |  ArtifactCreated │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                              ↓                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │              EventSubscriptionService (NEW!)                          │ │
│  │  - Catch-up: reads historical events on startup                       │ │
│  │  - Live: streams new events in real-time                              │ │
│  │  - Position tracking: survives restarts                               │ │
│  │  - Dispatches to ProjectionManager                                    │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                              ↓                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                      ProjectionManager                                │ │
│  │  EVENT_HANDLERS = {                                                   │ │
│  │    "WorkflowCreated": [workflow_summaries, workflow_detail],          │ │
│  │    "SessionStarted": [session_list],                                  │ │
│  │    "ArtifactCreated": [artifact_list],                                │ │
│  │  }                                                                    │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Commands

```bash
# Development
just dev                  # Start Docker (PostgreSQL + Event Store)
just seed-workflows       # Seed sample workflows (uses aef workflow seed)
just dashboard-backend    # Run API server (loads .env)
just dashboard-frontend   # Run React dev server

# Testing
just test                 # Run all tests
just qa                   # Full QA pipeline (format, lint, type, test)

# Health Check
curl http://localhost:8000/health
# Returns: {"status":"healthy","subscription":{"running":true,"caught_up":true,...}}
```

## Key Files

### Event Subscriptions (New!)
- `packages/aef-adapters/src/aef_adapters/subscriptions/service.py` - Core subscription service
- `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/client/grpc_client.py` - Subscribe method
- `apps/aef-dashboard/src/aef_dashboard/main.py` - Lifespan integration
- `docs/adrs/ADR-010-event-subscription-architecture.md` - Architecture decision

### Agentic SDK Integration
- `packages/aef-adapters/src/aef_adapters/agents/claude_agentic.py` - Claude SDK wrapper
- `packages/aef-adapters/src/aef_adapters/orchestration/executor.py` - Workflow executor
- `packages/aef-adapters/src/aef_adapters/artifacts/bundle.py` - Artifact management
- `packages/aef-adapters/src/aef_adapters/events/bridge.py` - Hook event bridge

### Project Plans
- `PROJECT-PLAN_20251203_EVENT-SOURCING-SUBSCRIPTIONS.md` - Subscriptions (✅ COMPLETE)
- `PROJECT-PLAN_20251202_AGENTIC-SDK-INTEGRATION.md` - SDK Integration (M1-M6 ✅)

## Current State

```
Phase 1 (MVP Foundation): ✅ COMPLETE
Phase 2 (Workflow Execution): ✅ COMPLETE
VSA Projections: ✅ COMPLETE
Event Store Integration: ✅ COMPLETE
Event Subscriptions: ✅ COMPLETE (NEW!)
Agentic SDK Integration: 🚧 M1-M6 Complete, M7-M8 Pending

Total Tests: 233 passing
Branch: feat/agentic-sdk-full-integration

Next: E2E validation with real Claude agent, then PR merge
```
