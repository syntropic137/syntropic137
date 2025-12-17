# ADR-026: TimescaleDB for Observability Event Storage

## Status

**Accepted** - 2025-12-16

## Context

During E2E testing of the agent-in-container observability system, we encountered a critical architectural issue:

**Observability events (token usage, tool calls) cannot be stored in the domain event store.**

### The Problem

```python
# This FAILS with "append precondition failed"
await event_store.append_events(
    stream_name=f"AgentObservations-{session_id}",
    events=[AgentObservationEvent.token_usage(...)],
    expected_version=nonce - 1,  # ❌ Violates aggregate invariants
)
```

**Root Cause:** The event store is designed for **domain events** that emerge from **aggregates with optimistic concurrency control**. Observability events are **external observations** that don't belong to aggregates and have fundamentally different characteristics.

### Industry Research

After researching how companies like Uber, Netflix, LinkedIn handle observability at scale, the industry consensus is clear:

**Domain events and observability events require separate storage systems.**

| Characteristic | Domain Events | Observability Events |
|---|---|---|
| **Purpose** | Business state changes | Telemetry, monitoring |
| **Volume** | Low-medium (100s/sec) | **Very high (millions/sec)** |
| **Retention** | Forever (audit trail) | Days/weeks (cost optimization) |
| **Consistency** | **Strong (aggregate invariants)** | Eventually consistent |
| **Storage** | Event Store (CQRS/ES) | **Time-series DB** |
| **Query Pattern** | By aggregate ID | By time range + filters |

## Decision

**Use TimescaleDB for observability events, keep PostgreSQL event store for domain events.**

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      STORAGE LAYER                            │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  PostgreSQL (same database, different tables)                │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  DOMAIN EVENTS (Event Store)                          │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │  Table: events                                         │  │
│  │  - WorkflowStarted, PhaseCompleted, SessionStarted    │  │
│  │  - Aggregate versioning (optimistic concurrency)      │  │
│  │  - Strong consistency guarantees                      │  │
│  │  - Managed by event-sourcing library                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  OBSERVABILITY EVENTS (TimescaleDB hypertable)        │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │  Hypertable: agent_observations                       │  │
│  │  - Token usage, tool calls, progress events           │  │
│  │  - Automatic partitioning by time                     │  │
│  │  - 10x-100x better write performance                  │  │
│  │  - Auto-compression (90% storage reduction)           │  │
│  │  - Retention policies (auto-delete old data)          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Why TimescaleDB?

1. **PostgreSQL Extension** - No new infrastructure! Just enable extension.
2. **10x-100x Performance** - Optimized for time-series data
3. **Automatic Compression** - 90% storage reduction after 7 days
4. **Retention Policies** - Auto-delete data older than 30 days
5. **SQL Interface** - Familiar query language
6. **Time-Series Optimizations** - `time_bucket()`, continuous aggregates, etc.

### Performance Benchmarks (TimescaleDB vs PostgreSQL)

- **Insert Performance**: 20x higher insert rates at scale
- **Query Performance**: 1.2x to 14,000x faster for time-based queries
- **Data Deletion**: 2,000x faster (for retention policies)

## Decision Drivers

1. **Correctness** - Don't violate event sourcing invariants
2. **Performance** - Handle millions of observations per second
3. **Cost** - Automatic compression and retention policies
4. **Simplicity** - Same PostgreSQL, just different tables
5. **Industry Alignment** - How Uber, Netflix, LinkedIn do it

## Schema Design

### Observability Events Table

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create observability events table
CREATE TABLE agent_observations (
    -- Time-series primary key
    time TIMESTAMPTZ NOT NULL,

    -- Correlation IDs
    session_id TEXT NOT NULL,
    execution_id TEXT,
    phase_id TEXT,
    workspace_id TEXT,

    -- Observation metadata
    observation_type TEXT NOT NULL,
    observation_id TEXT NOT NULL,  -- UUID for deduplication

    -- Flexible payload (observation-type specific)
    data JSONB NOT NULL,

    -- Indexes for common queries
    INDEX idx_session_time (session_id, time DESC),
    INDEX idx_execution_time (execution_id, time DESC),
    INDEX idx_observation_type (observation_type, time DESC)
);

-- Convert to hypertable (enables time-series optimizations)
SELECT create_hypertable('agent_observations', 'time');

-- Add compression policy (compress data older than 7 days)
ALTER TABLE agent_observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'session_id, observation_type',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('agent_observations', INTERVAL '7 days');

-- Add retention policy (drop data older than 30 days)
SELECT add_retention_policy('agent_observations', INTERVAL '30 days');

-- Add deduplication constraint
CREATE UNIQUE INDEX idx_observation_id ON agent_observations (observation_id);
```

### Observation Types

```python
class ObservationType(str, Enum):
    """Types of agent observations."""

    # Token tracking
    TOKEN_USAGE = "token_usage"

    # Tool lifecycle
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_BLOCKED = "tool_blocked"

    # Execution events
    PROMPT_SUBMITTED = "prompt_submitted"
    EXECUTION_STOPPED = "execution_stopped"
    SUBAGENT_STOPPED = "subagent_stopped"
    CONTEXT_COMPACTING = "context_compacting"

    # Progress tracking
    PROGRESS = "progress"
```

### Data Structure by Type

```python
# TOKEN_USAGE data field
{
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_creation_input_tokens": 2000,
    "cache_read_input_tokens": 8000,
    "model": "claude-sonnet-4-20250514"
}

