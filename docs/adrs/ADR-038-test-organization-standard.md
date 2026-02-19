# ADR-038: Test Organization Standard

**Status:** Accepted
**Date:** 2026-01-26
**Deciders:** Engineering Team
**Related:** ADR-034 (Test Infrastructure Architecture), ADR-008 (VSA Projection Architecture)

## Context

AEF uses Vertical Slice Architecture (VSA) where each feature is a self-contained "slice" with its own command, handler, and tests. However, test organization has become inconsistent:

### Current State (Problems)

| Pattern | Location | Problem |
|---------|----------|---------|
| Co-located | `src/.../slices/start_session/test_start_session.py` | Good for slices |
| Separate | `tests/events/test_integration.py` | Good for integration |
| Mixed | `src/syn_adapters/.../test_memory_adapter.py` | Tests shipped in package |

### Issues

1. **Inconsistent** - syn-domain uses co-located, syn-adapters uses separate
2. **Tests in src/** - Some tests live in `src/` and get shipped with the package
3. **No standard** - New contributors don't know where to put tests
4. **Type safety** - Tests used raw dicts that could drift from schemas

### Requirements

1. Clear, documented convention for test placement
2. VSA slices remain self-contained (co-located tests)
3. Integration/cross-slice tests have a home
4. Type-safe event creation to catch schema drift
5. Centralized test constants (no hardcoded strings)

## Decision

### 1. Hybrid Test Organization

**Rule: Co-located for slices, separate for integration**

```
packages/syn-domain/
├── src/syn_domain/
│   └── contexts/
│       └── sessions/
│           └── slices/
│               └── start_session/
│                   ├── command.py
│                   ├── handler.py
│                   └── test_start_session.py  ← CO-LOCATED (unit)
└── tests/
    └── integration/
        └── test_session_roundtrip.py          ← SEPARATE (integration)

packages/syn-adapters/
├── src/syn_adapters/
│   └── events/
│       └── store.py                           ← NO tests in src/
└── tests/
    ├── events/
    │   ├── test_integration.py                ← Integration tests
    │   └── test_models.py                     ← Unit tests for models
    └── workspace_backends/
        └── test_memory_adapter.py             ← Adapter unit tests
```

### 2. Test Location Decision Tree

```
Is it testing a VSA slice (command/handler)?
├── YES → Co-locate in slice folder: src/.../slices/foo/test_foo.py
└── NO → Put in tests/ directory
    │
    Is it an integration test (requires infrastructure)?
    ├── YES → tests/integration/test_*.py
    └── NO → tests/{module}/test_*.py
```

### 3. Type-Safe Event Factories

All test event creation MUST use typed factories from `syn_shared.events.factories`:

```python
# ❌ BAD: Raw dicts (no type checking, can drift from schema)
event = {
    "event_type": "tool_execution_started",
    "session_id": session_id,
    "tool_name": "Read",
}

# ✅ GOOD: Type-safe factory (IDE autocomplete, type errors on drift)
from syn_shared.events.factories import tool_started

event = tool_started(
    session_id=session_id,
    tool_name="Read",
    tool_use_id="t1",
)
```

**Available Factories:**

| Factory | Required Args | Returns |
|---------|---------------|---------|
| `tool_started()` | `session_id`, `tool_name`, `tool_use_id` | Event dict |
| `tool_completed()` | `session_id`, `tool_name`, `tool_use_id`, `success` | Event dict |
| `session_started()` | `session_id` | Event dict |
| `session_completed()` | `session_id` | Event dict |
| `token_usage()` | `session_id`, `input_tokens`, `output_tokens` | Event dict |

### 4. Centralized Constants

All test configuration MUST use centralized constants:

```python
# ❌ BAD: Hardcoded strings
"tool_execution_started"
"TEST_TIMESCALEDB_HOST"
15432

# ✅ GOOD: Centralized constants
from syn_shared.events import TOOL_EXECUTION_STARTED
from syn_shared.testing import ENV_TEST_TIMESCALEDB_HOST, TEST_STACK_PORTS

TOOL_EXECUTION_STARTED  # "tool_execution_started"
ENV_TEST_TIMESCALEDB_HOST  # "TEST_TIMESCALEDB_HOST"
TEST_STACK_PORTS["timescaledb"]  # 15432
```

### 5. CI Integration Test Schedule

Integration tests run on:
- Weekly cron (Sunday 2am UTC)
- Pushes to main branch
- Manual workflow dispatch

NOT on feature branch PRs (unit tests sufficient for fast iteration).

## Test Location Summary

| What | Where | Example |
|------|-------|---------|
| Slice unit tests | Co-located in slice | `src/.../slices/foo/test_foo.py` |
| Model unit tests | `tests/{module}/` | `tests/events/test_models.py` |
| Adapter unit tests | `tests/{adapter}/` | `tests/workspace_backends/test_*.py` |
| Integration tests | `tests/integration/` | `tests/integration/test_e2e.py` |
| E2E tests | `aef_tests/integration/` | Root-level cross-package E2E |
| Shared fixtures | `aef_tests/fixtures/` | Infrastructure, factories |

## Consequences

### Positive

1. **Consistent** - Clear rules for where tests belong
2. **Self-contained slices** - VSA pattern preserved
3. **Type safety** - Schema drift caught at compile time
4. **DRY** - No hardcoded strings scattered across tests
5. **IDE support** - Autocomplete for events and constants
6. **Clean packages** - No tests shipped in src/

### Negative

1. **Migration effort** - Existing tests need moving
2. **Learning curve** - New pattern to learn
3. **Import overhead** - Must import factories/constants

### Mitigations

1. **Migration** - Gradual; fix as we touch files
2. **Learning curve** - ADR serves as reference
3. **Import overhead** - Small price for type safety

## Files to Migrate

The following tests currently violate the standard:

```
❌ packages/syn-adapters/src/syn_adapters/workspace_backends/memory/test_memory_adapter.py
   → Move to: packages/syn-adapters/tests/workspace_backends/test_memory_adapter.py

❌ packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_workspace_service.py
   → Move to: packages/syn-adapters/tests/workspace_backends/test_workspace_service.py

❌ packages/syn-adapters/src/syn_adapters/workspace_backends/tokens/test_token_adapters.py
   → Move to: packages/syn-adapters/tests/workspace_backends/test_token_adapters.py
```

## Implementation Checklist

- [x] Create `syn_shared.events.factories` module
- [x] Create `syn_shared.testing` module with constants
- [x] Update test files to use factories
- [x] Update test files to use constants
- [x] Enable weekly CI integration tests
- [ ] Move misplaced test files (gradual)
- [ ] Add pre-commit hook to detect raw event dicts

## References

- [ADR-034: Test Infrastructure Architecture](./ADR-034-test-infrastructure-architecture.md)
- [ADR-008: VSA Projection Architecture](./ADR-008-vsa-projection-architecture.md)
- [syn_shared.events.factories](/packages/syn-shared/src/syn_shared/events/factories.py)
- [syn_shared.testing](/packages/syn-shared/src/syn_shared/testing/__init__.py)
