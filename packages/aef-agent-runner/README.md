# AEF Agent Runner

Minimal agent runner package designed to execute inside isolated AEF workspaces.

## Purpose

This package runs **inside** isolated containers and:

1. Reads task configuration from `/workspace/task.json`
2. Executes the Claude agent SDK
3. Emits JSONL events to stdout (for orchestrator parsing)
4. Writes artifacts to `/workspace/artifacts/`
5. Handles graceful cancellation via `/workspace/.cancel`

## Usage

```bash
# Inside container
python -m aef_agent_runner

# Or via entry point
aef-agent-run
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `HTTP_PROXY` | Sidecar proxy URL (tokens injected here) | Yes |
| `HTTPS_PROXY` | Sidecar proxy URL for HTTPS | Yes |
| `AEF_EXECUTION_ID` | Current execution ID | Yes |
| `AEF_TENANT_ID` | Tenant identifier | Yes |

## Task Format

```json
{
  "phase": "research",
  "prompt": "Research best practices for...",
  "inputs": {},
  "artifacts": ["previous_phase_output.md"],
  "execution_id": "exec-123",
  "tenant_id": "tenant-abc"
}
```

## Event Output (JSONL to stdout)

```jsonl
{"type": "started", "timestamp": "2025-12-14T10:00:00Z"}
{"type": "tool_use", "tool": "Read", "path": "/workspace/inputs/doc.md"}
{"type": "progress", "turn": 1, "input_tokens": 1500, "output_tokens": 200}
{"type": "artifact", "name": "research.md", "path": "/workspace/artifacts/research.md"}
{"type": "completed", "success": true, "duration_ms": 45000}
```

## Cancellation

The runner polls for `/workspace/.cancel` file every second. When detected:

1. Gracefully stops the agent
2. Emits `{"type": "cancelled"}` event
3. Exits with code 130 (SIGINT equivalent)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Isolated Container                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 aef-agent-runner                      │   │
│  │                                                       │   │
│  │  task.json ──▶ Claude SDK ──▶ stdout (JSONL events)  │   │
│  │                    │                                  │   │
│  │                    ▼                                  │   │
│  │              /workspace/artifacts/                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          │ HTTP_PROXY                        │
│                          ▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Sidecar Proxy (Envoy)                    │   │
│  │         (injects tokens, never seen by agent)         │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│                  api.anthropic.com                           │
└─────────────────────────────────────────────────────────────┘
```

## Related

- ADR-021: Isolated Workspace Architecture
- ADR-022: Secure Token Architecture
- ADR-023: Workspace-First Execution Model
