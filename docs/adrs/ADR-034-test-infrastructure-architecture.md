# ADR-034: Test Infrastructure Architecture

**Status:** Accepted
**Date:** 2025-12-20
**Deciders:** Engineering Team
**Related:** ADR-033 (Recording-Based Integration Testing)

## Context

AEF requires different testing modes:

1. **Unit tests** - Fast, no infrastructure, run in CI
2. **Integration tests** - Test full pipeline with real services
3. **Development** - Persistent data for manual testing and debugging

The challenge is enabling developers to:
- Run integration tests while simultaneously using the dev stack
- Have ephemeral, clean-slate test infrastructure
- Support CI without manual infrastructure setup

### Current State

- Single `docker-compose.dev.yaml` with all services
- No separation between dev and test infrastructure
- Integration tests either skip or require manual setup
- CI cannot run true integration tests

### Requirements

1. Dev stack and test stack must run simultaneously
2. Test stack must be ephemeral (clean slate on restart)
3. CI must work without pre-running infrastructure (testcontainers fallback)
4. No code duplication in Docker Compose files
5. Clear, explicit naming conventions

## Decision

### 1. DRY Docker Compose with Override Files

Use Docker Compose's multi-file feature to maintain a single source of truth:

```
docker/
├── docker-compose.yaml        # Base: all service definitions
├── docker-compose.dev.yaml    # Dev overrides: ports, volumes
└── docker-compose.test.yaml   # Test overrides: offset ports, no volumes
```

The base file contains:
- Service images and build contexts
- Environment variables
- Health checks
- Service dependencies

Override files add:
- Port mappings (different per environment)
- Volume mounts (dev only)
- Container names (prefixed per environment)

### 2. Port Offset Strategy

Test stack uses ports offset by +10000 from dev:

| Service | Dev Port | Test Port | Internal Port |
|---------|----------|-----------|---------------|
| TimescaleDB | 5432 | 15432 | 5432 |
| EventStore | 50051 | 55051 | 50051 |
| Collector | 8080 | 18080 | 8080 |
| MinIO API | 9000 | 19000 | 9000 |
| MinIO Console | 9001 | 19001 | 9001 |
| Redis | 6379 | 16379 | 6379 |

This allows both stacks to run simultaneously without conflicts.

### 3. Container Naming Convention

- Dev: `aef-{service}` (e.g., `syn-db`, `syn-collector`)
- Test: `syn-test-{service}` (e.g., `syn-test-db`, `syn-test-collector`)

### 4. Volume Strategy

- **Dev stack**: Named volumes for persistence across restarts
- **Test stack**: No volumes (ephemeral, clean slate)

### 5. Test Fixture Detection Pattern

Following the es-p pattern, test fixtures:

1. Check for explicit environment variables (`TEST_DATABASE_URL`)
2. Probe test-stack ports to detect if running
3. Fall back to testcontainers for CI

```python
from syn_shared.testing import (
    ENV_TEST_DATABASE_URL,
    ENV_TEST_TIMESCALEDB_HOST,
    TEST_STACK_PORTS,
)

async def get_test_infrastructure():
    # 1. Explicit env var (use constants, not magic strings!)
    if os.environ.get(ENV_TEST_DATABASE_URL) or os.environ.get(ENV_TEST_TIMESCALEDB_HOST):
        return from_env_vars()

    # 2. Test-stack running? (use centralized port constants)
    if _check_port_open("localhost", TEST_STACK_PORTS["timescaledb"]):
        return _get_test_stack_infrastructure()

    # 3. Fallback to testcontainers
    return await _get_testcontainer_infrastructure()
```

**Important:** Always use constants from `syn_shared.testing` - never hardcode port numbers or environment variable names. See ADR-038 for full DRY patterns.

### 6. Justfile Commands

