# OpenCode Plugin-Based Observability

> **Status:** Architecture Complete - Ready for Implementation
> **Related Issue:** [#51 - OpenCode Integration](https://github.com/syntropic137/syntropic137/issues/51)
> **Related ADRs:** ADR-038 (planned)

## Overview

OpenCode uses a **plugin system** to extend functionality and capture events. This document describes how Syn137 leverages OpenCode's plugin architecture to achieve full observability without depending on upstream telemetry features.

## Why Plugins > Waiting for Native Observability

**Previous Understanding:** OpenCode lacked native observability APIs (like Claude CLI's JSONL stdout).

**Reality:** OpenCode provides a comprehensive plugin system with event hooks that enable **building observability ourselves**.

### Benefits of Plugin Approach

- ✅ **Zero upstream dependencies** - works with OpenCode today
- ✅ **Full control** - capture exactly what Syn137 needs
- ✅ **Custom event schema** - map directly to Syn137 domain events
- ✅ **Security enforcement** - block unsafe operations at plugin layer
- ✅ **No performance overhead** - async event emission
- ✅ **Production-ready** - no experimental features required

## OpenCode Plugin Architecture

### Plugin Structure

Plugins are TypeScript/JavaScript modules that export plugin functions:

```typescript
import type { Plugin } from "@opencode-ai/plugin"

export const MyPlugin: Plugin = async (ctx) => {
  // ctx includes: project, client, $, directory, worktree

  return {
    // Event hooks
    "tool.execute.before": async (input, output) => { ... },
    "tool.execute.after": async (input, output) => { ... },
    // ... more hooks
  }
}
```

### Context Object

Plugins receive a context object with:

- `project`: Current project information
- `client`: OpenCode SDK client for API interactions
- `$`: Bun's shell API for executing commands
- `directory`: Current working directory
- `worktree`: Git worktree path

### Plugin Loading

**Local Plugins:**
- `.opencode/plugin/` (project-level)
- `~/.config/opencode/plugin/` (global)

**npm Plugins:**
```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["@syn137/opencode-plugin", "opencode-skills"]
}
```

Plugins are loaded in sequence. Bun automatically installs npm packages at startup.

## Available Events

Reference: [OpenCode Plugin Documentation](https://opencode.ai/docs/plugins/)

### Tool Events (Critical for Syn137)

| Event | When Fired | Use Case |
|-------|-----------|----------|
| `tool.execute.before` | Before tool execution | Capture tool invocation, security checks |
| `tool.execute.after` | After tool execution | Capture results, duration, errors |

**Example:**
```typescript
"tool.execute.before": async (input, output) => {
  // input.tool: "bash" | "read" | "edit" | ...
  // output.args: { command: "ls -la", ... }

  // Emit to Syn137 collector
  await emitEvent("tool_execution_started", {
    tool_name: input.tool,
    args: output.args,
    timestamp: Date.now(),
  })
}
```

### Session Events (Agent Lifecycle)

| Event | When Fired | Use Case |
|-------|-----------|----------|
| `session.created` | Session starts | Track session initiation |
| `session.idle` | Session completes | Mark session complete |
| `session.error` | Session errors | Capture failures |
| `session.status` | Status updates | Track progress |
| `session.updated` | State changes | Capture state transitions |
| `session.compacted` | Context compression | Track compaction events |

**Example:**
```typescript
"session.created": async (event) => {
  await emitEvent("agent_session_started", {
    session_id: event.sessionId,
    provider: event.provider,
    model: event.model,
    backend: "opencode",
  })
}
```

### File Events (Track Edits)

| Event | When Fired | Use Case |
|-------|-----------|----------|
| `file.edited` | File modified | Capture file operations |
| `file.watcher.updated` | File system changes | Track workspace changes |

### Message Events (Conversation Tracking)

| Event | When Fired | Use Case |
|-------|-----------|----------|
| `message.updated` | Message changes | Track conversation |
| `message.part.updated` | Streaming updates | Capture streaming tokens |
| `message.removed` | Message deleted | Track deletions |

### Other Events

- `command.executed` - Custom command execution
- `lsp.client.diagnostics` - LSP diagnostics
- `permission.replied` - Permission decisions
- `todo.updated` - Todo changes

## Syn137 Observability Plugin Design

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  OpenCode Container                                          │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Syn137 Observability Plugin                          │     │
│  │                                                    │     │
│  │  ┌──────────────┐      ┌──────────────────────┐  │     │
│  │  │ Event Hooks  │─────▶│  Event Mapper        │  │     │
│  │  │              │      │                      │  │     │
│  │  │ • tool.*     │      │ OpenCode → Syn137      │  │     │
│  │  │ • session.*  │      │ event schema        │  │     │
│  │  │ • file.*     │      │                      │  │     │
│  │  └──────────────┘      └──────────┬───────────┘  │     │
│  │                                   │              │     │
│  │                                   ▼              │     │
│  │                        ┌──────────────────────┐  │     │
│  │                        │  HTTP Emitter        │  │     │
│  │                        │  (with retry logic)  │  │     │
│  │                        └──────────┬───────────┘  │     │
│  └────────────────────────────────────┼──────────────┘     │
│                                       │                    │
└───────────────────────────────────────┼────────────────────┘
                                        │
                                        ▼
                           ┌─────────────────────┐
                           │  Syn137 Collector      │
                           │  POST /events       │
                           └─────────────────────┘
```

### Event Mapping

OpenCode plugin events map to Syn137 domain events:

| OpenCode Event | Syn137 Domain Event | Attributes |
|---------------|------------------|------------|
| `tool.execute.before` | `ToolExecutionStarted` | tool_name, args, session_id, timestamp |
| `tool.execute.after` | `ToolExecutionCompleted` | tool_name, result, duration_ms, tokens |
| `session.created` | `AgentSessionStarted` | session_id, backend, provider, model |
| `session.idle` | `AgentSessionCompleted` | session_id, duration_ms, total_tokens |
| `session.error` | `AgentSessionFailed` | session_id, error_message, error_type |
| `file.edited` | `FileOperationCompleted` | file_path, operation: "edit", diff |
| `message.updated` | `MessageEvent` | message_id, role, content_length |

### Plugin Implementation

**Core Plugin:**
```typescript
// packages/opencode-syn137-plugin/src/index.ts
import type { Plugin } from "@opencode-ai/plugin"

interface Syn137PluginConfig {
  collectorUrl: string
  sessionId: string
  apiKey?: string
  retryAttempts: number
  batchSize: number
}

export const Syn137ObservabilityPlugin: Plugin = async ({
  project,
  client,
  directory
}) => {
  const config: Syn137PluginConfig = {
    collectorUrl: process.env.SYN_COLLECTOR_URL || "http://syn-collector:8080",
    sessionId: process.env.SYN_SESSION_ID || crypto.randomUUID(),
    apiKey: process.env.SYN_API_KEY,
    retryAttempts: 3,
    batchSize: 10,
  }

  const eventQueue: any[] = []

  async function emitEvent(eventType: string, payload: any) {
    const event = {
      event_type: eventType,
      session_id: config.sessionId,
      timestamp: new Date().toISOString(),
      backend: "opencode",
      project: project.name,
      directory,
      ...payload,
    }

    eventQueue.push(event)

    // Batch emit
    if (eventQueue.length >= config.batchSize) {
      await flushEvents()
    }
  }

  async function flushEvents() {
    if (eventQueue.length === 0) return

    const batch = eventQueue.splice(0, eventQueue.length)

    for (let attempt = 0; attempt < config.retryAttempts; attempt++) {
      try {
        const response = await fetch(`${config.collectorUrl}/events`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(config.apiKey && { "Authorization": `Bearer ${config.apiKey}` }),
          },
          body: JSON.stringify({ events: batch }),
        })

        if (response.ok) {
          return // Success
        }
      } catch (error) {
        if (attempt === config.retryAttempts - 1) {
          await client.app.log({
            service: "syn137-observability",
            level: "error",
            message: "Failed to emit events after retries",
            extra: { error: error.message, eventCount: batch.length },
          })
        }
        await new Promise(resolve => setTimeout(resolve, 1000 * Math.pow(2, attempt)))
      }
    }
  }

  // Flush on session idle
  const originalSessionIdle = async (event: any) => {
    await flushEvents()
  }

  return {
    // Tool execution tracking
    "tool.execute.before": async (input, output) => {
      await emitEvent("tool_execution_started", {
        tool_name: input.tool,
        tool_args: output.args,
      })
    },

    "tool.execute.after": async (input, output) => {
      await emitEvent("tool_execution_completed", {
        tool_name: input.tool,
        result: output.result,
        success: !output.error,
        error: output.error,
      })
    },

    // Session lifecycle
    "session.created": async (event) => {
      await emitEvent("agent_session_started", {
        provider: event.provider,
        model: event.model,
      })
    },

    "session.idle": async (event) => {
      await emitEvent("agent_session_completed", {})
      await flushEvents() // Ensure all events sent
    },

    "session.error": async (event) => {
      await emitEvent("agent_session_failed", {
        error_message: event.error?.message,
        error_stack: event.error?.stack,
      })
      await flushEvents()
    },

    // File operations
    "file.edited": async (event) => {
      await emitEvent("file_operation_completed", {
        file_path: event.filePath,
        operation: "edit",
        // TODO: Capture diff if available
      })
    },

    // Message tracking
    "message.updated": async (event) => {
      await emitEvent("message_event", {
        message_id: event.messageId,
        role: event.role,
        content_length: event.content?.length || 0,
      })
    },
  }
}
```

## Security Policy Enforcement

Plugins can enforce security policies by blocking unsafe operations:

```typescript
"tool.execute.before": async (input, output) => {
  // Block dangerous commands
  if (input.tool === "bash") {
    const dangerousPatterns = [
      /rm\s+-rf\s+\//,
      /sudo/,
      /curl.*\|.*bash/,
    ]

    for (const pattern of dangerousPatterns) {
      if (pattern.test(output.args.command)) {
        throw new Error(`Blocked by Syn137 security policy: dangerous command pattern`)
      }
    }
  }

  // Block reading sensitive files
  if (input.tool === "read") {
    const sensitiveFiles = [".env", ".env.local", "id_rsa", ".ssh/"]
    if (sensitiveFiles.some(f => output.args.filePath.includes(f))) {
      throw new Error(`Blocked by Syn137 security policy: sensitive file access`)
    }
  }

  await emitEvent("tool_execution_started", { ... })
}
```

## Custom Tools

Plugins can add custom tools that agents can invoke:

```typescript
import { tool } from "@opencode-ai/plugin"

export const Syn137Plugin: Plugin = async (ctx) => {
  return {
    tool: {
      // Custom tool for emitting structured events
      emit_syn137_metric: tool({
        description: "Emit a custom metric to Syn137 observability",
        args: {
          metric_name: tool.schema.string(),
          value: tool.schema.number(),
          tags: tool.schema.record(tool.schema.string()),
        },
        async execute(args, ctx) {
          await fetch('http://syn-collector:8080/metrics', {
            method: 'POST',
            body: JSON.stringify(args),
          })
          return `Metric ${args.metric_name} emitted: ${args.value}`
        },
      }),

      // Custom tool for querying Syn137 dashboard
      query_syn137_metrics: tool({
        description: "Query Syn137 metrics dashboard for session stats",
        args: {
          session_id: tool.schema.string(),
        },
        async execute(args, ctx) {
          const response = await fetch(
            `http://syn-dashboard:8000/api/sessions/${args.session_id}/metrics`
          )
          return await response.json()
        },
      }),
    },
  }
}
```

## Structured Logging

Use OpenCode's structured logging API for debugging:

```typescript
await client.app.log({
  service: "syn137-observability",
  level: "info",  // debug | info | warn | error
  message: "Tool execution captured",
  extra: {
    tool: "bash",
    duration_ms: 123,
    tokens: 456,
    session_id: config.sessionId,
  },
})
```

Logs are written to OpenCode's log directory (`~/.local/share/opencode/log/`).

## Token Attribution (Plugin + Gateway)

**Challenge:** OpenCode plugin events don't expose token counts or costs.

**Solution:** Combine plugin events with API gateway telemetry:

1. **API Gateway** captures:
   - Token counts (input/output)
   - Model latency
   - Provider/model identification
   - Cost calculation

2. **Plugin** captures:
   - Tool execution context
   - File operations
   - Session lifecycle

3. **Correlation:** Trace IDs link gateway spans ↔ plugin events

```typescript
// Plugin emits trace ID
"tool.execute.before": async (input, output) => {
  const traceId = crypto.randomUUID()
  output.traceId = traceId  // Propagate to API calls

  await emitEvent("tool_execution_started", {
    tool_name: input.tool,
    trace_id: traceId,  // Link to gateway spans
  })
}
```

Gateway adds trace ID to OpenTelemetry spans:

```python
# packages/syn137-gateway/src/proxy.py
from opentelemetry import trace

@app.post("/v1/messages")
async def proxy_anthropic(request: Request):
    tracer = trace.get_tracer(__name__)
    trace_id = request.headers.get("X-Trace-ID")

    with tracer.start_as_current_span(
        "anthropic.messages.create",
        attributes={
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": body["model"],
            "syn137.trace_id": trace_id,  # Link to plugin
        }
    ) as span:
        # Proxy request...
        span.set_attribute("gen_ai.usage.input_tokens", response["usage"]["input_tokens"])
```

## Deployment

### Docker Configuration

**Dockerfile:**
```dockerfile
FROM oven/bun:latest

# Install OpenCode
RUN bun install -g @opencode-ai/cli

# Install Syn137 plugin
COPY packages/opencode-syn137-plugin /app/syn137-plugin
WORKDIR /app/syn137-plugin
RUN bun install

# Copy OpenCode config
COPY .opencode/opencode.json /root/.config/opencode/opencode.json

WORKDIR /workspace
CMD ["opencode"]
```

**Config (opencode.json):**
```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["file:///app/syn137-plugin"]
}
```

**Environment Variables:**
```bash
SYN_COLLECTOR_URL=http://syn-collector:8080
SYN_SESSION_ID=<generated-by-workspace-service>
SYN_API_KEY=<optional-auth>
AI_API_BASE_URL=http://syn137-gateway:8081  # Route through gateway
```

### WorkspaceService Integration

```python
# packages/syn-adapters/src/syn_adapters/workspace_backends/opencode.py
from syn_domain.workspace import WorkspaceBackend

