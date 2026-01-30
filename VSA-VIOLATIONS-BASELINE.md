# VSA Validation Baseline Report
**Date**: 2026-01-22
**VSA Version**: 0.6.1-beta
**AEF Branch**: feat/vsa-architecture-visualization

---

## Executive Summary

Ran enhanced VSA validation (with all ADR-019 rules) against current AEF domain structure to establish refactoring baseline.

### Overall Results
- **Total Errors**: 67
- **Total Warnings**: 35
- **Contexts Analyzed**: 9 (agents, artifacts, costs, github, metrics, observability, sessions, workflows, workspaces)
- **Files Analyzed**: 250 Python files across all contexts

### Validation Status
✅ **All validation rules operational** (VSA015-VSA031)
✅ **Zero false positives** (VSA015 bug fixed)
❌ **67 legitimate structural violations** - Expected for pre-ADR-019 codebase
⚠️ **35 warnings** - Mostly missing tests and naming suggestions (non-blocking)

---

## Violation Breakdown by Type

### 🔴 Critical Structural Violations (49 errors)

#### **VSA020: Commands Not in domain/commands/** - 12 violations
Commands are colocated with slices instead of centralized in `domain/commands/`.

**Rationale for Centralization** (per ADR-019):
- Commands are pure domain contracts (input DTOs)
- Centralizing commands improves discoverability
- Makes it easy to see all ways to interact with aggregates
- Separates "what can be done" (commands) from "how it's done" (handlers)

**Violations by Context:**
| Context | Commands | Files |
|---------|----------|-------|
| workspaces | 4 | CreateWorkspaceCommand, InjectTokensCommand, ExecuteCommandCommand, TerminateWorkspaceCommand |
| sessions | 3 | StartSessionCommand, CompleteSessionCommand, RecordOperationCommand |
| workflows | 2 | CreateWorkflowCommand, ExecuteWorkflowCommand |
| artifacts | 2 | CreateArtifactCommand, UploadArtifactCommand |
| github | 1 | RefreshTokenCommand |

#### **VSA021: Events Not at Context Root (events/)** - 31 violations
Events are colocated with slices instead of centralized at context root `events/`.

**Rationale for Centralization** (per ADR-019 + eventsourcing-book reference):
- Events are immutable contracts between write and read sides
- Events are the "public API" of the bounded context
- Other contexts may subscribe to these events (integration events)
- Events should be highly visible, not hidden in slice folders

**Violations by Context:**
| Context | Events | Examples |
|---------|--------|----------|
| workspaces | 10 | WorkspaceCreated, WorkspaceDestroyed, CommandExecuted, TokensInjected, etc. |
| workflows | 9 | WorkflowCreated, ExecutionStarted, PhaseStarted, PhaseCompleted, etc. |
| github | 4 | AppInstalled, TokenRefreshed, InstallationRevoked, InstallationSuspended |
| sessions | 3 | SessionStarted, SessionCompleted, OperationRecorded |
| artifacts | 2 | ArtifactCreated, ArtifactUploaded |
| costs | 2 | CostRecorded, SessionCostFinalized |

#### **VSA022: Aggregates Not in domain/ Root** - 6 violations
Aggregates are in `_shared/` folder (legacy pattern) or subfolders.

**Rationale for domain/ Root** (per ADR-019):
- Aggregates are the heart of the domain - should be highly visible
- `_shared/` pattern is deprecated (unclear naming)
- Aggregates at `domain/` root makes them immediately discoverable

**Violations:**
- `artifacts/_shared/ArtifactAggregate.py` → should be `domain/ArtifactAggregate.py`
- `workflows/_shared/WorkflowAggregate.py` → should be `domain/WorkflowAggregate.py`
- `workflows/_shared/WorkflowExecutionAggregate.py` → should be `domain/WorkflowExecutionAggregate.py`
- `workspaces/_shared/WorkspaceAggregate.py` → should be `domain/WorkspaceAggregate.py`
- `sessions/_shared/AgentSessionAggregate.py` → should be `domain/AgentSessionAggregate.py`
- `github/domain/aggregates/InstallationAggregate.py` → should be `domain/InstallationAggregate.py`

