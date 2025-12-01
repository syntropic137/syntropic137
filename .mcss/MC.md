# MISSION CONTROL — Agentic Engineering Framework

## Purpose

Build an event-sourced system for tracking AI agent work across workflows, capturing metrics, and optimizing agent swarms. The framework enables engineers to define composable workflow phases, execute them via CLI, and analyze artifacts and metrics from agent runs.

## Architecture / Structure Summary

```
agentic-engineering-framework/          # uv monorepo (uv_build backend)
├── apps/aef-cli/src/aef_cli/           # CLI entry point (Typer)
├── packages/
│   ├── aef-domain/src/aef_domain/      # Domain layer (aggregates, events, commands)
│   ├── aef-adapters/src/aef_adapters/  # Infrastructure adapters (storage, agents)
│   └── aef-shared/src/aef_shared/      # Shared utilities (logging, DI)
├── lib/
│   ├── event-sourcing-platform/        # Submodule: Rust event store + Python SDK
│   └── agentic-primitives/             # Submodule: Agent orchestration patterns
└── workflows/                          # YAML workflow definitions (seeded to DB)
```

**Pattern:** Event Sourcing + Processor/Todo Pattern (no complex sagas)
**Naming:** Project names use hyphens (`aef-domain`), imports use snake_case (`aef_domain`)

## Key Decisions

- **ADR-001:** Monorepo with apps/ + packages/ separation
- **ADR-002:** uv_build backend, canonical src/ layout
- Event sourcing via event-sourcing-platform Python SDK (gRPC to Rust store)
- Processor/Todo pattern for event handling (not sagas)
- PostgreSQL for artifacts (migrate to S3/Supabase later)
- Workflows defined in YAML, seeded to database
- Strict typing: Pydantic + mypy strict mode
- Structured logging: structlog with DI interface
- 80% test coverage minimum

## Constraints

- Python 3.12+
- uv package manager only
- Must use VSA tool for vertical slice validation
- Phase 1: No git hooks, no code execution environment, no GitHub app
- In-memory storage for unit tests, Docker PostgreSQL for local dev

## Important Links / Files

- Codebase: `/Users/neural/Code/AgentParadise/agentic-engineering-framework`
- Project Plan: `PROJECT-PLAN_20241201_MVP-FOUNDATION.md` (not committed)
- ADRs: `docs/adrs/`
- Domain Reference: `docs/_reference/20251130-aggregate-entity-design.md`
- System Model: `docs/_reference/20251130-agentic-engineering-ssytem_final-model.md`
