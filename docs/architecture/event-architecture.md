# Event Architecture: Domain vs Observability Events

**Last Updated:** 2026-01-29  
**Reference:** [ADR-018: Commands vs Observations](../adrs/ADR-018-commands-vs-observations-event-architecture.md), [ADR-030: Database Consolidation](../adrs/ADR-030-database-consolidation.md)

---

## Overview

Syn137 uses **two distinct event patterns** based on the nature of the data:

1. **Domain Events** (Full Event Sourcing) - For core business logic with validation
2. **Observability Events** (Event Log) - For high-volume telemetry and observations

Both patterns use **TimescaleDB as the unified database** (ADR-030), but with different tables and access patterns:

| Pattern | Table | Access Layer |
|---------|-------|--------------|
| Domain Events | `event_store.events` | Event Store Server (gRPC) |
| Observability Events | `public.agent_events` | Direct inserts (hypertable) |

This architectural distinction is fundamental to understanding how data flows through the system.

---

## The Two Patterns

```mermaid
flowchart TB
    subgraph domain["🔵 Domain Events (Full Event Sourcing)"]
        direction TB
        cmd1["📝 Command<br/>(Intent to change state)"]
        agg1["🏛️ Aggregate<br/>(Business logic + validation)"]
        evt1["✅ Domain Event<br/>(Validated fact)"]
        store1[("📚 TimescaleDB<br/>(via Event Store Server)")]
        
        cmd1 -->|"1. Validate against<br/>business rules"| agg1
        agg1 -->|"2. Emit after<br/>validation"| evt1
        evt1 -->|"3. Persist"| store1
        
        note1["Examples:<br/>• CreateWorkflow → WorkflowCreated<br/>• ExecuteWorkflow → ExecutionStarted<br/>• CompleteSession → SessionCompleted"]
        
        style cmd1 fill:#e3f2fd,color:#000
        style agg1 fill:#bbdefb,color:#000
        style evt1 fill:#90caf9,color:#000
        style store1 fill:#64b5f6,color:#000
    end
    
    subgraph obs["🟠 Observability Events (Event Log)"]
        direction TB
        obs1["👁️ Observation<br/>(External fact)"]
        val1["✔️ Validate Schema<br/>(+ Deduplication)"]
        evt2["📊 Observability Event<br/>(Recorded fact)"]
        store2[("⏱️ TimescaleDB<br/>(Time-series optimized)")]
        
        obs1 -->|"1. Already happened<br/>(no aggregate needed)"| val1
        val1 -->|"2. Validate + Dedup"| evt2
        evt2 -->|"3. Append to log"| store2
        
        note2["Examples:<br/>• ToolExecuted<br/>• TokensUsed<br/>• WorkspaceCreated<br/>• ErrorOccurred"]
        
        style obs1 fill:#fff3e0,color:#000
        style val1 fill:#ffe0b2,color:#000
        style evt2 fill:#ffcc80,color:#000
        style store2 fill:#ffb74d,color:#000
    end
    
    domain -.->|"Different patterns<br/>for different needs"| obs
```

---

## Key Differences

| Aspect | Domain Events | Observability Events |
|--------|--------------|---------------------|
| **Nature** | Intent that needs validation | Fact that already occurred |
| **Processing** | Command → Aggregate → Event | Observation → Direct append |
| **Validation** | Business rules enforced | Schema validation only |
| **Storage** | TimescaleDB (`event_store.events`) | TimescaleDB (`agent_events` hypertable) |
| **Access** | Event Store Server (gRPC) | Direct inserts |
| **Volume** | Low-to-medium | High volume |
| **Latency** | Can be higher (validation) | Must be low |
| **Aggregates** | Required | Not used |
| **State** | Maintains invariants | Stateless |

---

## Pattern 1: Domain Events (Full Event Sourcing)

### When to Use
- Core business logic with rules to enforce
- State transitions that need validation
- Operations that can be rejected
- Aggregate state must be consistent

### Characteristics
- **Commands are validated** against current aggregate state
- **Events emerge** from successful state transitions
- **Optimistic concurrency** via version numbers
- **Replay-able** - can rebuild state from events

### Example Flow: Workflow Creation

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Agg as WorkflowAggregate
    participant ES as Event Store Server
    
    Client->>API: POST /workflows<br/>(CreateWorkflow)
    API->>Agg: handle_create_workflow(cmd)
    
    Note over Agg: Validate business rules:<br/>- Unique workflow ID<br/>- Valid configuration<br/>- User has permission
    
    alt Validation Succeeds
        Agg->>Agg: Apply state change
        Agg->>ES: emit(WorkflowCreated)
        ES-->>API: Success
        API-->>Client: 201 Created
    else Validation Fails
        Agg-->>API: BusinessRuleViolation
        API-->>Client: 400 Bad Request
    end