---

### 🟠 Dependency Violations (18 errors)

#### **VSA027: Domain Purity Violations** - 4 violations
Domain files importing from forbidden layers (events/, ports/, slices/).

**Rationale** (per ADR-019 Hexagonal Architecture):
- Domain layer is the **pure business logic core**
- Must have ZERO external dependencies
- Can only import from within domain/ itself
- This ensures domain is portable, testable, framework-agnostic

**Violations:**
1. `artifacts/domain/ports/__init__.py` → imports from `domain.ports.artifact_storage` (line 9)
   - **Issue**: `ports/` is infrastructure boundary, not domain
   - **Fix**: Move port interfaces to `ports/` at context root

2. `artifacts/domain/services/artifact_query_service.py` → imports from `slices.list_artifacts.projection` (line 17)
   - **Issue**: Domain service depending on slice projection (read model)
   - **Fix**: Move projection to `domain/` or use port interface

3. `observability/domain/events/__init__.py` → imports from `domain.events.agent_observation` (line 6)
   - **Issue**: Events currently in `domain/events/` but should be at context root `events/`
   - **Fix**: Move all events to `events/` at context root

4. `github/domain/aggregates/InstallationAggregate.py` → imports 3 events from slices (lines 11, 14, 17)
   - **Issue**: Aggregate importing events from slice folders
   - **Fix**: Move events to `events/` at context root

#### **VSA031: Cross-Slice Import Violations** - 14 violations
Slices importing from other slices (horizontal coupling).

**Rationale** (per ADR-019 VSA Principles):
- Slices must be **vertically isolated**
- No horizontal dependencies between slices
- Share code via domain/, not via other slices
- Enforces bounded context autonomy

**Violations:**
| Source Slice | Imports From | Count | Context |
|--------------|--------------|-------|---------|
| execute_workflow | create_workflow, start_session, complete_session, record_operation, create_artifact | 8 | workflows |
| get_installation | install_app, refresh_token | 4 | github |

**Key Insight**: `WorkflowExecutionEngine.py` is a **saga/orchestrator** that coordinates across multiple slices. Per ADR-019, sagas should use **domain events** and **command bus**, not direct slice imports.

---

## Violation Matrix by Context

| Context | Commands | Events | Aggregates | Domain Purity | Cross-Slice | **Total** | Files |
|---------|----------|--------|------------|---------------|-------------|-----------|-------|
| **workflows** | 2 | 9 | 2 | 0 | 8 | **21** | 67 |
| **workspaces** | 4 | 10 | 1 | 0 | 0 | **15** | 36 |
| **github** | 1 | 4 | 1 | 3 | 4 | **13** | 29 |
| **sessions** | 3 | 3 | 1 | 0 | 0 | **7** | 30 |
| **artifacts** | 2 | 2 | 1 | 2 | 0 | **7** | 28 |
| **costs** | 0 | 2 | 0 | 0 | 0 | **2** | 29 |
| **observability** | 0 | 0 | 0 | 1 | 0 | **1** | 19 |
| **metrics** | 0 | 0 | 0 | 0 | 0 | **0** | 11 |
| **agents** | 0 | 0 | 0 | 0 | 0 | **0** | 1 |
| **TOTAL** | **12** | **31** | **6** | **4** | **14** | **67** | **250** |

---

## Warnings Summary (35 total)

### Missing Tests (16 warnings, some duplicated)
Features without test files in slice directory.

**Affected**: create_artifact, upload_artifact, execute_workflow, create_workflow, complete_session, start_session, record_operation, refresh_token

**Note**: Tests may exist elsewhere in the codebase, just not colocated with slices.

### Generic Filenames (10 warnings)
- `handler.py` in 10 slices → should be `<ActionName>Handler.py`
- Improves discoverability and IDE search

**Contexts**: metrics, artifacts (×2), costs (×2), workflows (×2), observability (×2), sessions, github

### Integration Events Directory (9 warnings)
- 6 contexts have `_shared/` but no `integration-events/` subdirectory
- 3 contexts missing `_shared/` entirely (metrics, agents, observability)

