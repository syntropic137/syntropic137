# ADR-062: Architectural Fitness Function Standard

## Status

Accepted

## Date

2026-04-14

## Related

- ADR-035: QA Workflow Standard (fitness runs as part of `just qa`)
- ADR-055: Projection Checkpoint Coordinator Architecture (fitness test for wiring)
- `docs/architecture/architectural-fitness.md`: the 9 principles these tests enforce
- `ci/fitness/FITNESS-MANIFEST.md`: human-readable index mapping principles to tests

## Context

The architecture audit of 2026-04-13 found that 5 of 7 restart-safety
invariants were broken. Fixes shipped across PRs #674-#690, but without
automated enforcement the invariants would drift back as the codebase
evolves. Manual code review cannot reliably catch structural violations
like "projections must not import adapters" or "command handlers must
have precondition guards" - these require machine-checked invariants.

Two complementary enforcement needs emerged:

1. **Metric thresholds** - cognitive complexity, cyclomatic complexity,
   LOC, fan-out. These are numeric budgets that tools like APSS handle
   declaratively.

2. **Structural invariants** - "aggregates must not import from
   adapters", "every projection must declare subscriptions", "the
   dispatch chain must wire a budget check". These require AST analysis
   and cannot be expressed as simple numeric thresholds.

No single tool covered both needs. APSS handles (1) well but cannot
express (2). pytest with AST analysis handles (2) but would be
over-engineered for (1).

## Decision

### Two-toolchain approach

**APSS** (`fitness.toml`) enforces metric thresholds:

| Rule | Threshold | Level |
|------|-----------|-------|
| Cognitive complexity (function) | <= 15 | error |
| Cyclomatic complexity (function) | <= 10 | error |
| LOC per function | <= 100 | warning |
| LOC per file | <= 750 | error |
| Fan-out per module | <= 30 | error |

APSS exceptions go in `fitness-exceptions.toml` (APSS format, separate
from the pytest config).

**pytest** (`ci/fitness/`) enforces structural invariants using AST
analysis, import checking, and parameterized tests. Tests are organized
by domain:

- `ci/fitness/event_sourcing/` - aggregate purity, projection patterns, replay safety
- `ci/fitness/code_quality/` - layer separation, dependency direction, context isolation
- `ci/fitness/api/` - cost controls, background task safety, resolver coverage
- `ci/fitness/infrastructure/` - Docker Compose, phase definitions, proxy config

Both toolchains run via `just fitness`.

### 9 architectural principles, each with at least one test

Every test maps back to one of the 9 principles defined in
`docs/architecture/architectural-fitness.md`:

| # | Principle | Key Tests |
|---|-----------|-----------|
| 1 | Single Ownership | test_event_ownership, test_event_sourcing_patterns, test_aggregate_guards |
| 2 | Separation of Concerns | test_layer_separation, test_dependency_direction, test_bounded_context_isolation |
| 3 | Replay Safety | test_esp_fitness (projection purity), test_aggregate_purity |
| 4 | Idempotency | test_dedup_durability |
| 5 | Startup Contract | test_restart_safety |
| 6 | Temporal Clarity | test_projection_wiring, test_projection_data_flow |
| 7 | Cost Boundaries | test_cost_ceiling |
| 8 | Boundary Clarity | test_layer_separation, test_dependency_direction |
| 9 | Scalability | test_in_memory_state_audit |

The full mapping with config surfaces is in `ci/fitness/FITNESS-MANIFEST.md`.

### Configuration surfaces

1. **`fitness.toml`** - APSS declarative thresholds (complexity, LOC, coupling)
2. **`ci/fitness/fitness_exceptions.toml`** - pytest structural check config:
   registries, whitelists, grandfathered violations, exempt methods.
   Single source of truth for all pytest fitness configuration.
3. **`ci/fitness/FITNESS-MANIFEST.md`** - human-readable index mapping
   principles to tests, config, and status. Not machine-read, but the
   entry point for understanding what CI enforces.

### Ratcheting exceptions

Exception budgets in `fitness_exceptions.toml` are ratchets - they can
only decrease, never increase. Every entry MUST reference a GitHub issue.
This ensures grandfathered violations are tracked and eventually resolved.

### Test contract for new fitness tests

Every fitness test file follows this pattern:

