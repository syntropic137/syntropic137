# @syntropic137/cli

Command-line interface for [Syntropic137](https://github.com/syntropic137/syntropic137). An event-sourced workflow engine for AI agents.

## Design

**Single dependency. 168 KB. Full API coverage.**

The CLI is built with a zero-dependency philosophy:

- **No Commander.js**: custom two-level command framework on `node:parseArgs`
- **No chalk**: direct ANSI escape codes with `NO_COLOR` support
- **No axios**: built-in `fetch` with timeout and streaming (SSE)
- **One runtime dep**: [Zod](https://zod.dev) for local file validation only

The entire CLI ships as a single `dist/syn.mjs` file (168 KB). It targets Node.js 22+ with strict TypeScript (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`).

API response types are generated from the OpenAPI spec, so the TypeScript compiler catches any API drift at build time.

## Install

```bash
npm install -g @syntropic137/cli
```

Or run directly:

```bash
npx @syntropic137/cli health
```

## Connect to a Server

By default, the CLI connects to `http://localhost:8137` (local dev server).

### Local

```bash
# Start the API server
just dev

# Use the CLI — no auth needed on localhost
syn health
syn workflow list
```

### Remote

Set the server URL and credentials:

```bash
export SYN_API_URL=https://syn.example.com
export SYN_API_USER=admin
export SYN_API_PASSWORD=your-password

syn health
```

Or use a bearer token:

```bash
export SYN_API_URL=https://syn.example.com
export SYN_API_TOKEN=your-token

syn health
```

Environment variables take precedence. When no credentials are set, requests are sent without authentication (suitable for localhost).

## Commands

### Root Commands

| Command | Description |
|---------|-------------|
| `syn health` | Check API server health |
| `syn version` | Show CLI version |
| `syn run <workflow>` | Execute a workflow (shortcut) |

### Workflow Management

```bash
syn workflow list                    # List all workflows
syn workflow show <id>               # Show workflow details
syn workflow create <name>           # Create a new workflow
syn workflow run <id> -i key=value   # Execute a workflow
syn workflow status <id>             # Show execution history
syn workflow validate <path>         # Validate a workflow package
syn workflow delete <id> --force     # Archive a workflow
syn workflow export <id> -o ./out    # Export workflow files
```

### Workflow Packages & Marketplace

```bash
# Install from marketplace, git, or local path
syn workflow install my-plugin
syn workflow install https://github.com/org/repo
syn workflow install ./local-package

# Manage installations
syn workflow installed               # List installed packages
syn workflow update my-plugin        # Update to latest
syn workflow uninstall my-plugin     # Remove workflows

# Search the marketplace
syn workflow search "code review"
syn workflow info my-plugin

# Manage registries
syn marketplace add https://github.com/org/registry
syn marketplace list
syn marketplace refresh
```

### Execution Control

```bash
syn execution list                   # List all executions
syn execution show <id>              # Show execution detail

syn control pause <id>               # Pause at next yield point
syn control resume <id>              # Resume paused execution
syn control cancel <id> --force      # Cancel execution
syn control status <id>              # Check execution state
syn control inject <id> -m "msg"     # Inject a message
```

### Sessions & Observability

```bash
syn sessions list                    # List agent sessions
syn sessions show <id>               # Show session detail

syn events recent                    # Recent domain events
syn events session <id>              # Session events
syn events timeline <id>             # Tool-call timeline
syn events costs <id>                # Token/cost breakdown
syn events tools <id>                # Tool usage summary

syn observe tools <id>               # Tool execution timeline
syn observe tokens <id>              # Token breakdown

syn conversations show <id>          # View conversation log
syn conversations metadata <id>     # Conversation metadata
```

### Cost Tracking

```bash
syn costs summary                    # Global cost overview
syn costs sessions                   # Cost by session
syn costs session <id>               # Session cost detail
syn costs executions                 # Cost by execution
syn costs execution <id>             # Execution cost detail
```

### Organization Management

```bash
syn org create --name "Acme"         # Create organization
syn org list                         # List organizations
syn org show <id>                    # Organization detail

syn system create --name "Backend"   # Create system
syn system list                      # List systems
syn system status <id>               # System health
syn system cost <id>                 # System costs
syn system patterns <id>             # Failure patterns
syn system history <id>              # Execution history

syn repo register --url owner/repo   # Register repository
syn repo list                        # List repositories
syn repo health <id>                 # Health metrics
syn repo cost <id>                   # Cost breakdown
syn repo activity <id>               # Recent activity
syn repo failures <id>               # Recent failures
```

### Live Streaming

```bash
syn watch execution <id>             # Stream execution events (SSE)
syn watch activity                   # Stream all activity
```

### Triggers

```bash
syn triggers register --repo r --workflow w --event push
syn triggers enable self-healing --repo r
syn triggers list
syn triggers show <id>
syn triggers history <id>
syn triggers pause <id>
syn triggers delete <id> --force
```

### Configuration & Metrics

```bash
syn config show                      # Show current config
syn config validate                  # Validate configuration
syn metrics show                     # Aggregated metrics
syn insights overview                # Global system overview
syn insights cost --days 30          # Cost analysis
syn insights heatmap                 # Activity heatmap
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SYN_API_URL` | `http://localhost:8137` | API server URL |
| `SYN_API_TOKEN` | (none) | Bearer token for authentication |
| `SYN_API_USER` | (none) | Basic auth username |
| `SYN_API_PASSWORD` | (none) | Basic auth password |
| `NO_COLOR` | (none) | Disable colored output |

## Development

```bash
# Install dependencies
pnpm install

# Development mode (auto-reload)
pnpm dev

# Build
pnpm build

# Run tests
pnpm test

# Type check
pnpm typecheck

# Regenerate API types from OpenAPI spec
pnpm generate:types

# Check for API drift (CI)
pnpm check:api-drift
```

## API Type Safety

All commands use the typed API client powered by [openapi-fetch](https://openapi-ts.dev/openapi-fetch/). Response types are generated from the OpenAPI spec (`apps/syn-docs/openapi.json`) using `openapi-typescript`, giving compile-time path validation and fully typed responses.

```typescript
import { api, unwrap } from "../client/typed.js";
import type { components } from "../generated/api-types.js";

type ExecutionList = components["schemas"]["ExecutionListResponse"];

const data = unwrap(
  await api.GET("/executions", { params: { query: { status: "running" } } }),
  "List executions",
);
// data.executions is typed as ExecutionSummaryResponse[]
// data.total is typed as number
```

If the API spec changes:
1. `pnpm generate:types` regenerates the types
2. `tsc` catches any CLI code that doesn't match the new schema
3. `pnpm check:api-drift` in CI flags stale generated types
4. `pnpm check:untyped-api` in CI prevents use of the deprecated untyped client

## License

MIT
