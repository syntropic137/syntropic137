# @syntropic137/openclaw-plugin

OpenClaw plugin for [Syntropic137](https://github.com/Syntropic137/syntropic137) — orchestrate AI workflows, monitor executions, review costs, and automate GitHub triggers, all through natural language.

## Quick Start

### Install from local path

```bash
openclaw plugins install -l ./packages/openclaw-plugin
```

### Install from npm

```bash
openclaw plugins install @syntropic137/openclaw-plugin
```

### Configure

The plugin works out of the box with a local Syntropic137 instance on `http://localhost:8137`. For remote deployments, configure via OpenClaw plugin settings:

```json
{
  "apiUrl": "https://your-syntropic-instance.example.com",
  "apiKey": "your-api-key"
}
```

Or via environment variables:

```bash
export SYNTROPIC_URL="https://your-syntropic-instance.example.com"
export SYNTROPIC_API_KEY="your-api-key"
```

**Resolution order:** plugin config → environment variables → defaults (`http://localhost:8137`, no auth).

## What You Can Do

Once installed, just talk to your OpenClaw agent:

> "What workflows are available?"

> "Run the issue resolution workflow for https://github.com/org/repo/issues/42"

> "How's that execution going?"

> "How much did that cost?"

> "Show me the artifacts from the last run"

> "Set up a trigger to automatically run code review on new PRs in org/repo"

The agent uses 15 tools under the hood — you don't need to know their names.

## Tools Reference

### Workflows
| Tool | What it does |
|------|-------------|
| `syn_list_workflows` | Browse available workflow templates |
| `syn_execute_workflow` | Start a workflow with inputs |

### Executions
| Tool | What it does |
|------|-------------|
| `syn_list_executions` | List recent/active executions |
| `syn_get_execution` | Detailed status: phases, tokens, costs |

### Control
| Tool | What it does |
|------|-------------|
| `syn_pause_execution` | Pause a running execution |
| `syn_resume_execution` | Resume a paused execution |
| `syn_cancel_execution` | Cancel an execution |
| `syn_inject_context` | Send a message to a running agent |

### Observability
| Tool | What it does |
|------|-------------|
| `syn_get_session` | Session details: tool calls, git ops, tokens |
| `syn_get_execution_cost` | Cost breakdown by phase, model, and tool |
| `syn_get_metrics` | Platform-wide usage and cost metrics |

### Artifacts
| Tool | What it does |
|------|-------------|
| `syn_list_artifacts` | List workflow outputs |
| `syn_get_artifact` | Get artifact content |

### Triggers
| Tool | What it does |
|------|-------------|
| `syn_list_triggers` | List GitHub automation rules |
| `syn_create_trigger` | Create a new trigger rule |

## Deployment Scenarios

| Setup | apiUrl | apiKey |
|-------|--------|--------|
| Same Docker network | `http://syn-api:8000` | Not needed |
| Same VPS / localhost | `http://localhost:8137` | Not needed |
| Remote API | `https://api.example.com` | Required |

## Development

```bash
# Install dependencies
npm install

# Type check
npm run typecheck

# Run tests
npm test

# Build
npm run build

# Watch mode
npm run dev
```

### Project Structure

```
src/
├── index.ts          # Plugin entry point — registers all tools
├── client.ts         # SyntropicClient: typed fetch() wrapper
├── types.ts          # Response types (mirrors syn-api models)
├── errors.ts         # Error formatting
└── tools/
    ├── workflows.ts      # List + execute workflows
    ├── executions.ts     # List + detail executions
    ├── control.ts        # Pause, resume, cancel, inject
    ├── observability.ts  # Sessions, costs, metrics
    ├── artifacts.ts      # List + get artifacts
    └── triggers.ts       # List + create triggers
```

## Requirements

- Node.js 18+ (uses native `fetch()`)
- Syntropic137 API running (local or remote)
- OpenClaw runtime

## License

MIT
