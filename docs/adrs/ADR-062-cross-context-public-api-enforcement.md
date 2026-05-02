# ADR-062: Cross-Context Public API Enforcement

- **Status:** Accepted
- **Date:** 2026-04-14
- **Context:** Bounded context encapsulation, architectural fitness functions
- **Related:** ADR-020 (bounded context conventions), ADR-008 (projection composition root)

## Problem

A VSA audit of cross-context imports found **59 files with deep imports** reaching
into foreign bounded context internals (`slices/`, `domain/aggregate_*/`,
`domain/commands/`, `_shared/`, etc.) instead of importing through the context's
public API package.

This coupling creates several problems:

1. **Fragile consumers.** Renaming an internal module breaks every file that
   imports it directly. A public API absorbs internal refactors.
2. **Invisible contracts.** Without an explicit public surface, there is no way
   to distinguish "intended for external use" from "implementation detail."
3. **Unchecked growth.** Without CI enforcement, every new feature adds more
   deep imports. The coupling graph only gets worse.

## Decision

**Every bounded context must expose a public API via `__init__.py`. Cross-context
consumers must import through `contexts.<ctx>` or `contexts.<ctx>.ports`, never
through internal subpaths. CI fitness functions enforce this with ratcheted budgets.**

### Rules

1. **Public surface.** A context's public API is its `__init__.py` (re-exports)
   and its `ports/` subpackage (hexagonal port interfaces for adapter consumption).
   Everything else is internal.

2. **`__init__.py` must be non-empty.** Every active bounded context must have at
   least one re-export or `__all__` declaration. Enforced by
   `test_context_public_api_exists.py` (zero tolerance).

3. **No deep imports from foreign contexts.** A file in context A must not import
   `from syn_domain.contexts.B.slices.foo import Bar`. It must import
   `from syn_domain.contexts.B import Bar`. Enforced by
   `test_cross_context_public_api.py`.

4. **No private symbol imports.** Importing `_`-prefixed names from a foreign
   context is also a violation, even if the import path is the public package.

5. **TYPE_CHECKING imports are exempt.** Static analysis imports don't create
   runtime coupling and are needed for pyright to resolve types through lazy
   `__getattr__` patterns.

6. **Projection class imports are exempt.** Imports where all names match
   `*Projection` are legitimate per ADR-008's composition root pattern. The
   coordinator/manager legitimately imports projection classes from foreign
   context slices for subscription wiring.

7. **`_shared/` files are exempt.** Files inside `_shared/` directories serve
   multiple contexts by design and are not checked.

### Exception budget system

Violations that cannot be fixed immediately are grandfathered in
`ci/fitness/fitness_exceptions.toml` under the `[cross_context_public_api]`
section. Each entry specifies `deep_imports = N` (the maximum allowed count)
and an `issue` reference. Budgets are ratcheted: they can shrink but never grow.
New code that exceeds a budget fails CI.

### What goes in a context's `__init__.py`

Re-export everything that external consumers need:

- Aggregate classes
- Command and query dataclasses
- Command/query handler classes
- Value objects used in commands or API responses
- Domain events consumed by other contexts
- Projection factory functions (e.g., `get_repo_projection`)
- Port interfaces intended for adapter implementation
- Read model classes
- Shared constants and utility functions

Do not re-export purely internal types (e.g., private helpers, internal state
machines, test fixtures).

## Consequences

### Positive

- **59 violations reduced to 2.** The remaining 2 are adapter-layer coupling
  (`InMemoryTriggerQueryStore`, `_IndexedTrigger`) tracked at budget=1 each.
- **All 5 contexts now have comprehensive `__init__.py` files** with explicit
  `__all__` declarations documenting the public surface.
- **CI prevents regression.** Any new deep cross-context import fails the
  fitness test immediately.
- **Refactoring is safer.** Internal module restructuring no longer risks
  breaking consumers in other contexts.

### Negative

- **Large `__init__.py` files.** The orchestration context exports ~40 symbols.
  This is manageable but should be monitored.
- **Lazy loading considerations.** The orchestration domain `__init__.py` uses
  `__getattr__` for aggregate lazy imports to avoid circular dependencies.
  This pattern requires parallel `TYPE_CHECKING` imports for pyright resolution.

## Implementation

| File | Role |
|------|------|
| `ci/fitness/code_quality/test_cross_context_public_api.py` | Primary enforcement |
| `ci/fitness/code_quality/test_context_public_api_exists.py` | Public API gate |
| `ci/fitness/fitness_exceptions.toml` `[cross_context_public_api]` | Ratcheted budgets |
| `ci/fitness/_imports.py` `all_imports()` | AST walker for function-body lazy imports |
| `docs/fitness-functions.md` | Central fitness function registry |
| `packages/syn-domain/src/syn_domain/contexts/*/\__init__.py` | Context public APIs |
