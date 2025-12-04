# MISSION CONTROL — Agentic Engineering Framework

## Purpose

Build an event-sourced system for tracking AI agent work across workflows, capturing metrics, and optimizing agent swarms. The framework enables engineers to define composable workflow phases, execute them via CLI or API, and analyze artifacts and metrics from agent runs.

## Architecture / Structure Summary

```
agentic-engineering-framework/          # uv monorepo (uv_build backend)
├── apps/
│   ├── aef-cli/src/aef_cli/            # CLI entry point (Typer)
│   └── aef-dashboard/src/aef_dashboard/ # Dashboard API (FastAPI)
├── apps/aef-dashboard-ui/              # React dashboard frontend
├── packages/
│   ├── aef-domain/src/aef_domain/      # Domain layer (aggregates, events, commands)
│   ├── aef-adapters/src/aef_adapters/  # Infrastructure adapters (storage, agents)
│   └── aef-shared/src/aef_shared/      # Shared utilities (logging, settings)
├── lib/
│   ├── event-sourcing-platform/        # Submodule: Rust event store + Python SDK
│   └── agentic-primitives/             # Submodule: Agent orchestration patterns
└── workflows/                          # YAML workflow definitions
```

**Pattern:** Event Sourcing + CQRS + Vertical Slice Architecture
**Agent Pattern:** Agentic SDKs (not chat completion) — agents control tool use and multi-turn execution

## Key Decisions

- **ADR-001:** Monorepo with apps/ + packages/ separation
- **ADR-002:** uv_build backend, canonical src/ layout
- **ADR-007:** Event Store Integration via gRPC to Rust server
- **ADR-008:** VSA Projections for CQRS read side
- **ADR-009:** Agentic Execution Architecture (SDK-based, not API-based)
- **ADR-010:** Event Subscription Architecture (pub/sub to projections)
- Event sourcing via event-sourcing-platform Python SDK
- PostgreSQL for projections and artifacts
- Workflows defined in YAML, seeded to database
- Strict typing: Pydantic + mypy strict mode
- Structured logging: structlog with DI interface

## Constraints

- Python 3.12+
- uv package manager only
- Must use VSA tool for vertical slice validation
- In-memory storage for unit tests, Docker PostgreSQL for local dev
- Event store connection via gRPC (port 50051)

## Current Branch

`feat/agentic-sdk-full-integration` — Agentic SDK + Event Subscriptions

## Important Links / Files

- Codebase: `/Users/neural/Code/AgentParadise/agentic-engineering-framework`
- Project Plans: `PROJECT-PLAN_*.md` (root directory)
- ADRs: `docs/adrs/`
- Domain Reference: `docs/_reference/20251130-aggregate-entity-design.md`
- System Model: `docs/_reference/20251130-agentic-engineering-system_final-model.md`

## Quick Commands

```bash
# Start development environment
just dev                  # Docker (PostgreSQL + Event Store)
just dashboard-backend    # API server (port 8000)
just dashboard-frontend   # React dev (port 5173)

# Seed and test
just seed-workflows       # Seed sample workflows
just test                 # Run all 233 tests
just qa                   # Full QA pipeline

# Check health
curl http://localhost:8000/health
```
