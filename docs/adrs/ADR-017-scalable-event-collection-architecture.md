# ADR-017: Scalable Event Collection Architecture for Agent Observability

## Status

**Accepted** - 2025-12-09

## Context

The Agentic Engineering Framework (AEF) needs comprehensive observability for agent execution across multiple deployment environments. We require:

1. **Tool-level observability** - Track every tool call (started, completed, blocked) with metadata
2. **Token usage tracking** - Per-turn and cumulative token metrics from Claude transcripts
3. **User-in-the-loop tracking** - Count `UserPromptSubmit` events to measure human intervention
4. **Scale support** - Architecture must handle 1,000+ concurrent agents
5. **Multi-environment support** - Same pattern for local filesystem, Docker, and cloud sandboxes

### Current State

- **Claude Code Hooks** provide `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `SessionEnd` events
- Hooks receive `session_id`, `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, `transcript_path`
- **Hooks do NOT provide token usage data** - only tool execution metadata
- **Claude transcripts** (JSONL files at `~/.claude/projects/.../*.jsonl`) contain full token usage per message
- Existing `EventBridge` watches JSONL files locally but doesn't scale to distributed environments

### Key Constraints

1. Hooks are subprocess scripts - they execute quickly and exit
2. Token data is only in transcript files, not hook events
3. File watching doesn't work across network boundaries (cloud sandboxes)
4. Need deduplication to prevent duplicate events if retried
5. Must work with `uv` as the Python package manager/runner

## Decision Drivers

1. **Universality** - Same pattern across local/Docker/cloud environments
2. **Scalability** - Support 1,000+ concurrent agents on Mac Mini with Docker
3. **Simplicity** - HTTP-based communication (works everywhere)
4. **Reliability** - Deterministic deduplication via content hashing
5. **Observability** - Don't lose events due to network issues (retry with dedup)
6. **Performance** - Batch events to reduce network overhead

## Considered Options

### Option A: File Watcher Pattern (Current)

Each agent writes to JSONL → Central watcher monitors all files

**Pros**: Simple, existing implementation
**Cons**: Doesn't scale (OS file handle limits), doesn't work for cloud

### Option B: Direct Hook HTTP Emission

Hooks POST events directly to collector endpoint

**Pros**: Real-time, no intermediate files
**Cons**: Hooks are subprocesses (HTTP adds latency), can't read transcripts in hooks

### Option C: Sidecar + HTTP Collector (Selected)

Each agent environment has a lightweight sidecar that:
- Watches local hook JSONL and transcript files
- Batches and POSTs to a central Event Collector Service
- Uses deterministic event IDs for deduplication

**Pros**: Universal, scalable, simple HTTP protocol, handles both hook and transcript data
**Cons**: Requires sidecar process per agent container

### Option D: Message Queue (Kafka/Redis Streams)

Events flow through a message queue to event store

**Pros**: Highly scalable, proven at extreme scale
**Cons**: Infrastructure complexity, overkill for initial deployment

## Decision

**Selected: Option C - Sidecar + HTTP Collector Architecture**

This provides a universal pattern that works identically across all environments while maintaining simplicity.

### Two Agent Execution Patterns

**Important**: The event collection approach differs based on how the agent is executed:

#### Pattern A: CLI Agent (Interactive/File-based)

Used by: Claude Code CLI, human-in-the-loop development sessions

```
Claude Code CLI
    │ triggers
    ▼
File-based hooks (.claude/hooks/)
    │ write to
    ▼
.agentic/analytics/events.jsonl
    │ watched by
    ▼
Event Sidecar / File Watcher
    │ batches and posts
    ▼
Event Collector → Event Store
```

**Characteristics:**
- Human interactive sessions
- File-based hook scripts (Python/Shell)
- AnalyticsStreamer watches JSONL files
- Good for development/debugging

#### Pattern B: SDK Agent (Containerized/Stdout)

Used by: `claude-agent-sdk`, `aef-agent-runner`, production workloads

```
claude-agent-sdk query()
    │ yields
    ▼
ResultMessage (usage, content, tool blocks)
    │ processed by
    ▼
Agent Runner → emit_*() → stdout (JSONL)
    │ streamed by
    ▼
Orchestrator (reads container stdout)
    │ parses JSONL
    ▼
EventCollectorPort → Event Store
```

**Characteristics:**
- Programmatic, autonomous execution
- JSONL to stdout (industry standard for containerized agents)
- Orchestrator collects events from stdout stream
- Scales to 10,000+ concurrent agents

