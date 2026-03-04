# Syn137 Event Collector

Scalable event collection for AI agent observability in the Syntropic137.

## Overview

The `syn-collector` package provides:

- **Event Collector Service** - FastAPI service for receiving batched events from agent sidecars
- **File Watchers** - Monitor hook JSONL and Claude transcripts for new events
- **HTTP Client** - Batched client for sidecars to post events with retry logic
- **Deduplication** - In-memory LRU filter for duplicate event detection

## Installation

```bash
# Part of the Syntropic137 monorepo
uv sync
```

## Usage

### Start Collector Service

```bash
# Start the collector service (requires TimescaleDB)
uv run syn-collector serve --port 8080 --db-url postgresql://syn:syn_dev_password@localhost:5432/syn

# Or via environment variable
SYN_OBSERVABILITY_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn uv run syn-collector serve --port 8080
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
SYN_OBSERVABILITY_DB_URL=postgresql://syn:syn_dev_password@localhost:5432/syn  # TimescaleDB connection
EVENT_COLLECTOR_URL=http://localhost:8080
EVENT_COLLECTOR_API_KEY=sk-xxx  # For cloud deployments
EVENT_BATCH_SIZE=100
EVENT_BATCH_INTERVAL_MS=1000
```

## Architecture

See [ADR-026: Simplified Observability Events](../../docs/adrs/ADR-026-simplified-observability-events.md) for the current storage architecture (TimescaleDB via `AgentEventStore`). [ADR-017](../../docs/adrs/ADR-017-scalable-event-collection-architecture.md) covers the original collection architecture (partially superseded).

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
                          │  - TimescaleDB Store (AgentEventStore)        │
                          └─────────────────────────────────────────────┘
```

## License

MIT