```python
"""Fitness function: <name>.

<What invariant this enforces.>
Principle: <N>. <Name> (docs/architecture/architectural-fitness.md)
Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

import pytest
from ci.fitness.conftest import repo_root, production_files, load_exceptions, rel_path

@pytest.mark.architecture
class TestMyInvariant:
    def test_the_thing(self) -> None:
        """<What this checks.>"""
        if violations:
            pytest.fail(
                f"Found {len(violations)} violation(s):\n"
                f"  {joined}\n\n"
                "To fix: <specific instructions>"
            )
```

Rules:

1. **One file per invariant.** Don't combine unrelated checks.
2. **Config in TOML, not inline.** Whitelists, registries, and
   exception lists go in `fitness_exceptions.toml`.
3. **Reference the principle.** Module docstring names which of the
   9 principles it enforces.
4. **Reference this ADR.** Module docstring includes the `Standard:`
   line so the ADR stays discoverable when editing any fitness file.
5. **Actionable failure messages.** Messages explain HOW to fix, not
   just WHAT failed.
6. **Use `@pytest.mark.architecture`** on every test class.
7. **Static over dynamic.** Prefer AST analysis over runtime checks.
   Integration tests get the additional `@pytest.mark.integration`
   marker.

### Shared helpers

- `ci/fitness/conftest.py` - `repo_root()`, `production_files()`,
  `load_exceptions()`, `rel_path()`, `pytest_configure()`
- `ci/fitness/_imports.py` - AST-based import analysis (`ImportInfo`,
  `extract_imports`, `runtime_imports`)
- `ci/fitness/_event_discovery.py` - scan `domain/events/` for
  `@event`-decorated classes
- `ci/fitness/event_sourcing/conftest.py` - `aggregate_files()` discovery

## Consequences

**Positive:**

- Architectural invariants survive team turnover - knowledge is encoded
  in CI, not in people's heads
- New fitness tests follow a consistent, documented pattern
- Single index (`FITNESS-MANIFEST.md`) answers "what does CI enforce?"
  without reading 20+ files
- Ratcheting prevents exception budgets from growing over time
- Back-references in every fitness file keep this ADR discoverable

**Negative:**

- New fitness tests require understanding two toolchains (APSS + pytest)
- AST-based checks are brittle to major refactors (but that is the
  point - they force intentional changes with explicit exception updates)
- Configuration split across two TOML files (`fitness.toml` for APSS,
  `fitness_exceptions.toml` for pytest) requires knowing which tool
  owns which config

## References

### Test files

Event Sourcing:
- `ci/fitness/event_sourcing/test_aggregate_guards.py`
- `ci/fitness/event_sourcing/test_aggregate_purity.py`
- `ci/fitness/event_sourcing/test_dedup_durability.py`
- `ci/fitness/event_sourcing/test_esp_fitness.py`
- `ci/fitness/event_sourcing/test_event_ownership.py`
- `ci/fitness/event_sourcing/test_event_sourcing_patterns.py`
- `ci/fitness/event_sourcing/test_projection_data_flow.py`
- `ci/fitness/event_sourcing/test_projection_registry.py`
- `ci/fitness/event_sourcing/test_projection_wiring.py`
- `ci/fitness/event_sourcing/test_restart_safety.py`

Code Quality:
- `ci/fitness/code_quality/test_bounded_context_isolation.py`
- `ci/fitness/code_quality/test_dependency_direction.py`
- `ci/fitness/code_quality/test_error_propagation.py`
- `ci/fitness/code_quality/test_in_memory_state_audit.py`
- `ci/fitness/code_quality/test_layer_separation.py`

API:
- `ci/fitness/api/test_background_task_safety.py`
- `ci/fitness/api/test_cost_ceiling.py`
- `ci/fitness/api/test_cost_query_separation.py`
- `ci/fitness/api/test_prefix_resolver_coverage.py`

Infrastructure:
- `ci/fitness/infrastructure/test_compose_consistency.py`
- `ci/fitness/infrastructure/test_phase_definition_roundtrip.py`
- `ci/fitness/infrastructure/test_proxy_hostname_agreement.py`

### Configuration
- `fitness.toml` - APSS metric thresholds
- `ci/fitness/fitness_exceptions.toml` - pytest registries and exceptions
- `ci/fitness/FITNESS-MANIFEST.md` - human-readable principle-to-test index

### Shared code
- `ci/fitness/conftest.py` - shared fixtures and helpers
- `ci/fitness/_imports.py` - AST import analysis
- `ci/fitness/_event_discovery.py` - event class discovery
- `ci/fitness/event_sourcing/conftest.py` - aggregate file discovery

### Architecture
- `docs/architecture/architectural-fitness.md` - the 9 principles
