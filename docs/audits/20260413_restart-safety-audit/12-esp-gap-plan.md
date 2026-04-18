# 12 - ESP Gap Plan (Full Design)

**Status:** COMPLETE (design), IMPLEMENTED (0.1-0.5, 0.7), IN PROGRESS (0.6 VSA, tests)

## Context

The architectural fitness audit (docs 01-11) found that 5 of 7 invariants
are broken. The root cause is not in Syntropic137's application code - it
is in the event-sourcing-platform (ESP) itself. ESP provides exactly one
abstraction for event consumers (`CheckpointedProjection`) and that
abstraction is designed for read models. When Syn137 needed a process
manager, the only option was to put side effects in a projection. The
framework made the bug the path of least resistance.

**Strategy:** Fix ESP first. Then Syn137 inherits correct separation of
concerns by construction. Every future system built on ESP benefits.

---

## Gap Analysis

### Gap 1: No replay-mode awareness

**Current state:** The `SubscriptionCoordinator` knows when it is catching
up (it calculates min position vs live position) but does not communicate
this to projections. `EventEnvelope` has no replay flag. `handle_event()`
receives no context about whether the event is historical or live.

**File:** `event_sourcing/subscriptions/coordinator.py:311`
```python
result = await projection.handle_event(envelope, self._checkpoint_store)
```

**Impact:** Projections cannot distinguish replay from live processing.
Side-effecting projections fire during catch-up. This is the direct cause
of the replay storm bug.

**Fix:** `DispatchContext` dataclass with `is_catching_up` flag, passed
to `handle_event()` as an optional parameter (backwards-compatible).

---

### Gap 2: No ProcessManager base class

**Current state:** ESP has exactly one base class for event consumers:
`CheckpointedProjection`. This is designed for read models - pure state
reconstruction. There is no concept of a process manager, processor, or
any component that reacts to events with side effects.

**Impact:** When a system needs event-driven side effects, the developer
must either (a) put side effects in a projection (wrong, causes replay
storms) or (b) build a bespoke processor with no framework support (error-
prone, inconsistent). The framework makes option (a) the path of least
resistance.

**Fix:** `ProcessManager` base class implementing the Processor To-Do
List pattern (Dilger, Ch. 37). Two clearly separated parts: projection
side (read-only to-do list) and processor side (live-only execution).
The coordinator controls when each part runs.

---

### Gap 3: No projection purity enforcement

**Current state:** `CheckpointedProjection.handle_event()` is async and
unconstrained. A projection can import `httpx`, call external APIs, create
`asyncio` tasks, or launch containers. Purity is a convention enforced
by code review, not by the framework.

**Impact:** Nothing prevents a developer from accidentally adding side
effects to a projection. No warning, no error, no fitness check. The
violation is invisible until a replay storm happens.