---

## Refactoring Effort Analysis

### Context Complexity Ranking

| Rank | Context | Total Errors | Files | Slices | Est. Effort | Notes |
|------|---------|--------------|-------|--------|-------------|-------|
| 1 | **metrics** | 0 | 11 | 1 | ⭐ 15min | Already compliant! May only need ports |
| 2 | **agents** | 0 | 1 | 0 | ⭐ 5min | No violations |
| 3 | **observability** | 1 | 19 | 2 | ⭐ 30min | 1 domain purity fix |
| 4 | **costs** | 2 | 29 | 3 | ⭐⭐ 45min | 2 events to move |
| 5 | **artifacts** | 7 | 28 | 3 | ⭐⭐⭐ 2h | 2 cmds, 2 events, 1 agg, 2 domain fixes |
| 6 | **sessions** | 7 | 30 | 4 | ⭐⭐⭐ 2h | 3 cmds, 3 events, 1 agg |
| 7 | **github** | 13 | 29 | 3 | ⭐⭐⭐⭐ 3h | 1 cmd, 4 events, 1 agg, 3 domain, 4 cross-slice |
| 8 | **workspaces** | 15 | 36 | 6 | ⭐⭐⭐⭐ 4h | 4 cmds, 10 events, 1 agg |
| 9 | **workflows** | 21 | 67 | 6 | ⭐⭐⭐⭐⭐ 6h | 2 cmds, 9 events, 2 aggs, 8 cross-slice (saga) |

**Total Estimated Effort**: ~18-20 hours across all 9 contexts

---

## Recommended Refactoring Order

### Phase 1: Warmup & Pattern Validation (Milestones 7-8)
1. **metrics** - Already compliant, test the process
2. **agents** - Trivial, may be ports-only context

### Phase 2: Simple Contexts (Milestones 9-10)
3. **observability** - 1 simple fix
4. **costs** - 2 events to move

### Phase 3: Moderate Complexity (Milestones 11-13)
5. **artifacts** - Full refactoring pattern
6. **sessions** - Similar to artifacts
7. **github** - Introduces aggregate move + cross-slice fixes

### Phase 4: Complex (Milestones 14-15)
8. **workspaces** - Most events (10)
9. **workflows** - Most complex, refactor saga pattern for cross-slice imports

---

## Key Technical Challenges

### Challenge 1: Saga/Orchestrator Pattern (workflows)
**Issue**: `WorkflowExecutionEngine.py` imports directly from 8 other slices
**Current Pattern**:
```python
from aef_domain.contexts.workflows.slices.execute_workflow import ExecuteWorkflowCommand
from aef_domain.contexts.sessions.slices.start_session import StartSessionCommand
from aef_domain.contexts.sessions.slices.complete_session import CompleteSessionCommand
```

**ADR-019 Pattern**:
```python
# Via domain commands (centralized)
from aef_domain.contexts.workflows.domain.commands import ExecuteWorkflowCommand
from aef_domain.contexts.sessions.domain.commands import StartSessionCommand

# Via events (pub/sub)
from aef_domain.contexts.sessions.events import SessionStartedEvent
from aef_domain.contexts.sessions.events import SessionCompletedEvent
```

**Resolution**: Refactor saga to use domain commands + event subscriptions instead of direct slice imports.

### Challenge 2: Domain Importing from Slices (4 violations)
**Root Cause**: Events and port interfaces currently in wrong locations
**Fix**: Move events to `events/`, move port interfaces to `ports/` (both at context root)

### Challenge 3: Aggregate Relocation from _shared/
**Scope**: 6 aggregates need to move
**Complexity**: Each aggregate move requires updating imports across entire context
**Mitigation**: Use automated refactoring tools (IDE or script)

---

## Validation Rules Performance

