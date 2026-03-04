---
description: Prime context for Syn137 (Syntropic137)
argument-hint: [optional: focus area like "adapters", "dashboard", "cli", "events"]
model: sonnet
allowed-tools: Read, Glob, Grep
---

# Prime

Quickly understand the Syn137 codebase structure, patterns, and architecture.

## Purpose

Build working context for Syntropic137 by reading key files and understanding the dual-purpose architecture: **Orchestration** (running agents in Docker) and **Observability** (capturing and analyzing agent events).

## Variables

FOCUS_AREA: $ARGUMENTS

## Codebase Structure

```
syntropic137/
├── apps/                           # Applications
│   ├── syn-cli/                    # CLI tool (`syn` command)
│   ├── syn-dashboard/              # FastAPI backend (port 8000)
│   └── syn-dashboard-ui/           # React frontend (port 5173)
│
├── packages/                       # Core packages
│   ├── syn-adapters/               # External integrations (Docker, EventStore, MinIO)
│   │   ├── events/                 # Event storage (TimescaleDB)
│   │   ├── workspace_backends/     # Docker workspace management
│   │   ├── projections/            # Event aggregations
│   │   └── subscriptions/          # Real-time event streaming
│   ├── syn-domain/                 # Domain models & VSA contexts
│   │   ├── agents/                 # Agent sessions, token tracking
│   │   ├── workflows/              # Workflow definitions, phases
│   │   ├── artifacts/              # Artifact storage, metadata
│   │   ├── workspaces/             # Isolated workspace lifecycle
│   │   └── costs/                  # Cost tracking & aggregation
│   ├── syn-collector/              # Event ingestion API (port 8080)
│   ├── syn-shared/                 # Logging, settings, utilities
│   └── syn-tokens/                 # Secure token vending
│
├── lib/                            # Git submodules
│   ├── agentic-primitives/         # Composable agent blocks
│   │   └── lib/python/             # Python libs (agentic_events, etc.)
│   ├── event-sourcing-platform/    # Event sourcing infrastructure
│   └── ui-feedback/                # UI feedback widget
│
├── docker/                         # Docker Compose configs
│   ├── docker-compose.yaml         # Base services
│   ├── docker-compose.dev.yaml     # Dev overrides
│   └── docker-compose.test.yaml    # Test stack (ports +10000)
│
├── workflows/                      # Workflow YAML definitions
│   └── examples/                   # Sample workflows
│
├── docs/adrs/                      # Architecture Decision Records
├── syn_tests/                      # Integration test fixtures
├── justfile                        # Command runner (just --list)
└── AGENTS.md                       # Agent instructions & RIPER-5 protocol
```

## Key Files

| File | Purpose | Read Priority |
|------|---------|---------------|
| `justfile` | **Primary entry point** - all dev commands (`just --list`) | 1 (critical) |
| `AGENTS.md` | Agent instructions, RIPER-5 protocol, testing philosophy | 1 (critical) |
| `pyproject.toml` | Dependencies, workspace config, tool settings | 1 (critical) |
| `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py` | Core orchestration - runs Claude in Docker | 2 (high) |
| `packages/syn-adapters/src/syn_adapters/events/store.py` | Event storage (TimescaleDB) | 2 (high) |
| `apps/syn-dashboard/src/syn_dashboard/main.py` | Dashboard API entry point | 2 (high) |
| `apps/syn-cli/src/syn_cli/main.py` | CLI entry point | 2 (high) |
| `packages/syn-domain/src/syn_domain/` | Domain models per bounded context | 3 (medium) |
| `docker/docker-compose.yaml` | Infrastructure services | 3 (medium) |
| `docs/adrs/` | Architecture decisions (35+ ADRs) | 3 (medium) |

## Patterns

- **Language:** Python 3.12+
- **Command Runner:** `just` (justfile) is the primary entry point for all operations
- **Package Manager:** `uv` (Astral) - never use pip, poetry, or pipenv
  - All `just` recipes use `uv` under the hood
  - Use `uv add <pkg>` when adding new dependencies