# TOOL_STARTED data field
{
    "tool_name": "bash",
    "tool_use_id": "toolu_abc123",
    "input_preview": "git clone https://..."  # First 200 chars
    # Full input stored in MinIO: agent-operations/{session_id}/{tool_use_id}/input.json
}

# TOOL_COMPLETED data field
{
    "tool_name": "bash",
    "tool_use_id": "toolu_abc123",
    "success": true,
    "duration_ms": 1523,
    "output_preview": "Cloning into..."  # First 200 chars
    # Full output stored in MinIO: agent-operations/{session_id}/{tool_use_id}/output.txt
}
```

## Event Flow

### Before (Failed Approach)

```
Agent Runner → JSONL stdout → WorkflowExecutionEngine
    → AgentObservationEvent → event_store.append_events()
    → ❌ FAIL: "append precondition failed" (no aggregate)
```

### After (Correct Approach)

```
┌──────────────────────────────────────────────────────────────┐
│                    AGENT CONTAINER                            │
├──────────────────────────────────────────────────────────────┤
│  Agent Runner → JSONL stdout                                 │
│    {"type": "token_usage", "input_tokens": 1234, ...}       │
│    {"type": "tool_use", "tool_name": "bash", ...}           │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              WORKFLOW EXECUTION ENGINE                        │
├──────────────────────────────────────────────────────────────┤
│  Parse JSONL line → CREATE observation dict                  │
│                              │                                │
│                              ▼                                │
│  INSERT INTO agent_observations (time, session_id, ...)      │
│  VALUES (NOW(), 'session-123', ...)                          │
│                                                               │
│  ✓ No aggregate loading                                      │
│  ✓ No version conflicts                                      │
│  ✓ 20x faster writes                                         │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    PROJECTIONS                                │
├──────────────────────────────────────────────────────────────┤
│  CostProjection (reads from agent_observations)              │
│    SELECT                                                     │
│      SUM((data->>'input_tokens')::int) as total_input,      │
│      SUM((data->>'output_tokens')::int) as total_output     │
│    FROM agent_observations                                    │
│    WHERE session_id = ? AND observation_type = 'token_usage' │
│                                                               │
│  → Updates session_cost table (read model)                   │
└──────────────────────────────────────────────────────────────┘
```

## Consequences

### Positive

✅ **Correctness** - No longer violates event sourcing invariants

✅ **Performance** - 10x-100x better write throughput for observations

✅ **Cost Efficiency** - Automatic compression (90% reduction) and retention

✅ **Scalability** - Handles millions of observations per second

✅ **Simplicity** - Same PostgreSQL, no new infrastructure

✅ **Query Performance** - Time-series optimized queries (14,000x faster)

✅ **Industry Alignment** - How Uber, Netflix, LinkedIn handle observability

### Negative

⚠️ **Two Storage Systems** - Team must understand distinction

⚠️ **Migration Needed** - Existing code writes to event store

### Mitigations

1. **Clear Documentation** - This ADR + ADR-018 decision matrix
2. **ADR Updates** - Update ADR-015 and ADR-018 with new architecture
3. **Code Comments** - Explain storage choice at write sites
4. **Tests** - Validate both systems work correctly

## Implementation Plan

See `PROJECT-PLAN_20251216_TIMESCALEDB-OBSERVABILITY.md` for detailed implementation steps.

### Phase 1: Infrastructure (2 hours)

1. Add TimescaleDB to docker-compose
2. Create migration script for hypertable
3. Add compression and retention policies
4. Verify with test inserts

### Phase 2: Writer Implementation (3 hours)

1. Create `ObservabilityWriter` adapter
2. Update `WorkflowExecutionEngine` to INSERT directly
3. Add deduplication via UUID
4. Test with full workflow execution

### Phase 3: Projection Updates (2 hours)

1. Update `CostProjection` to query hypertable
2. Add time-bucket queries for aggregations
3. Test projection rebuild from observations

### Phase 4: E2E Validation (2 hours)

1. Run full github-pr workflow
2. Validate all observations persisted
3. Verify dashboard displays correct metrics
4. Check compression and retention policies

**Total Estimated Time: 8-10 hours**

## Future Enhancements

### OpenTelemetry Integration

```python
# Phase 2: Add OpenTelemetry instrumentation
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

# One-line integration with Claude SDK
AnthropicInstrumentor().instrument()

# Export to multiple backends
# - Jaeger (traces)
# - Prometheus (metrics)
# - DataDog (all-in-one)
```

### MinIO Conversation Storage

```python
# Phase 3: Store full content in MinIO
# TimescaleDB: Lightweight events + preview
# MinIO: Full conversation transcripts, tool I/O

INSERT INTO agent_observations (time, data) VALUES (
    NOW(),
    jsonb_build_object(
        'tool_name', 'bash',
        'input_preview', 'git clone https://...',  # First 200 chars
        'input_s3_key', 'agent-operations/session-123/input.json'  # Full content
    )
);
```

## Related ADRs

- **ADR-015**: Agent Session Observability (updated to reference TimescaleDB)
- **ADR-018**: Commands vs Observations (updated with storage decision)
- **ADR-017**: Scalable Event Collection (superseded by TimescaleDB approach)
- **ADR-007**: Event Store Integration (domain events only)

## References

- [TimescaleDB vs PostgreSQL Benchmarks](https://www.timescale.com/blog/timescaledb-vs-postgresql-time-series-database-6a696248104e/)
- [Uber's Time-Series Database Architecture](https://eng.uber.com/m3/)
- [Netflix's Observability at Scale](https://netflixtechblog.com/edgar-solving-mysteries-faster-with-observability-e1a76302c71f)
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/languages/python/)
