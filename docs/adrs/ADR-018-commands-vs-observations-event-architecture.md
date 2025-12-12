# ADR-018: Commands vs Observations in Event-Driven Architecture

## Status

**Accepted** - 2025-12-09

## Context

The Agentic Engineering Framework uses event-driven architecture with Event Sourcing (ES) and CQRS. During implementation of the scalable observability system (ADR-017), we identified a fundamental architectural distinction that was not previously documented:

**Not all events are created equal.**

Some events represent the **outcome of validated commands** (domain events), while others represent **observations of external facts** (observability events). These require different architectural patterns.

### The Problem

Our initial collector design (ADR-017) proposed writing observability events directly to the event store. This raised concerns:

1. **Aggregate Bypass**: Full ES requires events to be emitted by aggregates after command validation
2. **Performance**: Loading aggregates for every tool execution observation would be prohibitively slow
3. **Semantic Mismatch**: "Tool X executed" isn't a command - it's a fact that already happened

### Key Insight

> **Commands represent intent that needs validation.**
> **Observations represent facts that already occurred.**

Trying to force observations through the aggregate pattern creates unnecessary complexity and violates the semantic model.

## Decision

We adopt **two distinct event patterns** based on the nature of the data:

### Pattern 1: Full Event Sourcing (Domain Events)

**Use for:** Core domain logic with business rules

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Command    │ ──► │  Aggregate   │ ──► │ Domain Event │ ──► │ Event Store  │
│  (Intent)    │     │ (Validates)  │     │   (Fact)     │     │              │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                            │
                            ▼
                     Business Rules
                     Enforced Here
```

**Characteristics:**

- Events emerge from aggregate state transitions
- Commands are validated against business rules
- Aggregates maintain invariants
- Optimistic concurrency via version numbers

**Examples:**

- `CreateWorkflow` → `WorkflowAggregate` → `WorkflowCreated`
- `CompletePhase` → `WorkflowExecutionAggregate` → `PhaseCompleted`
- `StartSession` → `SessionAggregate` → `SessionStarted`

### Pattern 2: Event Log + CQRS (Observability Events)

**Use for:** High-volume telemetry and external observations

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Observation  │ ──► │   Validate   │ ──► │  Append to   │ ──► │ Event Store  │
│   (Fact)     │     │   Schema +   │     │  Event Log   │     │              │
└──────────────┘     │   Dedup ID   │     └──────────────┘     └──────────────┘
                     └──────────────┘
                            │
                            ▼
                     No Aggregate
                     (Already happened)
```

**Characteristics:**

- Events represent observations of external systems
- Schema validation only (no business rules)
- No aggregate loading (high throughput)
- Deduplication via deterministic content hashing

**Examples:**

- `ToolExecutionObserved` - Claude executed a tool
- `TokenUsageObserved` - Claude consumed tokens
- `UserPromptObserved` - User submitted a prompt

## Decision Matrix

| Question | If Yes → | If No → |
|----------|----------|---------|
| Does this represent user/system **intent**? | Pattern 1 (Full ES) | Pattern 2 (Event Log) |
| Are there **business rules** to enforce? | Pattern 1 (Full ES) | Pattern 2 (Event Log) |
| Can the operation be **rejected** based on current state? | Pattern 1 (Full ES) | Pattern 2 (Event Log) |
| Is this recording something that **already happened externally**? | Pattern 2 (Event Log) | Pattern 1 (Full ES) |
| Is this **high-volume telemetry** (>100 events/sec)? | Pattern 2 (Event Log) | Consider either |
| Does the event need to **update aggregate state**? | Pattern 1 (Full ES) | Pattern 2 (Event Log) |

### Quick Reference