**Industry Alignment**: This stdout-based pattern aligns with:
- OpenAI Codex CLI architecture
- Langfuse/LangSmith agent tracing
- E2B sandbox observability

#### Pattern Selection Guide

| Criteria | Use Pattern A (File) | Use Pattern B (Stdout) |
|----------|---------------------|------------------------|
| Execution mode | Interactive CLI | Programmatic SDK |
| Environment | Local filesystem | Docker container |
| Hook type | Claude Code CLI hooks | SDK callbacks |
| Scalability | Single agent | 1000s of agents |
| Debugging | Rich file-based logs | Structured stdout |

### Architectural Pattern

This ADR implements **Pattern 2: Event Log + CQRS** as defined in [ADR-018](./ADR-018-commands-vs-observations-event-architecture.md).

Observability events (tool executions, token usage) are **observations of external facts**, not commands that need aggregate validation. They:

- Represent things that already happened (Claude executed a tool)
- Have no business rules to enforce (can't reject an observation)
- Are high-volume (every tool call, every message)

Therefore, we use the lightweight Event Log pattern:

1. **Validate schema** (Pydantic models)
2. **Generate deterministic event ID** (deduplication via content hash)
3. **Soft-validate session correlation** (warn if unknown session, still accept)
4. **Append to event store** (no aggregate loading required)

This provides all the benefits of event-driven architecture (replayability, audit trail, CQRS, VSA) without the overhead of aggregate-based event sourcing.

See [ADR-018](./ADR-018-commands-vs-observations-event-architecture.md) for the full architectural rationale and decision matrix.

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        UNIVERSAL EVENT COLLECTION PATTERN                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐         │
│   │  Agent Process   │    │  Agent Process   │    │  Agent Process   │         │
│   │  + Claude Hooks  │    │  + Claude Hooks  │    │  + Claude Hooks  │         │
│   │  + Transcript    │    │  + Transcript    │    │  + Transcript    │         │
│   └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘         │
│            │ writes                │ writes                │ writes             │
│            ▼                       ▼                       ▼                    │
│   ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐         │
│   │  Event Sidecar   │    │  Event Sidecar   │    │  Event Sidecar   │         │
│   │  - File watcher  │    │  - File watcher  │    │  - File watcher  │         │
│   │  - HTTP client   │    │  - HTTP client   │    │  - HTTP client   │         │
│   └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘         │
│            │                       │                       │                    │
│            └───────────────────────┼───────────────────────┘                    │
│                                    │ HTTP POST /events                          │
│                                    ▼                                            │
│            ┌─────────────────────────────────────────────────┐                 │
│            │           Event Collector Service                │                 │
│            │  - Receives batched events                       │                 │
│            │  - Deduplicates by event_id                      │                 │
│            │  - Writes to Event Store via gRPC                │                 │
│            └──────────────────────────┬──────────────────────┘                 │
│                                       │                                         │
│                                       ▼                                         │
│            ┌─────────────────────────────────────────────────┐                 │
│            │        Event Store (Rust gRPC + PostgreSQL)      │                 │
│            └──────────────────────────┬──────────────────────┘                 │
│                                       │                                         │
│                                       ▼                                         │
│            ┌─────────────────────────────────────────────────┐                 │
│            │     Subscription Service + Projections + UI      │                 │
│            └─────────────────────────────────────────────────┘                 │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Environment-Specific Deployment

| Environment | Event Sidecar | Collector URL | Notes |
|-------------|--------------|---------------|-------|
| **Local Filesystem** | Background daemon | `http://localhost:8080` | Run via `uv run aef-collector daemon` |
| **Local Docker** | Same container or sidecar container | `http://collector:8080` | Docker network |
| **Cloud Sandbox (E2B)** | Baked into agent image | `https://collector.aef.example.com` | HTTPS + API key auth |

### Event Sources

#### 1. Hook Events (Tool Observability)

Claude Code hooks write to `.agentic/analytics/events.jsonl`:

```json
{
  "event_type": "tool_execution_started",
  "session_id": "session-abc",
  "tool_name": "Read",
  "tool_input": {"file_path": "/src/main.py"},
  "tool_use_id": "toolu_01ABC...",
  "timestamp": "2025-12-09T10:30:00Z"
}
```

#### 2. Transcript Events (Token Observability)

Claude transcript at `~/.claude/projects/.../*.jsonl` contains:

```json
{
  "uuid": "8a5b0faf-6154-4ea9-84f1-5018a3a9cbc8",
  "type": "assistant",
  "message": {
    "usage": {
      "input_tokens": 2500,
      "output_tokens": 135,
      "cache_creation_input_tokens": 3936,
      "cache_read_input_tokens": 14161
    }
  },
  "timestamp": "2025-12-09T10:30:05Z"
}
```

### Deduplication Strategy

**Critical**: Events may be sent multiple times due to retries. We use deterministic event IDs based on content hashing.

```python
import hashlib
from datetime import datetime

def generate_event_id(
    session_id: str,
    event_type: str,
    timestamp: datetime,
    content_hash: str | None = None,
) -> str:
    """Generate deterministic event ID for deduplication.

    Same inputs → Same event_id → Deduplicated on insert
    """
    key_parts = [
        session_id,
        event_type,
        timestamp.isoformat(),
    ]
    if content_hash:
        key_parts.append(content_hash)

    key = "|".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# For tool events: hash includes tool_name + tool_use_id
event_id = generate_event_id(
    session_id="session-abc",
    event_type="tool_execution_started",
    timestamp=datetime(2025, 12, 9, 10, 30, 0),
    content_hash=hashlib.sha256(b"Read|toolu_01ABC").hexdigest()[:16],
)

# For token events: hash includes message UUID from transcript
event_id = generate_event_id(
    session_id="session-abc",
    event_type="token_usage",
    timestamp=datetime(2025, 12, 9, 10, 30, 5),
    content_hash="8a5b0faf",  # message.uuid from transcript
)
```

**Collector deduplication**:
- In-memory bloom filter for fast lookup
- Database UNIQUE constraint on `event_id` as fallback
- Returns `duplicates` count in response for observability

### HTTP API Contract

```
POST /events
Content-Type: application/json
Authorization: Bearer <api-key>  # Required for cloud, optional for local

{
  "agent_id": "agent-abc-123",
  "batch_id": "batch-001",
  "events": [
    {
      "event_id": "a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5",
      "event_type": "tool_execution_started",
      "session_id": "session-xyz",
      "timestamp": "2025-12-09T10:30:00Z",
      "data": {
        "tool_name": "Read",
        "tool_use_id": "toolu_01ABC...",
        "tool_input": {"file_path": "/src/main.py"}
      }
    },
    {
      "event_id": "b5h9d3e2f6g7h8i9j0k1l2m3n4o5p6q7",
      "event_type": "token_usage",
      "session_id": "session-xyz",
      "timestamp": "2025-12-09T10:30:05Z",
      "data": {
        "message_uuid": "8a5b0faf-6154-4ea9-84f1-5018a3a9cbc8",
        "input_tokens": 2500,
        "output_tokens": 135,
        "cache_creation_input_tokens": 3936,
        "cache_read_input_tokens": 14161
      }
    }
  ]
}

Response:
{
  "accepted": 2,
  "duplicates": 0,
  "batch_id": "batch-001"
}
```

### Event Types

| Event Type | Source | Data Fields |
|------------|--------|-------------|
| `session_started` | Hook | `session_id`, `start_type` |
| `session_ended` | Hook | `session_id`, `reason` |
| `tool_execution_started` | Hook | `session_id`, `tool_name`, `tool_use_id`, `tool_input` |
| `tool_execution_completed` | Hook | `session_id`, `tool_name`, `tool_use_id`, `tool_response`, `duration_ms` |
| `tool_blocked` | Hook | `session_id`, `tool_name`, `tool_use_id`, `reason` |
| `user_prompt_submitted` | Hook | `session_id`, `prompt_length` |
| `token_usage` | Transcript | `session_id`, `message_uuid`, `input_tokens`, `output_tokens`, `cache_*` |
| `pre_compact` | Hook | `session_id`, `trigger` (manual/auto) |

## Consequences

### Positive

✅ **Universal** - Same pattern works for local, Docker, and cloud environments

✅ **Scalable** - HTTP-based, stateless collector handles 1000+ agents easily

✅ **Reliable** - Deterministic deduplication prevents duplicate events

✅ **Observable** - Full tool + token metrics from both hooks and transcripts

✅ **Simple** - HTTP is universally supported, no complex infrastructure

✅ **Composable** - Sidecar can be a daemon, container, or baked into image

### Negative

⚠️ **Additional Process** - Requires running event sidecar alongside agent

⚠️ **Latency** - Events are batched (1s default), not instant

⚠️ **File Watching** - Sidecar must watch two different file formats

### Mitigations

1. **Sidecar complexity** - Provide `aef-collector` CLI with `daemon`, `watch`, `serve` commands
2. **Latency** - Configurable batch interval (100ms for real-time needs)
3. **File formats** - Unified watcher library handles both JSONL formats

## Implementation

### Package Structure

```
packages/aef-collector/
├── pyproject.toml
├── src/
│   └── aef_collector/
│       ├── __init__.py
│       ├── cli.py              # Click CLI (daemon, watch, serve)
│       ├── watcher/
│       │   ├── __init__.py
│       │   ├── hooks.py        # Hook JSONL watcher
│       │   └── transcript.py   # Claude transcript watcher
│       ├── collector/
│       │   ├── __init__.py
│       │   ├── service.py      # FastAPI service
│       │   ├── dedup.py        # Deduplication logic
│       │   └── store.py        # Event store writer
│       ├── events/
│       │   ├── __init__.py
│       │   ├── types.py        # Event type definitions
│       │   └── ids.py          # Event ID generation
│       └── client/
│           ├── __init__.py
│           └── http.py         # HTTP client for posting events
└── tests/
```

### CLI Commands

```bash
# Start collector service (receives events, writes to event store)
uv run aef-collector serve --port 8080 --eventstore-host localhost

# Start file watcher daemon (watches files, posts to collector)
uv run aef-collector watch \
  --hooks-file .agentic/analytics/events.jsonl \
  --transcript-dir ~/.claude/projects/ \
  --collector-url http://localhost:8080

# Start as background daemon
uv run aef-collector daemon start

# For Docker: combined mode
uv run aef-collector sidecar \
  --hooks-file /app/.agentic/analytics/events.jsonl \
  --transcript-dir /root/.claude/projects/ \
  --collector-url http://collector:8080
```

### Configuration

Environment variables:
```bash
# Collector URL (configurable per environment)
EVENT_COLLECTOR_URL=http://localhost:8080

# For cloud environments
EVENT_COLLECTOR_API_KEY=sk-xxx

# Event store connection
EVENTSTORE_HOST=localhost
EVENTSTORE_PORT=50051
EVENTSTORE_TENANT_ID=aef

# Sidecar settings
EVENT_BATCH_SIZE=100
EVENT_BATCH_INTERVAL_MS=1000
```

## Migration Path

1. **Phase 1**: Build `aef-collector` package with CLI
2. **Phase 2**: Deploy collector service alongside existing dashboard
3. **Phase 3**: Add sidecar to Docker agent images
4. **Phase 4**: Configure cloud sandbox images with sidecar + API key

## Future Evolution

This architecture provides a foundation for:

1. **Message Queue Integration** - Add Kafka/Redis Streams between collector and event store for extreme scale
2. **Edge Caching** - Deploy collector replicas closer to agents in different regions
3. **Real-time Streaming** - WebSocket/SSE from collector directly to UI (bypass event store for live data)

## Related ADRs

- [ADR-007: Event Store Integration](./ADR-007-event-store-integration.md)
- [ADR-010: Event Subscription Architecture](./ADR-010-event-subscription-architecture.md)
- [ADR-015: Agent Session Observability](./ADR-015-agent-observability.md)
- [ADR-016: UI Feedback Module](./ADR-016-ui-feedback-module.md)
- [ADR-018: Commands vs Observations](./ADR-018-commands-vs-observations-event-architecture.md) - Architectural pattern used

## References

- Claude Code Hooks Documentation: https://code.claude.com/docs/en/hooks
- Claude Code Transcript Format: `~/.claude/projects/.../*.jsonl`
- Existing EventBridge: `packages/aef-adapters/src/aef_adapters/events/bridge.py`

---

## Implementation

**PROJECT PLAN**: See `PROJECT-PLAN_20251209_scalable-observability.md` in the repository root for detailed implementation milestones, code examples, and acceptance criteria.

### Quick Start for Implementation

1. Read this ADR fully
2. Read the Pre-Execution Context section of the PROJECT-PLAN
3. Start with Milestone 1: Core Package Structure
4. Follow the QA checkpoint process after each milestone

### Key Files to Reference

| Existing Code | Purpose |
|--------------|---------|
| `packages/aef-adapters/src/aef_adapters/events/watcher.py` | File watching pattern to extend |
| `packages/aef-adapters/src/aef_adapters/events/bridge.py` | Event bridging pattern |
| `packages/aef-adapters/src/aef_adapters/hooks/client.py` | HTTP client pattern |
| `lib/agentic-primitives/primitives/v1/hooks/handlers/` | Existing hook implementations |