class OpenCodeWorkspaceBackend(WorkspaceBackend):
    def __init__(self, collector_url: str, gateway_url: str):
        self.collector_url = collector_url
        self.gateway_url = gateway_url

    async def create(self, execution_id: str) -> Workspace:
        session_id = f"opencode-{execution_id}"

        # Start container with plugin configured
        container = await self.docker.containers.run(
            "syn137/opencode:latest",
            environment={
                "SYN_COLLECTOR_URL": self.collector_url,
                "SYN_SESSION_ID": session_id,
                "AI_API_BASE_URL": self.gateway_url,
            },
            volumes={
                f"/workspaces/{execution_id}": {"bind": "/workspace", "mode": "rw"},
            },
        )

        return OpenCodeWorkspace(container, session_id)
```

## Testing

### Unit Tests (Plugin)

```typescript
// packages/opencode-syn137-plugin/test/plugin.test.ts
import { describe, test, expect, mock } from "bun:test"
import { Syn137ObservabilityPlugin } from "../src"

describe("Syn137ObservabilityPlugin", () => {
  test("emits tool_execution_started on tool.execute.before", async () => {
    const mockFetch = mock(() => Promise.resolve({ ok: true }))
    global.fetch = mockFetch

    const plugin = await Syn137ObservabilityPlugin({
      project: { name: "test" },
      client: { app: { log: () => {} } },
      directory: "/test",
    })

    await plugin["tool.execute.before"](
      { tool: "bash" },
      { args: { command: "ls" } }
    )

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/events"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("tool_execution_started"),
      })
    )
  })
})
```

### Integration Tests (Recording-Based)

```python
# syn_tests/integration/test_opencode_observability.py
import pytest
from syn_adapters.workspace_backends.opencode import OpenCodeWorkspaceBackend