| Rule | Violations | Status | Notes |
|------|-----------|---------|-------|
| VSA015 | 0 | ✅ PASS | Slices correctly in `slices/` |
| VSA020 | 12 | ❌ FAIL | Commands colocated with slices |
| VSA021 | 31 | ❌ FAIL | Events colocated with slices |
| VSA022 | 6 | ❌ FAIL | Aggregates in `_shared/` or subfolders |
| VSA023 | 0 | ✅ PASS | Ports correctly located |
| VSA024 | 0 | ✅ PASS | No buses violations |
| VSA025 | 0 | ✅ PASS | All ports have Port suffix |
| VSA026 | 0 | ✅ PASS | No value objects files detected |
| VSA027 | 4 | ❌ FAIL | Domain impurity (imports from slices/events) |
| VSA028 | 0 | ✅ PASS | Events isolation OK |
| VSA029 | 0 | ✅ PASS | Ports isolation OK |
| VSA030 | 0 | ✅ PASS | Application isolation OK |
| VSA031 | 14 | ❌ FAIL | Cross-slice coupling (mainly workflows saga) |

---

## Per-Context Refactoring Checklists

### Context: metrics (0 errors) ✅
**Status**: Already ADR-019 compliant!
**Action**: Validate, generate docs, document as reference example

**Checklist**:
- [✅] Slices in `slices/` directory
- [✅] No commands/events (query-only context)
- [✅] No aggregates
- [ ] Generate architecture docs with VSA visualizer
- [ ] Use as reference for other contexts

---

### Context: agents (0 errors) ✅
**Status**: Minimal context, compliant
**Files**: 1 Python file
**Action**: May only contain port interfaces, validate and document

**Checklist**:
- [✅] No violations detected
- [ ] Verify purpose (likely ports/interfaces only)
- [ ] Generate architecture docs

---

### Context: observability (1 error)
**Violations**: 1 domain purity (VSA027)
**Files**: 19 Python files, 2 slices

**Issues**:
- `domain/events/__init__.py` imports from `domain.events.agent_observation` (line 6)
  - **Root Cause**: Events currently in `domain/events/` but should be at `events/` (context root)

**Checklist**:
- [ ] Move `domain/events/` → `events/` (context root)
- [ ] Update import in `domain/events/__init__.py`
- [ ] Update all imports referencing moved events
- [ ] Run tests
- [ ] Validate with VSA
- [ ] Commit

---

### Context: costs (2 errors)
**Violations**: 2 events (VSA021)
**Files**: 29 Python files, 3 slices

**Events to Move**:
- `slices/record_cost/CostRecordedEvent.py` → `events/CostRecordedEvent.py`
- `slices/record_cost/SessionCostFinalizedEvent.py` → `events/SessionCostFinalizedEvent.py`

**Checklist**:
- [ ] Create `events/` directory at context root
- [ ] Move 2 event files from slices to `events/`
- [ ] Update imports in `slices/record_cost/`
- [ ] Update imports in any consumers
- [ ] Run tests
- [ ] Validate with VSA
- [ ] Commit

---

### Context: artifacts (7 errors)
**Violations**: 2 commands, 2 events, 1 aggregate, 2 domain purity
**Files**: 28 Python files, 3 slices

**Refactoring Steps**:
1. **Move aggregate**: `_shared/ArtifactAggregate.py` → `domain/ArtifactAggregate.py`
2. **Centralize commands**:
   - `slices/create_artifact/CreateArtifactCommand.py` → `domain/commands/CreateArtifactCommand.py`
   - `slices/upload_artifact/UploadArtifactCommand.py` → `domain/commands/UploadArtifactCommand.py`
3. **Centralize events**:
   - `slices/create_artifact/ArtifactCreatedEvent.py` → `events/ArtifactCreatedEvent.py`
   - `slices/upload_artifact/ArtifactUploadedEvent.py` → `events/ArtifactUploadedEvent.py`
4. **Fix domain purity**:
   - Move `domain/ports/` interfaces → `ports/` (context root)
   - Refactor `domain/services/artifact_query_service.py` to not import from slices

**Checklist**:
- [ ] Create `domain/`, `domain/commands/`, `events/`, `ports/` directories
- [ ] Move aggregate from `_shared/` to `domain/`
- [ ] Move 2 commands to `domain/commands/`
- [ ] Move 2 events to `events/`
- [ ] Move port interfaces from `domain/ports/` to `ports/`
- [ ] Update all imports across context
- [ ] Run tests after each step
- [ ] Validate with VSA
- [ ] Commit with before/after structure

