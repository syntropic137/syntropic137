# ADR-001: Monorepo Architecture with VSA

## Status
Accepted (Revised)

## Date
2024-12-01

## Context

The Agentic Engineering Framework needs a scalable architecture that:
1. Integrates two external dependencies as git submodules (`agentic-primitives`, `event-sourcing-platform`)
2. Supports composable workflow phases with clear boundaries
3. Enables parallel agent development for new features
4. Uses event sourcing for all state changes
5. Follows Domain-Driven Design principles
6. Provides detailed logging for agent feedback
7. **Minimizes unnecessary directory nesting**

## Decision

### 1. Monorepo Structure: `apps/` + `packages/` Pattern (Flat)

We organize using `apps/` and `packages/` directories with **minimal nesting**. The project directory IS the package directory — no intermediate `src/` folder.

> **Note:** This is inspired by Turborepo's organization pattern, but we use **uv workspaces** for Python package management and **just** for task running.

```
agentic-engineering-framework/
├── lib/                              # Git submodules (external dependencies)
│   ├── agentic-primitives/           # Composable agent building blocks
│   └── event-sourcing-platform/      # Event sourcing infrastructure + VSA tool
│
├── apps/                             # Deployable applications
│   └── cli/                          # Package: "cli"
│       ├── __init__.py               # Package root
│       ├── main.py
│       ├── commands/
│       ├── pyproject.toml
│       └── tests/
│
├── packages/                         # Shared internal libraries
│   ├── domain/                       # Package: "domain"
│   │   ├── __init__.py               # Package root
│   │   ├── contexts/
│   │   │   ├── workflows/
│   │   │   ├── agents/
│   │   │   ├── artifacts/
│   │   │   └── _shared/
│   │   ├── pyproject.toml
│   │   └── tests/
│   │
│   ├── adapters/                     # Package: "adapters"
│   │   ├── __init__.py
│   │   ├── agents/
│   │   ├── storage/
│   │   ├── pyproject.toml
│   │   └── tests/
│   │
│   └── shared/                       # Package: "shared"
│       ├── __init__.py
│       ├── logging/
│       ├── commands/
│       ├── di/
│       ├── pyproject.toml
│       └── tests/
│
├── workflows/                        # Workflow YAML definitions (seed source)
│   └── examples/
│
├── docker/                           # Docker configurations
├── docs/                             # Documentation
├── pyproject.toml                    # Root workspace
└── justfile                          # Build commands
```

**Key principle:** Project directory = Package directory. No extra nesting.

**Imports:**
- `from domain.contexts.workflows import ...`
- `from shared.logging import ...`
- `from adapters.agents import ...`

### 2. Vertical Slice Architecture (VSA)

We will use the VSA tool from `event-sourcing-platform` to:
- Enforce architectural boundaries
- Generate consistent vertical slice scaffolding
- Validate bounded context integrity
- Enable parallel feature development

VSA structure within domain:

```
packages/domain/contexts/
├── workflows/                        # Bounded Context: Workflow Management
│   ├── create_workflow/              # Vertical Slice
│   │   ├── command.py
│   │   ├── event.py
│   │   ├── handler.py
│   │   ├── aggregate.py
│   │   └── test_create_workflow.py
│   ├── start_phase/
│   ├── complete_phase/
│   └── _processors/                  # Event processors (todo pattern)
├── agents/                           # Bounded Context: Agent Execution
│   ├── start_session/
│   ├── record_tokens/
│   └── complete_session/
└── _shared/
    └── integration_events/           # Cross-context events
```

### 3. Event Processing: Processor/Todo Pattern

Instead of complex sagas, we use the processor/todo pattern from "Understanding Event Sourcing":
- Events trigger processors
- Processors may issue new commands
- Simple, debuggable event chains
- No complex state machines

```
Command → Aggregate → Event → Processor → New Command (if needed)
```

### 4. Workflow Storage: YAML → Seed → PostgreSQL

Workflows follow a two-phase storage strategy:
- **Development**: YAML files in `workflows/` (version controlled, human-readable)
- **Runtime**: PostgreSQL table (queryable, fast retrieval)
- **Seeding**: `just seed-workflows` loads YAML into database (idempotent)

### 5. Centralized Logging with DI

Structured logging throughout the application:
- Abstract `Logger` interface for dependency injection
- `structlog` implementation with JSON output
- Context-aware logging with correlation IDs
- Configurable log levels per module
- Detailed logging for agent feedback

### 6. Type Safety: mypy + Pydantic

Type safety is critical for this system:
- **mypy (strict mode)**: Compile-time type checking for all code
- **Pydantic**: Runtime type validation for models, configs, schemas, API boundaries
- All public interfaces must be fully typed
- No `Any` types without explicit justification

### 7. Package Manager: uv with Workspaces

We will use `uv` for Python package management with workspace support:
- Fast dependency resolution
- Workspace member management
- Compatible with submodule dependencies

### 8. Build Automation: just

We will use `just` as the command runner for:
- Cross-platform compatibility
- Consistent developer experience
- Integration with VSA tool and Docker
- Comprehensive QA command: `just qa` runs lint, format, typecheck, test, coverage (≥80%), vsa-validate

### 9. Test Coverage: 80% Minimum

Test coverage is enforced as a quality gate:
- `pytest-cov` for coverage measurement
- Minimum 80% coverage required to pass QA
- Coverage report generated on every test run
- Fails CI/QA if below threshold

### 10. Artifact Storage: PostgreSQL First

Initial implementation stores artifacts inline in PostgreSQL:
- Simple transactional storage
- Queryable metadata
- Future migration path to Supabase S3

## Consequences

### Positive
- **Minimal nesting** — clean, readable paths
- Clear separation of concerns with bounded contexts
- VSA enables parallel development of features
- Event sourcing provides complete audit trail
- Processor pattern keeps event chains simple and debuggable
- YAML workflows are version controlled and reviewable
- Detailed logging enables agent feedback and debugging
- Submodules allow contribution to dependencies
- uv workspaces provide fast, reliable builds

### Negative
- Initial setup complexity
- Learning curve for VSA patterns
- Submodule management overhead
- Generic package names (`domain`, `shared`) could conflict with PyPI packages

### Risks
- VSA tool may need customization for Python patterns
- Event sourcing platform Python SDK is in beta
- If packages are ever published to PyPI, names may need prefixing

## References
- [Event Sourcing Platform](https://github.com/NeuralEmpowerment/event-sourcing-platform)
- [Agentic Primitives](https://github.com/AgentParadise/agentic-primitives)
- [uv Workspaces](https://docs.astral.sh/uv/concepts/workspaces/)
- [Understanding Event Sourcing](https://leanpub.com/understanding-eventsourcing) - Processor/Todo pattern
