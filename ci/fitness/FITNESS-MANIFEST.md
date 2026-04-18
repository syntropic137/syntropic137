# Fitness Manifest

Maps architectural principles (from `docs/architecture/architectural-fitness.md`)
to CI-enforced tests. Every principle should have at least one automated check.
If a principle has no test, it is a gap.

Standard: [ADR-062](../../docs/adrs/ADR-062-architectural-fitness-function-standard.md)

Two toolchains enforce fitness:
- **APSS** (`fitness.toml`): Declarative thresholds for complexity, LOC, coupling
- **pytest** (`ci/fitness/`): Structural invariant tests using AST analysis

Run both: `just fitness`

## Quick Reference

| # | Principle | Tests | Config | Status |
|---|-----------|-------|--------|--------|
| 1 | Single Ownership | test_event_ownership, test_event_sourcing_patterns | fitness_exceptions.toml `[event_sourcing_handle_command]` | Enforced |
| 2 | Separation of Concerns | test_layer_separation, test_dependency_direction, test_bounded_context_isolation | fitness_exceptions.toml `[layer_separation, bounded_context_isolation]` | Enforced |
| 3 | Replay Safety | test_esp_fitness (projection purity), test_aggregate_purity | fitness_exceptions.toml `[projection_purity]` | Enforced |
| 4 | Idempotency | test_dedup_durability (F3) | - | Enforced |
| 5 | Startup Contract | test_restart_safety (F2) | - | Enforced |
| 6 | Temporal Clarity | test_projection_wiring (subscriptions) | - | Enforced |
| 7 | Cost Boundaries | test_cost_ceiling (F7) | - | Enforced |
| 8 | Boundary Clarity | test_layer_separation, test_dependency_direction | fitness_exceptions.toml `[layer_separation]` | Enforced |
| 9 | Scalability | test_in_memory_state_audit | fitness_exceptions.toml `[in_memory_state]` | Enforced |

## Configuration Surfaces

### 1. `fitness.toml` (APSS declarative thresholds)

Controls complexity, size, and coupling budgets evaluated by `aps run fitness validate .`.

| Rule | Threshold | Level |
|------|-----------|-------|
| Cognitive complexity (function) | <= 15 | error |
| Cyclomatic complexity (function) | <= 10 | error |
| LOC per function | <= 100 | warning |
| LOC per file | <= 750 | error |
| Fan-out per module | <= 30 | error |

Exceptions in `fitness-exceptions.toml` (APSS format, separate from the pytest one).

### 2. `ci/fitness/fitness_exceptions.toml` (pytest structural checks)

Grandfathered violations and registries for pytest-based fitness tests.
Every entry MUST reference a GitHub issue. Budgets are ratchets - they
can only decrease, never increase.

Sections:
- `[layer_separation]` - domain files importing from adapters
- `[bounded_context_isolation]` - files exceeding context import limits
- `[event_sourcing_handle_command]` - direct _handle_command() calls
- `[event_construction_outside_aggregate]` - DomainEvent construction outside aggregates
- `[projection_purity]` - project-specific allowed import prefixes
- `[in_memory_state]` - registry of in-memory state requiring classification

### 3. Inline in test files (being migrated to TOML)

Legacy: some tests define config inline. Being consolidated into
`fitness_exceptions.toml` for single-source-of-truth.

## Test Inventory

### Event Sourcing (`ci/fitness/event_sourcing/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_aggregate_purity | Aggregates: no IO, no async, no infra imports | 3, 8 |
| test_esp_fitness | Projection purity (whitelist), ProcessManager structure | 3 |
| test_event_ownership | Events only constructed in aggregate_*/ dirs | 1 |
| test_event_sourcing_patterns | @command_handler used, not _handle_command() | 1 |
| test_projection_data_flow | Projections declare subscriptions, have names, valid versions | 6 |
| test_projection_registry | Coordinator and manager registry consistent | 6 |
| test_projection_wiring | Correct projection count, unique names, handlers exist | 6 |
| test_aggregate_guards | @command_handler methods have precondition guards before _apply() | 1 |
| test_restart_safety | Catch-up replay produces zero process_pending() calls | 3, 5 |
| test_dedup_durability | Pipeline uses durable, content-based dedup; dedup port is wired | 4 |

### Code Quality (`ci/fitness/code_quality/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_bounded_context_isolation | Max N foreign context imports per file | 2, 8 |
| test_dependency_direction | Package hierarchy: shared -> domain -> adapters -> api | 2, 8 |
| test_layer_separation | Domain doesn't import adapters/API at runtime | 2, 8 |
| test_error_propagation | No silent except: pass handlers | 2 |
| test_in_memory_state_audit | Every in-memory state var is classified | 9 |

### API (`ci/fitness/api/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_background_task_safety | BackgroundTasks closures handle errors | 2 |
| test_cost_query_separation | Cost routes use query services, not projection stores | 8 |
| test_prefix_resolver_coverage | GET /{id} endpoints use resolve_or_raise() | 8 |
| test_cost_ceiling | Dispatch chain has rate limit + budget check wired, config bounded | 7 |

### Infrastructure (`ci/fitness/infrastructure/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_compose_consistency | Docker Compose valid, build args match Dockerfiles | 8 |
| test_phase_definition_roundtrip | PhaseDefinition serialization is lossless | 8 |
| test_proxy_hostname_agreement | Envoy/injector/proxy URL configs agree | 8 |

## Writing New Fitness Tests

Every fitness test file follows this contract:

1. **One file per invariant.** Don't combine unrelated checks.
2. **Config in TOML.** Whitelists, registries, and exceptions go in `fitness_exceptions.toml`.
3. **Reference the principle.** Docstring names which of the 9 principles it enforces.
4. **Actionable failures.** Messages explain HOW to fix, not just WHAT failed.
5. **Use `@pytest.mark.architecture`** on every test class.
6. **Static over dynamic.** Prefer AST analysis. Integration tests get `@pytest.mark.integration`.

```python
"""Fitness function: <name>.

<What invariant this enforces.>
Principle: <N>. <Name> (docs/architecture/architectural-fitness.md)
"""

import pytest
from ci.fitness.conftest import repo_root, production_files, load_exceptions, rel_path

@pytest.mark.architecture
class TestMyInvariant:
    def test_the_thing(self) -> None:
        """<What this checks.>"""
        # ... AST analysis, import checking, grep, etc.
        if violations:
            pytest.fail(
                f"Found {len(violations)} violation(s):\n"
                f"  {joined}\n\n"
                "To fix: <specific instructions>"
            )
```

## Shared Helpers (`ci/fitness/conftest.py`)

- `repo_root()` - repository root Path
- `production_files(root)` - all .py files under apps/*/src and packages/*/src
- `load_exceptions(root)` - full fitness_exceptions.toml as dict
- `rel_path(path, root)` - normalize path for exception key lookup

## Shared Utilities

- `ci/fitness/_imports.py` - AST-based import analysis (ImportInfo, extract_imports, runtime_imports)
- `ci/fitness/_event_discovery.py` - scan domain/events/ for @event-decorated classes
- `ci/fitness/event_sourcing/conftest.py` - aggregate_files() discovery