---

### Context: sessions (7 errors)
**Violations**: 3 commands, 3 events, 1 aggregate
**Files**: 30 Python files, 4 slices

**Refactoring Steps**:
1. Move aggregate: `_shared/AgentSessionAggregate.py` → `domain/AgentSessionAggregate.py`
2. Centralize 3 commands (Start, Complete, RecordOperation)
3. Centralize 3 events (SessionStarted, SessionCompleted, OperationRecorded)
4. Update imports

**Checklist**:
- [ ] Create folder structure
- [ ] Move aggregate
- [ ] Move 3 commands
- [ ] Move 3 events
- [ ] Update imports
- [ ] Run tests
- [ ] Validate
- [ ] Commit

---

### Context: github (13 errors)
**Violations**: 1 command, 4 events, 1 aggregate (subfolder), 3 domain purity, 4 cross-slice
**Files**: 29 Python files, 3 slices

**Complex Issues**:
- Aggregate in subdirectory (`domain/aggregates/` → `domain/`)
- Aggregate importing events from slices (3 violations)
- Cross-slice imports in `get_installation` projection

**Refactoring Steps**:
1. Move aggregate: `domain/aggregates/InstallationAggregate.py` → `domain/InstallationAggregate.py`
2. Centralize 1 command (RefreshToken)
3. Centralize 4 events (AppInstalled, TokenRefreshed, InstallationRevoked, InstallationSuspended)
4. Fix aggregate event imports (now will import from `events/`)
5. Fix cross-slice imports in `get_installation` (should subscribe to events, not import from slices)

**Checklist**:
- [ ] Create `events/` and `domain/commands/` directories
- [ ] Move aggregate to `domain/` root
- [ ] Move command to `domain/commands/`
- [ ] Move 4 events to `events/`
- [ ] Update aggregate imports (events now at `events/`)
- [ ] Refactor `get_installation` projection to subscribe to events
- [ ] Update all imports
- [ ] Run tests
- [ ] Validate
- [ ] Commit

---

### Context: workspaces (15 errors)
**Violations**: 4 commands, 10 events, 1 aggregate
**Files**: 36 Python files, 6 slices

**Highest event count** - most domain activity in this context.

**Refactoring Steps**:
1. Move aggregate: `_shared/WorkspaceAggregate.py` → `domain/WorkspaceAggregate.py`
2. Centralize 4 commands (Create, Inject, Execute, Terminate)
3. Centralize 10 events (WorkspaceCreated, TokensInjected, CommandExecuted, etc.)

**Checklist**:
- [ ] Create folder structure
- [ ] Move aggregate
- [ ] Move 4 commands to `domain/commands/`
- [ ] Move 10 events to `events/`
- [ ] Update imports (systematic find/replace)
- [ ] Run tests
- [ ] Validate
- [ ] Commit

---

### Context: workflows (21 errors) 🔥
**Violations**: 2 commands, 9 events, 2 aggregates, 8 cross-slice
**Files**: 67 Python files (largest context), 6 slices

**Most complex refactoring** - contains saga/orchestrator with heavy cross-context coupling.

**Critical Issue**: `WorkflowExecutionEngine.py` is a saga that orchestrates across:
- Sessions context (start, complete, record_operation)
- Artifacts context (create_artifact)
- Internal workflows slices (execute_workflow, create_workflow)

**Refactoring Strategy**:
1. Move aggregates first (2)
2. Centralize commands (2)
3. Centralize events (9)
4. **Refactor saga** (most complex):
   - Replace direct slice imports with domain commands
   - Replace slice event imports with context `events/`
   - May need command bus or event bus pattern

**Checklist**:
- [ ] Create folder structure
- [ ] Move 2 aggregates from `_shared/` to `domain/`
- [ ] Move 2 commands to `domain/commands/`
- [ ] Move 9 events to `events/`
- [ ] **Refactor `WorkflowExecutionEngine` saga**:
   - [ ] Change slice imports to domain command imports
   - [ ] Change slice event imports to context event imports
   - [ ] Consider introducing command bus
   - [ ] Review saga pattern with event subscriptions
