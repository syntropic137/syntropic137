# ADR-035: Agent Output Data Model and Storage

## Status

**Proposed** - 2025-12-20

## Context

When an AI agent executes inside a container, it produces **three distinct types of output data**, each with different storage needs and use cases:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Agent Output Data Types                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. OBSERVABILITY EVENTS                                            │
│     ├── tool_execution_started/completed                            │
│     ├── token_usage                                                 │
│     └── session lifecycle                                           │
│     Purpose: Real-time metrics, dashboards, cost tracking           │
│     Storage: TimescaleDB (agent_events table)                       │
│     Access: SQL queries, time-series aggregation                    │
│                                                                      │
│  2. CONVERSATION LOGS                                               │
│     ├── Full JSONL stream from agent                                │
│     ├── Complete reasoning chains                                   │
│     ├── Full tool inputs/outputs                                    │
│     └── Message history                                             │
│     Purpose: ML training, debugging, vectorization, learning        │
│     Storage: MinIO/S3 (aef-conversations bucket)                    │
│     Access: Download, crawl, batch processing                       │
│                                                                      │
│  3. EXECUTION LOGS (future)                                         │
│     ├── Container stdout/stderr                                     │
│     ├── System-level events                                         │
│     └── Error traces                                                │
│     Purpose: Debugging, operations                                  │
│     Storage: TBD (possibly Loki or S3)                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Separation of Concerns

Each data type has fundamentally different:
- **Access patterns** (real-time queries vs batch processing)
- **Retention requirements** (days vs months)
- **Storage costs** (DB rows vs object files)
- **Use cases** (dashboards vs ML pipelines)

## Decision

### 1. Clean Interface from agentic-primitives

The `agentic-primitives` library provides a **clean abstraction** for AEF to consume. AEF doesn't need to understand Claude CLI internals:

```python
# In agentic-primitives (Claude CLI specific for now)
class SessionOutputStream:
    """Stream of structured outputs from an agent session.

    AEF consumes this without knowing how Claude CLI works internally.
    """

    @property
    def session_id(self) -> str:
        """Session identifier for correlation."""
        ...

    async def events(self) -> AsyncIterator[ObservabilityEvent]:
        """Stream of parsed observability events.

        Yields normalized events ready for TimescaleDB insertion.
        Tool names are already enriched (no caching needed by consumer).
        """
        ...

    async def raw_lines(self) -> AsyncIterator[str]:
        """Stream of raw JSONL lines for conversation storage.

        Full fidelity - nothing parsed or modified.
        Consumer can store directly to S3.
        """
        ...

    async def summary(self) -> SessionSummary:
        """Final summary after session completes.

        Includes: tool counts, token totals, duration, success.
        """
        ...
```

### 2. AEF Integration

AEF integrates cleanly without understanding container internals:

```python
# In AEF WorkflowExecutionEngine
async def execute_phase(self, phase: WorkflowPhase) -> PhaseResult:
    # Get structured output stream from workspace
    output_stream = await workspace.run_agent(task=phase.task)

    # Tee the raw lines to S3 while also processing events
    conversation_buffer: list[str] = []

    async for line in output_stream.raw_lines():
        conversation_buffer.append(line)

    # Store conversation log (full JSONL)
    await self._conversation_storage.store_session(
        session_id=output_stream.session_id,
        lines=conversation_buffer,
        context=SessionContext(
            execution_id=ctx.execution_id,
            phase_id=phase.phase_id,
            workflow_id=ctx.workflow_id,
        ),
    )

    # Observability events already stored during streaming
    # (handled by workspace internally or via separate consumer)

    return PhaseResult(
        summary=await output_stream.summary(),
    )
```

### 3. Storage by Session

**Session is the atomic unit.** Projections aggregate upward.

```
MinIO: aef-conversations/
└── sessions/
    └── {session_id}/
        └── conversation.jsonl      # Complete JSONL

TimescaleDB:
├── agent_events                    # Observability (real-time)
└── session_conversations           # Index for S3 objects
    ├── session_id (PK)
    ├── execution_id, phase_id      # Correlation
    ├── object_key                  # S3 reference
    ├── tool_counts (JSONB)         # {"Bash": 5, "Read": 3}
    ├── total_tokens
    └── started_at, completed_at
```

### 4. Projections for Analytics

```sql
-- Materialized view: aggregate sessions by execution
CREATE MATERIALIZED VIEW execution_sessions AS
SELECT
    execution_id,
    workflow_id,
    array_agg(session_id ORDER BY started_at) as sessions,
    SUM(total_input_tokens) as total_input_tokens,
    SUM(total_output_tokens) as total_output_tokens,
    jsonb_merge_agg(tool_counts) as tool_counts
FROM session_conversations
GROUP BY execution_id, workflow_id;
```

## Implementation

### Phase 1: Capture in agentic-primitives (Claude CLI)

Add to `agentic-primitives/lib/python/agentic_isolation/`:

```
agentic_isolation/
├── providers/
│   ├── docker.py              # Existing
│   └── claude_cli/            # NEW: Claude CLI specific
│       ├── __init__.py
│       ├── output_stream.py   # SessionOutputStream impl
│       └── event_parser.py    # JSONL → ObservabilityEvent
```

This keeps Claude CLI specifics isolated while providing clean interface.

### Phase 2: AEF Integration

- Add `ConversationStoragePort` and MinIO adapter
- Create `session_conversations` table
- Wire into `WorkflowExecutionEngine`

### Phase 3: Projections and Analytics

- Materialized views for execution/workflow aggregation
- API endpoints for conversation retrieval
- Batch export for ML pipelines

## Consequences

### Positive

1. **Clean separation** - Three data types, three purposes, three storage mechanisms
2. **AEF stays simple** - Consumes structured interface, doesn't parse JSONL
3. **Full fidelity** - Conversation logs preserved for ML/learning
4. **Queryable metrics** - Observability events in TimescaleDB
5. **Future-proof** - Can add other agents by implementing same interface

### Negative

1. **Dual write** - Events go to DB, conversations go to S3
2. **Implementation effort** - Need to build the abstraction layer

### Neutral

1. **Claude CLI specific for now** - Will abstract when adding other agents
2. **Eventually consistent** - S3 index may lag briefly

## Related ADRs

- [ADR-012: Artifact Storage](./ADR-012-artifact-storage.md) - Same MinIO infrastructure
- [ADR-026: TimescaleDB](./ADR-026-timescaledb-observability-storage.md) - Observability storage
- [ADR-030: Database Consolidation](./ADR-030-database-consolidation.md) - Single DB architecture
