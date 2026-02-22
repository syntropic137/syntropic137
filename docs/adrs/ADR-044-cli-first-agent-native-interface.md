# ADR-044: CLI-First, Agent-Native Interface Design

## Status

**Accepted** — 2026-02-20

## Context

AEF (Agentic Engineering Framework) needs a clear answer to: *who is the primary client of this system?*

Two directions were possible:

1. **Dashboard-first**: Build a rich UI, expose an API to serve it, optionally wrap with a CLI for power users
2. **CLI-first**: Build the CLI as the canonical interface, expose an API to serve it, build any UI on top of that same API

The system has grown to include a FastAPI dashboard, a React UI, and a Typer CLI. Without an explicit decision, each layer risks diverging — the CLI becomes second-class, the API becomes UI-specific, and programmatic access becomes an afterthought.

### The Primary Client Is Claude Code

AEF's primary use case is **orchestrating AI agents at scale**. The humans who deploy AEF are themselves engineers building agent pipelines. The operators of those pipelines are often other agents — specifically Claude Code agents that:

- Need to spawn sub-agents to handle discrete tasks
- Need to monitor execution status programmatically
- Need to retrieve structured output to act on
- Need to cancel or pause based on cost or time signals
- Need to retry safely without creating duplicates

Claude Code interacts with the world through **Bash commands**. It reads stdout and acts on it. It cannot interact with a browser, cannot click a dashboard, and cannot parse Rich-formatted terminal tables.

### The Dashboard Is a View, Not the Source of Truth

The React dashboard and FastAPI backend are valuable for human observability — but they are a *view* built on top of the same API that the CLI uses. The dashboard should never have capabilities that the CLI does not expose. If a human can do it in the dashboard, an agent must be able to do it via `syn`.

## Decision

**The `syn` CLI is the primary client interface for AEF. Every capability must be accessible via CLI before it is accessible via any other interface.**

Specifically:

### 1. CLI-First Feature Development

New capabilities are shipped in this order:
1. API endpoint (the contract)
2. CLI command or flag (the primary interface)
3. Dashboard UI (the human-readable view)

A feature is not "done" until it is accessible via `syn`.

### 2. Machine-Readable Output by Default in Non-TTY Contexts

All `syn` commands support `--output json` (alias `--format json`). When stdout is not a TTY (i.e., when called from a script or agent), JSON output is the default. When stdout is a TTY, Rich human-readable output is the default.

```bash
# Human (TTY) — Rich tables, panels, colors
syn workflow list

# Agent (piped or --output json) — structured JSON to stdout
syn workflow list --output json
# → [{"id": "...", "name": "...", "type": "...", "phases": 3}]
```

Errors always go to stderr, never stdout, so that stdout is clean for parsing.

### 3. Non-Interactive Mode

All commands that currently prompt for confirmation (`cancel`) support `--force` / `-f` to skip the prompt. This flag already exists for `cancel`. All future commands that require confirmation must follow the same pattern.

```bash
syn execution cancel abc-123 --force --output json
# → {"success": true, "final_status": "cancelled"}
```

### 4. Idempotency Keys on State-Changing Commands

Commands that create or modify state (`workflow run`, future: `workflow create`) accept `--idempotency-key`. The server stores seen keys for 24 hours and returns the original result on duplicate submission.

This enables agents to safely retry after timeouts or network failures without creating duplicate executions.

```bash
syn workflow run github-pr \
  --input repo=user/repo \
  --idempotency-key "issue-47-pr-review" \
  --output json
# → {"execution_id": "abc-123", "status": "started"}

# Safe retry — same key, same result
syn workflow run github-pr \
  --input repo=user/repo \
  --idempotency-key "issue-47-pr-review" \
  --output json
# → {"execution_id": "abc-123", "status": "running"}
```

### 5. The Agent Loop Is the Design Constraint

Every CLI design decision is evaluated against this canonical agent workflow:

```bash
# 1. Discover
WORKFLOWS=$(syn workflow list --output json)

# 2. Execute (non-blocking by default when --output json)
RESULT=$(syn workflow run github-pr \
  --input repo=user/repo \
  --idempotency-key "task-$(uuidgen)" \
  --output json)
EXEC_ID=$(echo $RESULT | jq -r .execution_id)

# 3. Poll
while true; do
  STATUS=$(syn execution status $EXEC_ID --output json | jq -r .status)
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done

# 4. Read output
ARTIFACT_ID=$(syn execution status $EXEC_ID --output json | jq -r '.artifacts[0]')
syn artifact get $ARTIFACT_ID --output json | jq -r .content

# 5. Control if needed
syn execution cancel $EXEC_ID --force --output json
```

If this loop does not work cleanly, the interface is not done.

### 6. Exit Codes Are Part of the Contract

- `0` — success
- `1` — execution failed (workflow returned failed status)
- `2` — CLI usage error (bad arguments)
- `3` — connectivity error (dashboard unreachable)

Exit codes must be consistent and documented. Agents use exit codes to branch.

## Consequences

### Good

- Claude Code agents can use AEF as infrastructure today with minimal setup
- The CLI serves as living documentation of what the API can do
- Any future interface (web app, VS Code extension, Slack bot) is built on the same foundation
- Testing the CLI is testing the API — no divergence
- Self-hosted deployments get full capability without needing a browser

### Bad / Trade-offs

- Every new API capability requires a corresponding CLI change before it's "shipped"
- JSON output paths must be maintained alongside human output paths (two render paths per command)
- Some capabilities are inherently interactive (agent chat, streaming logs) — these require special handling

### Out of Scope

- Authentication: Deliberately omitted for open-source / self-hosted Docker deployments. If multi-tenant or remote access is needed, this ADR will be revisited.
- MCP server: Rejected in favor of CLI-first. Claude Code uses Bash natively; an MCP layer adds complexity without capability.

## Implementation Reference

See GitHub issue #136 for the implementation scope of:
- `--output json` flag across all commands
- `--idempotency-key` on `syn workflow run`
- Exit code standardization

## Related ADRs

- ADR-011: Structured logging standard
- ADR-029: TimescaleDB for agent events
- ADR-034: Test infrastructure isolation