```

### Examples in Syn137
- `CreateWorkflow` → `WorkflowAggregate` → `WorkflowCreated`
- `StartExecution` → `WorkflowExecutionAggregate` → `ExecutionStarted`
- `CompletePhase` → `WorkflowExecutionAggregate` → `PhaseCompleted`
- `StartSession` → `SessionAggregate` → `SessionStarted`

---

## Pattern 2: Observability Events (Event Log)

### When to Use
- High-volume telemetry collection
- External system observations
- Facts that already happened (can't be rejected)
- Performance-critical event collection

### Characteristics
- **No aggregate** - fact already occurred
- **Schema validation** only (structure, types, required fields)
- **Deduplication** via idempotency keys
- **Time-series optimized** storage
- **High throughput, low latency**

### Example Flow: Tool Execution Observation

```mermaid
sequenceDiagram
    participant Agent as Agent (in Docker)
    participant Collector as Event Collector API
    participant Valid as Schema Validator
    participant TS as TimescaleDB
    participant Proj as Projections
    
    Agent->>Collector: POST /events/observability<br/>(ToolExecuted)
    
    Note over Collector: Event already happened<br/>(can't be rejected)
    
    Collector->>Valid: validate_schema(event)
    
    alt Valid Schema
        Valid->>TS: append_to_log(event)
        TS-->>Collector: Ack
        Collector-->>Agent: 202 Accepted
        
        TS-->>Proj: Stream to projections
        Note over Proj: Update read models:<br/>- ToolTimelineProjection<br/>- TokenMetricsProjection
    else Invalid Schema
        Valid-->>Collector: SchemaError
        Collector-->>Agent: 400 Bad Request<br/>(log error, continue)
    end
```

### Examples in Syn137
- `ToolExecuted` - Agent used a tool
- `TokensUsed` - Token consumption recorded
- `WorkspaceCreated` - Workspace lifecycle event
- `ErrorOccurred` - Error observation
- `SubagentStarted` - Subagent spawned

---

## Why Two Patterns?

Both patterns use TimescaleDB, but with different access layers because the data has fundamentally different characteristics.

### The Problem with One-Size-Fits-All

**If we used Full ES (via Event Store Server) for everything:**
- ❌ Loading aggregates for every tool execution would be slow
- ❌ gRPC overhead for high-volume telemetry
- ❌ "Tool X executed" isn't a command - it's a fact

**If we used Direct Inserts for everything:**
- ❌ No way to enforce business rules
- ❌ No way to reject invalid commands
- ❌ Can't maintain aggregate invariants

### The Solution: Pattern Matching

> **Commands represent intent that needs validation** → Event Store Server (gRPC)  
> **Observations represent facts that already occurred** → Direct hypertable inserts

Choose the pattern that matches your use case. Both end up in TimescaleDB.

---

## Routing and Processing

```mermaid
flowchart LR
    subgraph sources["Event Sources"]
        cmd[Domain Commands]
        obs[Observability Events]
    end
    
    subgraph processing["Processing Layer"]
        agg[Aggregates<br/>Validation]
        collector[Event Collector<br/>Schema Validation]
    end
    
    subgraph storage["TimescaleDB (Unified)"]
        es[(event_store.events<br/>Domain Events)]
        ts[(agent_events<br/>Observability)]
    end
    
    subgraph projections["Read Side"]
        pm[Projection Manager]
        p1[Projections]
    end
    
    cmd --> agg
    agg -->|"via Event Store<br/>Server (gRPC)"| es
    
    obs --> collector
    collector -->|Direct Insert| ts
    
    es --> pm
    ts --> pm
    pm --> p1
    
    style es fill:#64b5f6,color:#000
    style ts fill:#ffb74d,color:#000
    style agg fill:#90caf9,color:#000
    style collector fill:#ffcc80,color:#000
```

---

## Storage Characteristics

Both event types are stored in **TimescaleDB** (ADR-030), but in separate tables with different characteristics:

### Domain Events (`event_store.events`)
- **Access:** Via Event Store Server (gRPC) for aggregate semantics
- **Optimized for:** Sequential writes, event replay, optimistic concurrency
- **Query patterns:** Get events by aggregate ID, stream all events
- **Retention:** Indefinite (source of truth for event sourcing)
- **Volume:** Lower (business events only)

### Observability Events (`agent_events` hypertable)
- **Access:** Direct inserts for maximum throughput
- **Optimized for:** High-volume time-series data, aggregations
- **Query patterns:** Time-range queries, aggregations, metrics
- **Retention:** Configurable (e.g., 90 days raw, longer for aggregates)
- **Volume:** High (all telemetry)
- **Features:** Auto-compression, time-based partitioning

---

## Migration Guide

### Choosing the Right Pattern

**Use Domain Events (Full ES) when:**
- ✅ You need to validate business rules
- ✅ Commands can be rejected
- ✅ Aggregate state must be consistent
- ✅ You need optimistic concurrency
- ✅ Volume is low-to-medium

**Use Observability Events (Event Log) when:**
- ✅ Facts already occurred (can't reject)
- ✅ High-volume telemetry
- ✅ Performance is critical
- ✅ Time-series queries needed
- ✅ No aggregate state to maintain

### Example Decision Tree

```mermaid
flowchart TD
    start[New Event Type]
    
    start --> q1{Can this be<br/>rejected?}
    q1 -->|Yes| domain[Domain Event<br/>Use Full ES]
    q1 -->|No| q2{Is this<br/>high-volume?}
    
    q2 -->|No| domain
    q2 -->|Yes| q3{Time-series<br/>queries needed?}
    
    q3 -->|Yes| obs[Observability Event<br/>Use Event Log]
    q3 -->|No| domain
    
    domain --> es[(event_store.events<br/>via gRPC)]
    obs --> ts[(agent_events<br/>direct insert)]
    
    subgraph db["TimescaleDB"]
        es
        ts
    end
    
    style domain fill:#90caf9,color:#000
    style obs fill:#ffcc80,color:#000
```

---

## Related Documentation

- [ADR-018: Commands vs Observations Event Architecture](../adrs/ADR-018-commands-vs-observations-event-architecture.md)
- [ADR-007: Event Store Integration](../adrs/ADR-007-event-store-integration.md)
- [ADR-026: TimescaleDB Observability Storage](../adrs/ADR-026-timescaledb-observability-storage.md)
- [ADR-030: Database Consolidation](../adrs/ADR-030-database-consolidation.md) - Unified TimescaleDB architecture
- [Event Flow Diagrams](./event-flows/README.md)
- [Infrastructure Data Flow](./infrastructure-data-flow.md)