```bash
# Development
just dev              # Start dev stack (persistent)
just dev-stop         # Stop dev stack
just dev-down         # Remove dev stack

# Testing
just test-stack       # Start test stack (ephemeral)
just test-stack-down  # Remove test stack (with volumes)
just test-integration # Run integration tests
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LOCAL DEVELOPMENT                                    │
│                                                                             │
│   ┌─────────────────────────┐     ┌─────────────────────────┐              │
│   │      DEV STACK          │     │      TEST STACK         │              │
│   │  (just dev)             │     │  (just test-stack)      │              │
│   ├─────────────────────────┤     ├─────────────────────────┤              │
│   │ TimescaleDB: 5432       │     │ TimescaleDB: 15432      │              │
│   │ EventStore: 50051       │     │ EventStore: 55051       │              │
│   │ Collector: 8080         │     │ Collector: 18080        │              │
│   │ MinIO: 9000/9001        │     │ MinIO: 19000/19001      │              │
│   │ Redis: 6379             │     │ Redis: 16379            │              │
│   ├─────────────────────────┤     ├─────────────────────────┤              │
│   │ Volumes: PERSISTENT     │     │ Volumes: NONE           │              │
│   │ Network: syn-network    │     │ Network: syn-test-network│             │
│   └─────────────────────────┘     └─────────────────────────┘              │
│             │                               │                               │
│             ▼                               ▼                               │
│   ┌─────────────────────────┐     ┌─────────────────────────┐              │
│   │   Manual Testing        │     │   Automated Tests       │              │
│   │   Dashboard UI          │     │   pytest -m integration │              │
│   │   CLI Commands          │     │   Continuous testing    │              │
│   └─────────────────────────┘     └─────────────────────────┘              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              CI/CD                                          │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                      TESTCONTAINERS                                  │  │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐                          │  │
│   │  │ Postgres │  │  Redis   │  │   ...    │  Random ports, ephemeral │  │
│   │  │  :32768  │  │  :32769  │  │          │                          │  │
│   │  └──────────┘  └──────────┘  └──────────┘                          │  │
│   │                                                                      │  │
│   │  Auto-created by pytest fixtures when test-stack not detected       │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Test Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        INTEGRATION TEST FLOW                                │
│                                                                             │
│  ┌─────────────┐    ┌─────────────────────────────────────────────────┐    │
│  │  Recording  │    │              Test Fixture                       │    │
│  │  (JSONL)    │    │                                                 │    │
│  └──────┬──────┘    │  1. Check TEST_DATABASE_URL env var             │    │
│         │           │     └─► Use explicit config                     │    │
│         ▼           │                                                 │    │
│  ┌─────────────┐    │  2. Probe test-stack ports (15432, etc.)       │    │
│  │  Adapter    │    │     └─► Use test-stack if running              │    │
│  │  (Python)   │    │                                                 │    │
│  └──────┬──────┘    │  3. Fallback: spin up testcontainers           │    │
│         │           │     └─► Ephemeral, random ports                │    │
│         ▼           └─────────────────────────────────────────────────┘    │
│  ┌─────────────┐                        │                                   │
│  │  Collector  │◄───────────────────────┘                                   │
│  │   (POST)    │                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────┐                                                            │
│  │ TimescaleDB │                                                            │
│  │  (INSERT)   │                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────┐                                                            │
│  │  Dashboard  │                                                            │
│  │    API      │                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────┐                                                            │
│  │   Assert    │                                                            │
│  │  (Verify)   │                                                            │
│  └─────────────┘                                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Consequences

### Positive

1. **DRY Configuration** - Single source of truth for service definitions
2. **Simultaneous Stacks** - Dev and test run without conflicts
3. **Clean Slate Testing** - Test stack is ephemeral, predictable
4. **CI Compatible** - Testcontainers fallback requires no manual setup
5. **Fast Local Tests** - Reuse running test-stack (50ms vs 30s startup)
6. **Explicit Naming** - Clear distinction between dev and test

### Negative

1. **Port Memorization** - Developers need to remember offset ports
2. **Resource Usage** - Running both stacks doubles resource consumption
3. **Complexity** - Three compose files instead of one

### Mitigations

1. **Port Memorization** - Document in justfile help output; use just commands
2. **Resource Usage** - Test stack can be stopped when not needed
3. **Complexity** - Override files are small; base file is the source of truth

## Alternatives Considered

### 1. Single Docker Compose with Profiles

```yaml
services:
  timescaledb:
    profiles: [dev, test]
```

**Rejected because:** Cannot run both profiles simultaneously on different ports.

### 2. Environment Variable Port Configuration

```yaml
ports:
  - "${DB_PORT:-5432}:5432"
```

**Rejected because:** More error-prone; requires setting many variables.

### 3. Testcontainers Only (No Test Stack)

Always use testcontainers for integration tests.

**Rejected because:** 30+ second startup per test run is too slow for continuous testing during development.

## Implementation

See: `PROJECT-PLAN_20251220_TEST-INFRASTRUCTURE.md`

## References

- [Docker Compose Multiple Files](https://docs.docker.com/compose/multiple-compose-files/)
- [Testcontainers Python](https://testcontainers-python.readthedocs.io/)
- [es-p Test Infrastructure Pattern](../lib/event-sourcing-platform/event-store/eventstore-backend-postgres/tests/common/mod.rs)
- [ADR-033: Recording-Based Integration Testing](./ADR-033-recording-based-integration-testing.md)
