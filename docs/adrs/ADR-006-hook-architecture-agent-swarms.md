# ADR-006: Hook Architecture for Agent Swarms

**Status:** Proposed
**Date:** 2025-12-01
**Deciders:** @neural
**Tags:** hooks, performance, scalability, agentic-primitives

## Context

The Syntropic137 needs to capture observability events from AI agent operations (tool calls, token usage, session lifecycle). The existing approach in `agentic-primitives` uses subprocess-based hooks:

```bash
# Current approach
echo '{"tool_name": "Bash", ...}' | python pre-tool-use.py
```

While this works for single-agent scenarios, our vision includes **agent swarms** with 1000+ concurrent agents. Subprocess overhead (~10-50ms per call) becomes a significant bottleneck at this scale.

## Decision

We will create a **lightweight hook client library** (`agentic_hooks`) that:

1. **No subprocess overhead**: Events emitted via async function calls
2. **Event batching**: Buffer events and send in batches to reduce network calls
3. **Separate backend service**: Scalable hook backend that writes to PostgreSQL
4. **In-process validators**: Security validators imported and called directly

### Architecture

```
Agent Process                     Hook Backend Service
┌─────────────────────┐          ┌─────────────────────┐
│  InstrumentedAgent  │          │  FastAPI + uvicorn  │
│  ┌───────────────┐  │  HTTP    │  ┌───────────────┐  │
│  │  HookClient   │──┼─────────►│  │  /events/batch │  │
│  │  (batched)    │  │  POST    │  └───────┬───────┘  │
│  └───────────────┘  │          │          │          │
│  ┌───────────────┐  │          │          ▼          │
│  │  Validators   │  │          │  ┌───────────────┐  │
│  │  (in-process) │  │          │  │  PostgreSQL   │  │
│  └───────────────┘  │          │  └───────────────┘  │
└─────────────────────┘          └─────────────────────┘
```

### Event Flow

1. Agent calls `hook_client.emit(HookEvent(...))` - O(1) memory operation
2. Client buffers event (default: 50 events or 1 second)
3. Client batch-sends to backend via HTTP POST
4. Backend writes to PostgreSQL with async bulk insert
5. Dashboard queries PostgreSQL for real-time updates

### Key Design Decisions

#### D1: Zero-dependency client core
The `agentic_hooks` client has no required dependencies. HTTP transport is an optional extra (`agentic-hooks[http]`). This ensures the client can be imported anywhere without dependency conflicts.

#### D2: Separate hook backend service
Rather than embedding hook storage in the main application, a separate service:
- Scales independently
- Can be replicated for high availability
- Isolates observability concerns
- Can be shared across multiple applications

#### D3: PostgreSQL with time-based partitioning
Hook events are high-volume, append-only data. Time-based partitioning enables:
- Efficient cleanup of old data
- Better query performance for recent events
- Easy archival strategy

#### D4: In-process validators
Security validators (bash command checking, file path validation, PII detection) run **in-process** for:
- Zero latency overhead
- Ability to block dangerous operations immediately
- Rich context access

## Consequences

### Positive
- **Performance**: <5ms p99 latency for event emission (vs 10-50ms subprocess)
- **Scalability**: 1000+ concurrent agents supported
- **Simplicity**: 3-line integration for any Python agent
- **Observability**: Full event capture without performance penalty
- **Contribution**: Improvements flow back to agentic-primitives

### Negative
- **Complexity**: Requires running a backend service
- **Network**: Events require network call (batched, but still a dependency)
- **State**: Buffer can lose events on ungraceful shutdown

### Mitigations
- **Complexity**: Provide Docker Compose for easy local setup
- **Network**: Support JSONL fallback for offline/local development
- **State**: Flush buffer before shutdown, add retry with exponential backoff

## Alternatives Considered

### A1: Keep subprocess hooks
- ❌ Rejected: Doesn't scale to 1000 agents

### A2: Shared memory / IPC
- ❌ Rejected: Platform-specific, complex to implement

### A3: Message queue (Redis, Kafka)
- ⏸️ Deferred: May add later for very high scale, but HTTP sufficient for MVP

### A4: Embedded database (SQLite)
- ❌ Rejected: Doesn't support concurrent writes well, no central aggregation

## Implementation

See project plans:
- `PROJECT-PLAN_20251201_AGENTIC-PRIMITIVES-HOOKS.md`
- `PROJECT-PLAN_20251201_SYN137-WORKFLOW-EXECUTION.md`

## References

- [ADR-011: Analytics Middleware](../../lib/agentic-primitives/docs/adrs/011-analytics-middleware.md)
- [ADR-014: Atomic Hook Architecture](../../lib/agentic-primitives/docs/adrs/014-wrapper-impl-pattern.md)
- [Hook System Documentation](../../lib/agentic-primitives/docs/hooks/README.md)