- [ ] Update all other imports
- [ ] Run full test suite
- [ ] Validate
- [ ] Commit with detailed saga refactoring notes

---

## Findings & Recommendations

### Finding 1: VSA015 Config Issue - RESOLVED ✅
**Was**: Slices reported "not in slices/" despite being correctly located
**Root Cause**: Config `root` pointed to wrong level (`src/aef_domain` instead of `src/aef_domain/contexts`)
**Fix**: Updated `vsa.yaml` root to `src/aef_domain/contexts` for proper context auto-discovery
**Result**: Zero VSA015 violations - all slices correctly detected

### Finding 2: Colocated Pattern is Consistent
**Observation**: ALL contexts use same pattern (commands/events colocated with slices)
**Implication**: Refactoring is **mechanical** and **repeatable** across contexts
**Benefit**: Lessons learned from early contexts apply to later ones

### Finding 3: Workflows is a Saga/Orchestrator
**Pattern**: Workflows coordinates across multiple bounded contexts
**Challenge**: Heavy coupling via direct slice imports (8 cross-slice violations)
**Solution**: Classic saga pattern with event choreography or command orchestration
**Priority**: Refactor workflows LAST after all other contexts stabilized

### Finding 4: Domain Purity Violations are Fixable
**All 4 violations** are caused by events/ports being in wrong locations:
- Events currently in `domain/events/` → move to `events/`
- Ports currently in `domain/ports/` → move to `ports/`
- Domain services importing from slices → fix after events moved

**Resolution**: Automatically fixed when we move events/ports to correct locations

### Finding 5: Most Contexts Have No Dependency Violations
**Good News**: 5/9 contexts have **zero** dependency violations (VSA027-VSA031)
**Implication**: Domain layer is already relatively pure
**Only Issues**: workflows (saga), github (events in wrong location)

---

## Success Metrics

After completing all 9 context refactorings (Milestones 7-15), we expect:

| Metric | Before | Target | Notes |
|--------|--------|--------|-------|
| **Errors** | 67 | 0 | Full ADR-019 compliance |
| **Commands Centralized** | 0% | 100% | All in `domain/commands/` |
| **Events Centralized** | 0% | 100% | All at `events/` (context root) |
| **Aggregates Visible** | 0% | 100% | All at `domain/` root |
| **Domain Purity** | 93% | 100% | 4 violations fixed |
| **Slice Isolation** | 79% | 100% | 14 cross-slice imports removed |
| **Test Coverage** | ~85% | 100% | Add missing slice tests |

---

## Next Actions

### Immediate (Milestone 6 - Complete)
- [✅] Run enhanced VSA validation on AEF
- [✅] Capture baseline report (67 errors, 35 warnings)
- [✅] Fix VSA015 validator bug (relative path issue)
- [✅] Analyze violations by type and context
- [✅] Create context complexity matrix
- [✅] Determine refactoring order
- [✅] Create per-context refactoring checklists
- [ ] Commit baseline report and config

### Next Milestone (Milestone 7 - metrics)
- [ ] Run `vsa validate --config ../../vsa.yaml` (should show 0 errors)
- [ ] Generate manifest and visualization
- [ ] Document as reference example
- [ ] Quick commit as already compliant

---

## Appendix

### VSA Configuration
See `packages/aef-domain/vsa.yaml` for validated configuration.

**Key Settings**:
- Root: `src/aef_domain/contexts` (auto-discovers 9 contexts)
- Language: python
- Architecture: hexagonal-event-sourced-vsa

### Full Validation Output
See `VSA-VALIDATION-BASELINE-CORRECTED.txt` for complete output with line numbers.

### Validation Command
```bash
cd packages/aef-domain
../../lib/event-sourcing-platform/vsa/target/release/vsa validate
```

---

**Status**: ✅ Baseline established, validator bugs fixed, ready to start refactoring with Milestone 7 (metrics)!