**Fix:** Class-level `SIDE_EFFECTS_ALLOWED` marker. `CheckpointedProjection`
defaults to `False`. `ProcessManager` defaults to `True`. The coordinator
can warn or reject projections that claim purity but have side-effecting
imports (via AST analysis, similar to Syn137's existing `_imports.py`).

---

### Gap 4: No built-in fitness functions

**Current state:** ESP ships with: event store, projection framework,
checkpoint system, test kit (aggregate scenarios). It does NOT ship with
any architectural fitness checks. Individual projects must build their
own fitness tests from scratch.

**Impact:** Each project reinvents fitness validation. Violations are
caught late (in code review or production) instead of early (in CI). The
platform philosophy says "strong architectural guardrails" but the
guardrails are structural (VSA) not behavioral (replay safety, purity).

**Fix:** Ship a `fitness/` module with ESP. Projection purity check,
replay safety check, process manager idempotency check. Any project
using ESP runs them in CI with one import.

---

### Gap 5: No documentation of consumer patterns

**Current state:** ESP's documentation covers the event store, SDK
patterns, and VSA structure. It does not define:
- What a projection is allowed to do
- What a process manager is
- The To-Do List pattern
- The boundary between projection and processor
- When to use which consumer pattern

**Impact:** Developers (and AI agents) must learn these patterns from
external sources or from Syn137's AGENTS.md. The patterns are not part
of ESP's documented contract.

**Fix:** Add a consumer patterns guide to ESP docs. Define Projection,
ProcessManager, and the rules for each. Reference Dilger and the
glossary.

---

### Gap 6: VSA does not validate event consumer patterns

**Current state:** The VSA CLI validates structure (bounded contexts,
slices, imports, aggregate conventions). It does NOT validate event
consumer patterns (projection purity, handler classification, process
manager structure).

**Impact:** A projection with side-effecting imports passes VSA
validation. The structural rules are enforced but the behavioral rules
are not.

**Fix:** Add VSA validation rules for:
- Projection files must not import side-effecting modules
- ProcessManager subclasses must implement `process_pending()`
- ProcessManager subclasses must implement `get_idempotency_key()`
This requires extending the Rust `ValidationRule` trait in `vsa-core`.

---

### Gap 7: Test kit has no ProcessManager utilities

**Current state:** ESP's test kit (`event_sourcing/testing/scenario/`)
provides aggregate test scenarios (given events, when command, then
events). There are no test utilities for process managers - no way to
test the projection side independently from the processor side, no
way to verify idempotency, no way to simulate replay.

**Fix:** Add ProcessManager test utilities:
- `ProcessManagerScenario` - test projection side given events
- `IdempotencyTest` - verify `process_pending()` is idempotent
- `ReplaySimulator` - verify zero side effects during catch-up

---

## Implementation Plan

### Phase 0.1: DispatchContext (1 day) -- IMPLEMENTED

**What:** Add replay awareness to the coordinator dispatch path.

**Files changed:**
| File | Change |
|------|--------|
| `event_sourcing/core/checkpoint.py` | Added `DispatchContext` dataclass |
| `event_sourcing/core/checkpoint.py` | Updated `handle_event()` signature (optional `context` param) |
| `event_sourcing/subscriptions/coordinator.py` | Tracks catch-up state via `global_nonce` boundary |
| `event_sourcing/subscriptions/coordinator.py` | Creates and passes `DispatchContext` to projections |
| `event_sourcing/core/__init__.py` | Exports `DispatchContext` |
| `event_sourcing/__init__.py` | Exports `DispatchContext` |

**Implementation (as built):**
```python
@dataclass(frozen=True)
class DispatchContext:
    """Context provided by the coordinator to projections during dispatch."""
    is_catching_up: bool       # True during catch-up replay, False for live events
    global_nonce: int          # global_nonce of the current event (monotonic, from event store)
    live_boundary_nonce: int   # Head global_nonce at subscribe time (the boundary)

    @property
    def is_live(self) -> bool:
        return not self.is_catching_up
```

**Why `global_nonce` (not `global_position`):** The event store assigns
`global_nonce` at append time - it is the immutable, monotonic position
counter from the source of truth. Using the same name as the event store
field (`EventMetadata.global_nonce`) avoids ambiguity.

**Coordinator catch-up detection:** Before subscribing, snapshots the head
`global_nonce` via `read_all(forward=False, max_count=1)`. Events with
`global_nonce <= live_boundary_nonce` are historical. Events with
`global_nonce > live_boundary_nonce` are live. Transition is one-way
(catch-up -> live) and uses strict greater-than comparison.

**Backwards compatibility:** Confirmed - 146 existing tests pass unchanged.

---

### Phase 0.2: ProcessManager Base Class (2-3 days) -- IMPLEMENTED

**What:** New abstract base class for event-driven process managers.

**New file:** `event_sourcing/core/process_manager.py` -- CREATED

**Implementation matches design.** ProcessManager extends CheckpointedProjection
with `SIDE_EFFECTS_ALLOWED = True`, abstract `handle_event()` (projection side),
`process_pending()` (processor side), and `get_idempotency_key()`.

**Coordinator gating implemented:** After `handle_event()` returns SUCCESS,
coordinator checks `isinstance(projection, ProcessManager)` and
`not self._is_catching_up`. Only then calls `process_pending()`. Errors in
`process_pending()` are caught and logged (do not crash the coordinator).

**Files changed:**
| File | Change |
|------|--------|
| `event_sourcing/core/process_manager.py` | **New** - ProcessManager base class |
| `event_sourcing/subscriptions/coordinator.py` | Detects ProcessManager, gates `process_pending()` |
| `event_sourcing/core/__init__.py` | Exports `ProcessManager` |
| `event_sourcing/__init__.py` | Exports `ProcessManager` |

**Backwards compatibility:** Confirmed - 146 existing tests pass unchanged.

---

### Phase 0.3: Projection Purity Marker (0.5 day) -- IMPLEMENTED

**What:** Class-level declaration of side-effect intent.

**Files changed:**
| File | Change |
|------|--------|
| `event_sourcing/core/checkpoint.py` | Added `SIDE_EFFECTS_ALLOWED: ClassVar[bool] = False` to `CheckpointedProjection` |
| `event_sourcing/core/process_manager.py` | Overrides to `True` in `ProcessManager` |

---

### Phase 0.4: Built-in Fitness Module (1-2 days) -- IMPLEMENTED

**What:** Ship fitness functions as part of ESP.

**New directory:** `event_sourcing/fitness/` -- CREATED

**Files:**
| File | Purpose |
|------|---------|
| `event_sourcing/fitness/__init__.py` | Public API |
| `event_sourcing/fitness/projection_purity.py` | AST-based whitelist import analysis |
| `event_sourcing/fitness/replay_safety.py` | Verify zero process_pending() calls during catch-up |
| `event_sourcing/fitness/process_manager_check.py` | Verify ProcessManager subclasses have required methods |
| `event_sourcing/fitness/violations.py` | `Violation` frozen dataclass |

**Projection purity check (WHITELIST, not blacklist):**

The original design proposed a blacklist of banned modules. During review,
this was changed to a **whitelist approach** (CSP-style default-deny).
Rationale: blacklists are fragile - new side-effecting libraries slip
through. The whitelist approach catches anything not explicitly allowed.

```python
PROJECTION_ALLOWED_PREFIXES: frozenset[str] = frozenset({
    # Python stdlib (pure)
    "__future__", "abc", "collections", "dataclasses", "datetime",
    "decimal", "enum", "functools", "logging", "math", "operator",
    "re", "typing", "typing_extensions", "uuid",
    # ESP framework itself
    "event_sourcing",
})

def check_projection_purity(
    file_path: Path,
    allowed_prefixes: set[str] | None = None,  # project-specific additions
) -> list[Violation]:
    """Whitelist-based: flag any runtime import not in allowed_prefixes.
    TYPE_CHECKING imports are always allowed (zero runtime effect)."""
    ...
```

**Usage in any ESP-based project:**
```python
from event_sourcing.fitness import check_projection_purity

def test_projections_are_pure():
    project_allowed = {"syn_domain.contexts", "syn_shared", "syn_adapters.projection_stores"}
    for path in find_projection_files():
        violations = check_projection_purity(path, allowed_prefixes=project_allowed)
        assert not violations, f"{path}: {violations}"
```

---

### Phase 0.5: Documentation (1 day) -- IMPLEMENTED

**What:** Document consumer patterns in ESP's docs.

**New files created:**
| File | Content |
|------|---------|
| `docs/CONSUMER-PATTERNS.md` | Full guide: Projection vs ProcessManager, DispatchContext, testing, anti-patterns |
| `docs/adrs/ADR-025-process-manager-pattern.md` | Decision record: context, decision, alternatives considered (saga, replay flag, blacklist), consequences |

**Existing docs updated:**
- `PLATFORM-PHILOSOPHY.md` - Added "Process Manager" to "What This Platform IS" table
- `AGENTS.md` - Added "Event Consumer Patterns (Python SDK)" section with CheckpointedProjection, ProcessManager, DispatchContext

---

### Phase 0.6: VSA Validator Extensions (2-3 days) -- IMPLEMENTED

**What:** Add structural validation rules for event consumer patterns.

**New file:** `vsa/vsa-core/src/validation/consumer_pattern_rules.rs` -- CREATED

**New validation rules:**

| Rule | Code | What it checks | Severity |
|------|------|---------------|----------|
| `ProjectionPurityRule` | VSA032 | Projection files only import whitelisted modules | Error |
| `ProcessManagerStructureRule` | VSA033 | ProcessManager subclasses have process_pending() and get_idempotency_key() | Error |

**Config extension:** Added `projection_allowed_prefixes: Option<Vec<String>>`
to VsaConfig for project-specific whitelist additions in vsa.yaml.

**Implementation:** Uses existing PythonImportParser and ValidationRule trait.
ProjectionPurityRule mirrors the Python fitness module's whitelist approach.
ProcessManagerStructureRule uses string scanning (consistent with existing VSA parser).
3 new Rust unit tests + 248 existing tests pass.

---

### Phase 0.7: Test Kit Extensions (1 day) -- IMPLEMENTED

**What:** Add ProcessManager test utilities to ESP's test kit.

**New file:** `event_sourcing/testing/process_manager_scenario.py` -- CREATED

**Utilities implemented:**

- `ProcessManagerScenario` - Tests projection side in isolation.
  `given_events()` dispatches with `is_catching_up=True` (verifies zero
  process_pending calls). `when_live_event()` dispatches with
  `is_catching_up=False` (runs both sides). Tracks `process_pending_call_count`.

- `IdempotencyVerifier` - Calls `process_pending()` twice via `verify()`.
  Returns `IdempotencyResult` with `first_pass_count`, `second_pass_count`,
  and `is_idempotent` (True when second pass returns 0).

**Exported from `testing/__init__.py`:** `ProcessManagerScenario`,
`IdempotencyVerifier`, `IdempotencyResult`.

---

## Dependency Graph

```
Phase 0.1 (DispatchContext)
  |
  v
Phase 0.2 (ProcessManager base class) -- depends on 0.1
  |
  +---> Phase 0.3 (Purity marker) -- depends on 0.2
  |
  +---> Phase 0.4 (Fitness module) -- depends on 0.2
  |       |
  |       v
  |     Phase 0.6 (VSA extensions) -- depends on 0.4
  |
  +---> Phase 0.5 (Documentation) -- depends on 0.2
  |
  +---> Phase 0.7 (Test kit) -- depends on 0.2
```

Phases 0.3, 0.4, 0.5, 0.7 can run in parallel after 0.2 is complete.
Phase 0.6 depends on 0.4 (fitness module).

---

## Timeline

| Phase | Status | Duration |
|-------|--------|----------|
| 0.1: DispatchContext | **DONE** | Completed 2026-04-13 |
| 0.2: ProcessManager | **DONE** | Completed 2026-04-13 |
| 0.3: Purity marker | **DONE** | Completed 2026-04-13 |
| 0.4: Fitness module | **DONE** | Completed 2026-04-13 |
| 0.5: Documentation | **DONE** | Completed 2026-04-13 |
| 0.6: VSA extensions | **DONE** | Completed 2026-04-13 |
| 0.7: Test kit | **DONE** | Completed 2026-04-13 |

**All phases complete.** Ready for PR.

---

## Success Criteria

After all ESP enhancements are implemented:

1. **ProcessManager exists** - developers have a correct base class for
   event-driven side effects
2. **Projections are pure by default** - `SIDE_EFFECTS_ALLOWED = False`
   is the default, violations are detectable
3. **Replay is safe by construction** - the coordinator never calls
   `process_pending()` during catch-up
4. **Fitness is automated** - `check_projection_purity()` runs in CI for
   any ESP-based project
5. **Patterns are documented** - contributors know when to use Projection
   vs ProcessManager without reading external books
6. **VSA validates consumers** - structural analysis catches misclassified
   event handlers
7. **Testing is ergonomic** - ProcessManager tests are as easy to write
   as aggregate scenario tests

---

## How This Unblocks Syn137

With ESP enhancements complete, the Syn137 fix becomes straightforward:

1. `WorkflowDispatchProjection` becomes a `ProcessManager` subclass
2. `handle_event()` writes dispatch records only (pure projection side)
3. `process_pending()` dispatches workflows (live-only processor side)
4. The coordinator gates `process_pending()` - never called during replay
5. `get_idempotency_key()` returns `execution_id` - framework enforces dedup
6. ESP fitness functions catch any future projection with side effects in CI
7. VSA validates that all event consumers are correctly classified

The replay storm bug becomes impossible to write. Not "caught in review"
or "caught in CI" - structurally impossible at the framework level.

---

## Files Summary

### New files (ESP repo)

| File | Purpose |
|------|---------|
| `event_sourcing/core/process_manager.py` | ProcessManager base class |
| `event_sourcing/fitness/__init__.py` | Fitness module public API |
| `event_sourcing/fitness/projection_purity.py` | Projection purity check |
| `event_sourcing/fitness/replay_safety.py` | Replay safety check |
| `event_sourcing/fitness/process_manager_check.py` | ProcessManager validation |
| `event_sourcing/fitness/violations.py` | Violation types |
| `event_sourcing/testing/process_manager_scenario.py` | Test utilities |
| `docs/CONSUMER-PATTERNS.md` | Consumer pattern guide |
| `docs/adrs/ADR-025-process-manager-pattern.md` | ADR for ProcessManager |

### Modified files (ESP repo)

| File | Change |
|------|--------|
| `event_sourcing/core/checkpoint.py` | Add `DispatchContext`, `SIDE_EFFECTS_ALLOWED`, update `handle_event()` |
| `event_sourcing/subscriptions/coordinator.py` | Track catch-up state, pass `DispatchContext`, gate `process_pending()` |
| `event_sourcing/core/__init__.py` | Export new types |
| `event_sourcing/__init__.py` | Export new types |
| `docs/PLATFORM-PHILOSOPHY.md` | Reference consumer patterns |
| `AGENTS.md` | Add ProcessManager to key concepts |

### New VSA rules (ESP repo)

| File | Rule |
|------|------|
| `vsa/vsa-core/src/rules/projection_purity.rs` | Projection import analysis (delegates to fitness module) |
| `vsa/vsa-core/src/rules/process_manager_structure.rs` | ProcessManager structural validation |