| Data Type | Pattern | Rationale |
|-----------|---------|-----------|
| Workflow creation | **Pattern 1** | Business rules (name required, phases valid) |
| Phase completion | **Pattern 1** | State machine (can't complete before start) |
| Session lifecycle | **Pattern 1** | Aggregate tracks session state |
| Tool execution tracking | **Pattern 2** | Observation of external fact |
| Token usage tracking | **Pattern 2** | High-volume telemetry |
| User prompt events | **Pattern 2** | Observation (prompt already submitted) |
| **Cost tracking** | **Pattern 2** | Derived from token/tool observations, aggregated via projections |

## Deduplication Invariant

Even without aggregates, observability events maintain **one critical invariant**:

> **The same observation cannot be recorded twice.**

### Implementation: Deterministic Event IDs

```python
import hashlib
from datetime import datetime

def generate_observation_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    content_fingerprint: str,
) -> str:
    """Generate deterministic ID for deduplication.

    Same inputs → Same ID → Deduplicated on insert

    The content_fingerprint should uniquely identify the observation:
    - For tool events: tool_use_id (provided by Claude)
    - For token events: message_uuid (from transcript)
    - For custom events: hash of payload
    """
    key = f"{session_id}|{event_type}|{timestamp.isoformat()}|{content_fingerprint}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]
```

### Content Fingerprint by Event Type

| Event Type | Content Fingerprint Source |
|------------|---------------------------|
| `tool_execution_started` | `tool_use_id` (from Claude) |
| `tool_execution_completed` | `tool_use_id` (from Claude) |
| `tool_blocked` | `tool_use_id` (from Claude) |
| `token_usage` | `message_uuid` (from transcript) |
| `user_prompt_submitted` | `sha256(prompt_content)[:16]` |
| `session_started` | `session_id` (self-referential) |
| `session_ended` | `session_id + end_reason` |

### Deduplication Enforcement

1. **Application Layer**: In-memory LRU cache for fast duplicate detection
2. **Database Layer**: UNIQUE constraint on `event_id` as fallback
3. **Idempotent Retries**: Clients can safely retry failed sends

## Session Correlation (Soft Validation)

Observability events SHOULD include a `session_id` to correlate with domain sessions.

### Validation Strategy: Warn, Don't Reject

```python
async def ingest_observation(event: ObservabilityEvent) -> IngestResult:
    """Ingest an observation event with soft session validation."""

    # 1. Schema validation (HARD - reject if invalid)
    validated = ObservationSchema.validate(event)

    # 2. Deduplication check (HARD - skip if duplicate)
    if await dedup_filter.is_duplicate(validated.event_id):
        return IngestResult(status="duplicate", event_id=validated.event_id)

    # 3. Session correlation (SOFT - warn if unknown, still accept)
    if validated.session_id:
        session_exists = await session_lookup.exists(validated.session_id)
        if not session_exists:
            logger.warning(
                "Observation references unknown session",
                event_id=validated.event_id,
                session_id=validated.session_id,
            )
            # Still accept - eventual consistency

    # 4. Append to event log (no aggregate)
    await event_store.append(validated)
    return IngestResult(status="accepted", event_id=validated.event_id)
```

### Rationale for Soft Validation

| Approach | Pros | Cons |
|----------|------|------|
| **Hard reject** if session unknown | Data integrity | Race conditions, ordering issues |
| **Soft warn** if session unknown (✅ Selected) | Resilient to timing | May have orphan observations |

We choose **soft validation** because:

1. **Timing**: Session creation event may arrive after tool observations (network ordering)
2. **External Systems**: Observations may come from systems we don't control
3. **Resilience**: Better to have orphan data than lose observations
4. **Queryable**: Projections can filter/flag observations with unknown sessions

## Benefits Preserved

Both patterns provide the core benefits of event-driven architecture:

| Benefit | Pattern 1 (Full ES) | Pattern 2 (Event Log) |
|---------|--------------------|-----------------------|
| **Replayability** | ✅ Rebuild aggregate state | ✅ Rebuild projections |
| **Audit Trail** | ✅ Complete command history | ✅ Complete observation history |
| **CQRS** | ✅ Projections for reads | ✅ Projections for reads |
| **VSA** | ✅ Vertical slices | ✅ Vertical slices |
| **Temporal Queries** | ✅ "State at time X" | ✅ "What happened at time X" |

## Consequences

### Positive

✅ **Clarity**: Clear guidance on when to use each pattern

✅ **Performance**: Observability doesn't pay aggregate loading cost

✅ **Semantic Accuracy**: Events match their true nature (command vs observation)

✅ **Scalability**: Pattern 2 handles high-volume telemetry efficiently

✅ **Preserved Benefits**: Both patterns maintain ES/CQRS advantages

### Negative

⚠️ **Two Mental Models**: Team must understand both patterns

⚠️ **Potential Confusion**: Risk of using wrong pattern for given use case

### Mitigations

1. **Decision Matrix**: Clear criteria for pattern selection (see above)
2. **Code Reviews**: Verify pattern choice during PR review
3. **Documentation**: This ADR + inline code comments

## Implementation Guidelines

### For Pattern 1 (Full ES)

Follow existing patterns in ADR-003:

```python
@aggregate("Workflow")
class WorkflowAggregate(AggregateRoot):
    @command_handler("CreateWorkflow")
    def create(self, cmd: CreateWorkflowCommand) -> None:
        # Validate business rules
        if not cmd.name:
            raise ValueError("Workflow name required")
        # Emit event
        self._apply(WorkflowCreatedEvent(...))
```

### For Pattern 2 (Event Log)

Use the collector service from ADR-017:

```python
# Observation comes from external source (file watcher, webhook, etc.)
observation = ToolExecutionObserved(
    event_id=generate_observation_id(...),  # Deterministic!
    session_id="session-123",
    tool_name="Read",
    tool_use_id="toolu_abc",
    timestamp=datetime.now(UTC),
)

# Validate schema + dedup + append (no aggregate)
await collector.ingest(observation)
```

## Pattern 2 Implementation: Cost Tracking

The `costs` VSA context is a complete implementation of Pattern 2, demonstrating how to:

1. **Derive events** from existing observations (token usage → cost calculation)
2. **Aggregate via projections** (session costs → execution costs)
3. **Build read models** for efficient querying

### Cost Tracking Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  token_usage event  │ ──► │   CostCalculator    │ ──► │  CostRecordedEvent  │
│  (from collector)   │     │   (applies pricing) │     │   (per LLM call)    │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
                                                                  │
┌─────────────────────┐                                          │
│ tool_execution event│ ──► CostCalculator ──► CostRecordedEvent─┘
└─────────────────────┘                                          │
                                                                  ▼
                                                        ┌─────────────────────┐
                                                        │    Event Store      │
                                                        └─────────────────────┘
                                                                  │
                          ┌───────────────────────────────────────┤
                          ▼                                       ▼
                ┌─────────────────────┐             ┌─────────────────────┐
                │ SessionCostProjection│             │ExecutionCostProjection│
                │   (per-session)      │             │   (aggregates)      │
                └─────────────────────┘             └─────────────────────┘
                          │                                       │
                          ▼                                       ▼
                ┌─────────────────────┐             ┌─────────────────────┐
                │   SessionCost       │             │   ExecutionCost     │
                │   (read model)      │             │   (read model)      │
                └─────────────────────┘             └─────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Session as atomic unit** | Costs are tracked per-session, then aggregated upward |
| **CostRecordedEvent per cost** | Fine-grained events enable rich analytics |
| **SessionCostFinalizedEvent** | Captures final totals when session ends |
| **Decimal precision** | USD amounts stored as `Decimal` to avoid float errors |
| **Model pricing lookup** | `ModelPricing` value objects with per-model rates |

### Cost Hierarchy

```
ExecutionCost (aggregated)
    └── SessionCost (atomic unit)
            └── CostRecordedEvent (individual cost)
                    ├── llm_tokens (from token_usage)
                    └── tool_execution (from tool events)
```

This demonstrates Pattern 2's power: deriving business value (cost tracking) from raw observations (token usage) without requiring aggregates.

## Related ADRs

- **ADR-003**: Event Sourcing Decorators (Pattern 1 implementation)
- **ADR-007**: Event Store Integration (storage layer for both patterns)
- **ADR-008**: VSA Projection Architecture (read side for both patterns)
- **ADR-013**: Projection Consistency (applies to both patterns)
- **ADR-017**: Scalable Event Collection (uses Pattern 2)

## References

- [Event Sourcing Pattern](https://martinfowler.com/eaaDev/EventSourcing.html)
- [CQRS Pattern](https://martinfowler.com/bliki/CQRS.html)
- [Domain Events vs Integration Events](https://docs.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/domain-events-design-implementation)
