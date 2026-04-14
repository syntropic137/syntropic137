# Architectural Fitness Functions

Central registry of all CI-enforced structural checks. Run the full suite with:

```bash
uv run pytest ci/fitness/ -v --tb=short -m architecture
```

Or via Just: `just fitness-invariants`

## Categories

### Code Quality (`code_quality/`)

Enforce bounded context isolation, dependency direction, and layer separation.

| Check | File | What it enforces | Exceptions key |
|-------|------|------------------|----------------|
| Cross-context public API | `test_cross_context_public_api.py` | Imports from foreign contexts must go through `contexts.<ctx>` or `contexts.<ctx>.ports`, not internal paths | `[cross_context_public_api]` |
| Context public API exists | `test_context_public_api_exists.py` | Every bounded context must have a non-empty `__init__.py` with re-exports | (zero tolerance) |
| Bounded context isolation | `test_bounded_context_isolation.py` | Each file should import from at most 1 foreign bounded context | `[bounded_context_isolation]` |
| Layer separation | `test_layer_separation.py` | Domain layer must not import from adapter or API layers | `[layer_separation]` |
| Dependency direction | `test_dependency_direction.py` | Dependencies flow inward: API -> Adapters -> Domain, never reversed | (zero tolerance) |

### Event Sourcing (`event_sourcing/`)

Enforce event sourcing invariants and aggregate purity.

| Check | File | What it enforces | Exceptions key |
|-------|------|------------------|----------------|
| Aggregate purity | `test_aggregate_purity.py` | Aggregates must not import infrastructure (IO, HTTP, DB) | (zero tolerance) |
| Event ownership | `test_event_ownership.py` | Domain events constructed only inside aggregate directories | `[event_construction_outside_aggregate]` |
| ES patterns | `test_event_sourcing_patterns.py` | `_handle_command()` called only from aggregate methods | `[event_sourcing_handle_command]` |
| Projection data flow | `test_projection_data_flow.py` | Projections subscribe to events and implement required interfaces | (zero tolerance) |
| Projection registry | `test_projection_registry.py` | All projections registered in the coordinator service | (zero tolerance) |
| Projection wiring | `test_projection_wiring.py` | Projection subscriptions match aggregate event types | (zero tolerance) |

### API (`api/`)

Enforce API layer conventions.

| Check | File | What it enforces | Exceptions key |
|-------|------|------------------|----------------|
| Background task safety | `test_background_task_safety.py` | `BackgroundTasks` closures check `Result` errors | (zero tolerance) |
| Cost query separation | `test_cost_query_separation.py` | Cost queries use dedicated query services, not raw DB access | (zero tolerance) |
| Prefix resolver coverage | `test_prefix_resolver_coverage.py` | API route prefixes match resolver configuration | (zero tolerance) |

### Infrastructure (`infrastructure/`)

Enforce deployment and configuration consistency.

| Check | File | What it enforces | Exceptions key |
|-------|------|------------------|----------------|
| Compose consistency | `test_compose_consistency.py` | Docker Compose files are consistent across environments | (zero tolerance) |
| Phase definition roundtrip | `test_phase_definition_roundtrip.py` | Phase definitions serialize/deserialize without data loss | (zero tolerance) |
| Proxy hostname agreement | `test_proxy_hostname_agreement.py` | Proxy hostnames match between services | (zero tolerance) |

## Exception Budget System

Grandfathered violations are tracked in `fitness_exceptions.toml`. Each entry has:
- A **budget** (maximum allowed violations) - ratcheted to current count
- An **issue** reference for the planned fix

Budgets can only shrink. Adding code that exceeds a budget fails CI. The goal is to drive all budgets to zero over time.

## Shared Infrastructure

| File | Purpose |
|------|---------|
| `conftest.py` | `repo_root()`, `load_exceptions()`, `rel_path()`, `production_files()`, `@pytest.mark.architecture` |
| `_imports.py` | `ImportInfo`, `extract_imports()`, `runtime_imports()`, `all_imports()` - AST-based import analysis |
| `_event_discovery.py` | Event class discovery for ES fitness checks |
| `fitness_exceptions.toml` | Ratcheted exception budgets for all checks |
