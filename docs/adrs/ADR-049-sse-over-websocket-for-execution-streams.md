# ADR-049: Server-Sent Events (SSE) for Real-Time Execution Streams

## Status

**Accepted** — 2026-03-21

## Context

The Syntropic137 dashboard and CLI require real-time streaming of domain events as workflows execute. Previously this was implemented using WebSocket endpoints (`/ws/executions/{id}`, `/ws/activity`, `/ws/health`, `/ws/control/{id}`).

The fundamental insight that drove this change: **execution observation is unidirectional**. Events flow server→client only. All control actions (pause, resume, cancel, inject) are fully covered by synchronous HTTP POST endpoints that the CLI and dashboard already use as the canonical interface. The bidirectional capability of WebSocket was unused for streaming, and the `/ws/control/{id}` endpoint that did accept commands was entirely redundant with existing HTTP endpoints.

### Problems with the WebSocket approach

1. **Over-engineered for the use case** — WebSocket is bidirectional; we only needed server→client streaming
2. **Protocol upgrade complexity** — Requires `Connection: Upgrade` + `Upgrade: websocket` headers; many proxies/load balancers need special configuration
3. **Manual reconnection logic** — Browser `WebSocket` has no built-in reconnect; every client had to implement exponential backoff manually
4. **Conflated concerns** — `/ws/control/{id}` mixed observation (event streaming) with control (command receipt), making the architecture harder to reason about
5. **Parallel infrastructure** — Separate connection pool management distinct from normal HTTP connection handling

## Decision

Replace all WebSocket streaming with **Server-Sent Events (SSE)** for observation, and retain HTTP POST for all control actions.

### New endpoints

```
GET /sse/executions/{execution_id}   — Domain events for one execution
GET /sse/activity                    — Global activity feed
GET /sse/health                      — Subscriber/connection counts
```

### Wire format (`text/event-stream`)

Each frame is a JSON-serialised `SSEEventFrame`:

```
data: {"type":"event","event_type":"PhaseStarted","execution_id":"exec-abc","data":{...},"timestamp":"2026-03-21T10:30:00Z"}

: keepalive

data: {"type":"terminal","event_type":"WorkflowCompleted",...}

```

### SSEEventFrame — typed envelope

```python
class SSEEventFrame(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["connected", "event", "terminal"]
    event_type: str
    execution_id: str | None = None
    data: dict[str, JsonValue]   # JsonValue = str | int | float | bool | None | list | dict
    timestamp: str
```

Three frame types:
- **`connected`** — handshake sent immediately on subscribe
- **`event`** — a domain event forwarded from the event store
- **`terminal`** — stream is closing (WorkflowCompleted / WorkflowFailed); client should not expect more events

### Terminal sentinel pattern

When a workflow ends, `RealTimeProjection.broadcast(..., terminal=True)` puts the `terminal` frame on the queue followed by a `None` sentinel. The route handler dequeues the frame, emits it to the client, then dequeues `None` and exits cleanly.

```python
# In RealTimeProjection
await queue.put(frame)       # terminal SSEEventFrame
await queue.put(None)        # sentinel — route handler exits loop
```

This gives clients an explicit, typed signal that the stream is done — not a dropped connection.

### Keepalive (30-second comment lines)

Long-lived streams are at risk of being closed by proxies with idle connection timeouts. Every 30 seconds without an event, the route emits:

```
: keepalive

```

SSE comment lines (`:`) are ignored by `EventSource.onmessage` — zero client-side overhead, resets proxy timers.

### RealTimeProjection — queue per subscriber

The projection maintains one `asyncio.Queue[SSEEventFrame | None]` per SSE client:

```python
_queues: dict[str, set[SSEQueue]]   # channel → subscriber queues
```

`connect(channel)` creates and returns a queue. `disconnect(channel, queue)` removes it in a `finally` block. No WebSocket library dependency; no protocol state machine.

### Control actions remain HTTP-only

```
POST /executions/{id}/pause
POST /executions/{id}/resume
POST /executions/{id}/cancel
POST /executions/{id}/inject
GET  /executions/{id}/state
```

These are the canonical control interfaces for CLI, dashboard, and programmatic clients. There is no bidirectional streaming for control, nor is one needed.

### Client implementations

**Browser (EventSource):**

```typescript
const source = new EventSource(`${API_BASE}/sse/executions/${executionId}`)

source.onmessage = (e: MessageEvent<string>) => {
  const frame = JSON.parse(e.data) as SSEEventFrame
  if (frame.type === 'terminal') source.close()
  else render(frame)
}
```

`EventSource` reconnects automatically on network interruption — no manual backoff loop.

**CLI (httpx streaming):**

```python
with get_streaming_client() as client:
    with client.stream("GET", f"/sse/executions/{id}") as resp:
        for line in resp.iter_lines():
            frame = parse_sse_line(line)
            if frame:
                render_event(frame)
```

`get_streaming_client()` uses `httpx.Timeout(connect=5.0, write=10.0, read=None, pool=5.0)` — finite connect timeout, unbounded read for long-lived streams.

### Vite dev proxy

SSE goes through the existing `/api/v1` proxy (which rewrites to the backend root). No separate WS proxy entries needed. The stale `/ws/*` proxy entries were removed.

## Consequences

### Positive

- **Simpler protocol** — HTTP GET; no upgrade handshake; no special proxy rules
- **Built-in browser reconnect** — `EventSource` handles exponential backoff natively
- **Type safety** — `SSEEventFrame` enforces schema at construction (`frozen`, `extra="forbid"`, `JsonValue`)
- **Clean separation** — observation (SSE GET) and control (HTTP POST) are distinct, discoverable interfaces
- **No extra dependencies** — `EventSource` is a browser native; CLI uses `httpx` which was already a dependency
- **Queue model** — `asyncio.Queue` per subscriber is simpler than managing WebSocket state machines

### Negative

- **Unidirectional only** — SSE cannot carry client→server messages. This is acceptable because control actions are HTTP. If a future use case genuinely requires bidirectional streaming, WebSocket can be reintroduced for that specific resource.
- **HTTP/1.1 connection limit** — Browsers cap concurrent connections per origin (typically 6). Multiple SSE tabs to the same origin share this budget. In practice this is not an issue since the dashboard opens at most one or two SSE connections.

## Removed components (ISS-262)

| Removed | Replacement |
|---|---|
| `GET /ws/executions/{id}` (WS) | `GET /sse/executions/{id}` |
| `GET /ws/activity` (WS) | `GET /sse/activity` |
| `GET /ws/health` (WS) | `GET /sse/health` |
| `GET /ws/control/{id}` (WS, bidirectional) | HTTP POST endpoints (already existed) |
| `routes/websocket.py` | `routes/sse.py` |
| `WeakSet[WebSocket]` in RealTimeProjection | `set[asyncio.Queue[SSEEventFrame \| None]]` |

## Related ADRs

- **ADR-010** — Event Subscription Architecture (RealTimeProjection section updated)
- **ADR-019** — WebSocket Control Plane (control WebSocket removed; HTTP endpoints are canonical)
- **ADR-044** — CLI-First Interface Design (`syn watch` uses SSE streaming)