@pytest.mark.integration
async def test_opencode_events_captured(test_infrastructure, db_pool):
    backend = OpenCodeWorkspaceBackend(
        collector_url="http://localhost:18080",
        gateway_url="http://localhost:18081",
    )

    async with backend.create("test-exec") as workspace:
        await workspace.execute(["opencode", "-p", "List files in current directory"])

    # Verify events in database
    async with db_pool.acquire() as conn:
        events = await conn.fetch("""
            SELECT event_type, payload->>'tool_name' as tool
            FROM event_store.events
            WHERE payload->>'session_id' = 'opencode-test-exec'
            ORDER BY created_at
        """)

        assert events[0]["event_type"] == "agent_session_started"
        assert events[1]["event_type"] == "tool_execution_started"
        assert events[1]["tool"] == "bash"
```

## Performance Considerations

### Event Batching

Plugin batches events (default: 10 events) before HTTP emission:

```typescript
const eventQueue: any[] = []

if (eventQueue.length >= config.batchSize) {
  await flushEvents()
}
```

Reduces HTTP overhead while maintaining near-real-time telemetry.

### Async Emission

Events are emitted asynchronously to avoid blocking agent execution:

```typescript
"tool.execute.before": async (input, output) => {
  // Non-blocking: fire-and-forget
  emitEvent("tool_execution_started", { ... }).catch(err => {
    // Log but don't fail tool execution
    console.error("Failed to emit event:", err)
  })
}
```

### Retry Logic

Exponential backoff for failed HTTP requests:

```typescript
for (let attempt = 0; attempt < config.retryAttempts; attempt++) {
  try {
    await fetch(...)
    return // Success
  } catch (error) {
    await sleep(1000 * Math.pow(2, attempt)) // 1s, 2s, 4s
  }
}
```

## Future Enhancements

- **Dead letter queue** for failed events
- **Event compression** (gzip) for large payloads
- **Sampling** for high-volume sessions
- **OpenTelemetry integration** when upstream PR lands
- **Message diff capture** for fine-grained edits

## References

- [OpenCode Plugin Documentation](https://opencode.ai/docs/plugins/)
- [OpenCode GitHub Repository](https://github.com/stackblitz/opencode)
- [Bun Shell API](https://bun.sh/docs/runtime/shell)
- [Syn137 Issue #51 - OpenCode Integration](https://github.com/syntropic137/syntropic137/issues/51)