- **Architecture:** Vertical Slice Architecture (VSA) with bounded contexts
- **Event Sourcing:** Commands → Aggregates → Events → Projections
- **Testing:** Recording-based integration tests (no API tokens needed)
- **Config:** Pydantic settings from environment variables
- **Naming:** snake_case (Python), kebab-case (packages/files)
- **Build:** `just qa` (lint + typecheck + test)

## Key Concepts

### Orchestration Flow
```
WorkspaceService.create_workspace() → Docker container
    → claude CLI runs inside container
    → stderr emits JSONL events
    → Events captured by host
```

### Observability Pipeline
```
Agent events → Collector (8080) → EventStore → Projections → Dashboard
```

### Test Infrastructure (ADR-034)
```
Dev Stack:  ports 5432, 50051, 8080, 9000, 6379 (persistent)
Test Stack: ports +10000 (15432, 55051, etc.) (ephemeral)
```

## Workflow

1. **Read Foundation**
   - Read `AGENTS.md` for agent instructions and RIPER-5 protocol
   - Read `justfile` for available commands
   - Read `pyproject.toml` for package structure

2. **Understand Architecture**
   - Review relevant ADRs in `docs/adrs/`
   - Check bounded contexts in `packages/syn-domain/src/syn_domain/`

3. **If FOCUS_AREA provided**
   Focus areas and their key files:

   | Area | Key Files |
   |------|-----------|
   | `adapters` | `packages/syn-adapters/src/syn_adapters/` |
   | `dashboard` | `apps/syn-dashboard/src/syn_dashboard/` |
   | `cli` | `apps/syn-cli/src/syn_cli/` |
   | `events` | `packages/syn-adapters/src/syn_adapters/events/` |
   | `workspaces` | `packages/syn-adapters/src/syn_adapters/workspace_backends/` |
   | `domain` | `packages/syn-domain/src/syn_domain/` |
   | `collector` | `packages/syn-collector/src/syn_collector/` |
   | `frontend` | `apps/syn-dashboard-ui/src/` |

## Common Commands

**The `justfile` is the primary entry point for all operations.** Run `just --list` to see all available commands.

```bash
# Getting Started
just --list             # Show all available commands
just install            # Install dependencies (uses uv sync)

# Development
just dev-fresh          # Clean start: reset DB + start full stack + seed
just dev                # Start Docker services only
just dev-down           # Stop all services

# Quality Assurance
just qa                 # Full QA: lint + typecheck + test
just lint               # Ruff linting
just format             # Ruff formatting
just typecheck          # Mypy type checking
just test               # Run tests

# Testing
just test-unit          # Fast unit tests (no infra)
just test-stack         # Start ephemeral test infra (ports +10000)
just test-integration   # Integration tests

# CLI
just cli --help         # Syn137 CLI commands
just cli run <workflow> # Run a workflow

# Direct uv commands (when just recipe doesn't exist)
uv add <package>        # Add new dependency
uv run <command>        # Run arbitrary command in venv
```

> **Note:** All `just` recipes use `uv` under the hood. Prefer `just` commands over raw `uv` commands when available.

## Report

## Syn137 Context Loaded

**Purpose:** Event-sourced system for AI agent orchestration and observability

**Stack:** Python 3.12 / FastAPI / React / Docker / TimescaleDB / MinIO

### Core Capabilities
- Run Claude CLI in isolated Docker containers
- Capture all agent events (tool use, tokens, costs, errors)
- Real-time streaming to dashboard
- Recording-based testing (no API tokens spent)

### Architecture Understanding
- **apps/**: CLI, Dashboard API, Dashboard UI
- **packages/**: Domain models, adapters, shared utilities
- **lib/**: Git submodules (agentic-primitives, event-sourcing-platform)
- **docker/**: Base + dev + test compose files
- **workflows/**: YAML workflow definitions

### Ready to Work On
Based on this context, I can help with:
- Implementing new features in bounded contexts
- Adding/modifying event projections
- Extending the CLI or Dashboard
- Writing tests using recordings
- Understanding and following RIPER-5 protocol
