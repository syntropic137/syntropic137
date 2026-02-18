# AEF Event Collector

Scalable event collection for AI agent observability in the Syntropic137.

## Overview

The `syn-collector` package provides:

- **Event Collector Service** - FastAPI service for receiving batched events from agent sidecars
- **File Watchers** - Monitor hook JSONL and Claude transcripts for new events
- **HTTP Client** - Batched client for sidecars to post events with retry logic
- **Deduplication** - In-memory LRU filter for duplicate event detection

## Installation

```bash
# Part of the AEF monorepo
uv sync
```

## Usage

### Start Collector Service

```bash
# Start the collector service
uv run syn-collector serve --port 8080

# With event store connection
uv run syn-collector serve --port 8080 --eventstore-host localhost --eventstore-port 50051
```

### Start File Watcher (Sidecar)

```bash
# Watch hook events and transcripts, send to collector
uv run syn-collector watch \
    --hooks-file .agentic/analytics/events.jsonl \
    --transcript-dir ~/.claude/projects/ \
    --collector-url http://localhost:8080
```

### Sidecar Mode (Docker)

```bash
# Combined mode with container-friendly defaults
uv run syn-collector sidecar \
    --hooks-file /app/.agentic/analytics/events.jsonl \
    --transcript-dir /root/.claude/projects/ \
    --collector-url http://collector:8080
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | POST | Receive batched events |
| `/health` | GET | Health check |
| `/stats` | GET | Deduplication statistics |
| `/reset` | POST | Reset collector state (testing) |

## Event Types

| Event Type | Source | Description |
|------------|--------|-------------|
| `session_started` | Hook | Agent session begins |
| `session_ended` | Hook | Agent session ends |
| `tool_execution_started` | Hook | Tool call initiated |
| `tool_execution_completed` | Hook | Tool call finished |
| `tool_blocked` | Hook | Tool call blocked |
| `user_prompt_submitted` | Hook | User submitted prompt |
| `token_usage` | Transcript | Per-turn token metrics |
| `pre_compact` | Hook | Context compaction triggered |

## Configuration

Environment variables:

```bash
EVENT_COLLECTOR_URL=http://localhost:8080
EVENT_COLLECTOR_API_KEY=sk-xxx  # For cloud deployments
EVENTSTORE_HOST=localhost
EVENTSTORE_PORT=50051
EVENT_BATCH_SIZE=100
EVENT_BATCH_INTERVAL_MS=1000
```

## Architecture

See [ADR-017: Scalable Event Collection Architecture](../../docs/adrs/ADR-017-scalable-event-collection-architecture.md) for detailed architecture documentation.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      AGENT EXECUTION ENVIRONMENT                         │
│   ┌─────────────────┐     ┌──────────────────────────────────────────┐  │
│   │  Claude Agent   │     │         Event Sidecar                     │  │
│   │  + Hooks        │────▶│  - Hook Watcher (events.jsonl)           │  │
│   │  + Transcript   │     │  - Transcript Watcher (~/.claude/...)    │  │
│   └─────────────────┘     │  - HTTP Client (batched)                 │  │
│                           └────────────────────┬─────────────────────┘  │
└────────────────────────────────────────────────┼────────────────────────┘
                                                 │ HTTP POST /events
                                                 ▼
                          ┌─────────────────────────────────────────────┐
                          │       Event Collector Service                │
                          │  - FastAPI Server                           │
                          │  - Deduplication Filter                      │
                          │  - Event Store Writer                        │
                          └─────────────────────────────────────────────┘
```

## License

MIT
