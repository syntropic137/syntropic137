# Research: Bounded Context Analysis & Given-When-Then Test Harness
**Date:** 2026-02-02
**Status:** Research Complete → Innovation Complete → Plan Created

## Critical Architectural Principle (from Innovation Phase)

> **Multiple aggregates CAN and SHOULD live in ONE bounded context when they share the same domain/ubiquitous language.**

A bounded context is a **SEMANTIC boundary**, not a 1:1 mapping with aggregates.

**Example:**
- `orchestration` bounded context contains:
  - `WorkspaceAggregate` 
  - `WorkflowAggregate`
  - `WorkflowExecutionAggregate`

These share the same domain language around "executing workflows in isolated workspaces."

---

---

## Executive Summary

This research identifies issues with the current domain model organization and proposes simplification. Key findings:

1. **Given-When-Then Test Harness** - Complete in `lib/event-sourcing-platform`, not yet adopted in AEF
2. **9 "Bounded Contexts"** - Should be reduced to 4 true bounded contexts
3. **Projection-Only Modules** - `metrics`, `costs`, `observability` are misclassified
4. **Empty Context** - `agents/` has 0 features and should be removed
5. **VSA Tool Issue** - Auto-discovers directories at depth 1, treating projections as bounded contexts

---

## 1. Given-When-Then Test Harness

### Location
```
lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/testing/scenario/
├── __init__.py              # Public exports (scenario function)
├── aggregate_scenario.py    # Entry point: AggregateScenario class
├── test_executor.py         # "When" phase: TestExecutor class
├── result_validator.py      # "Then" phase: ResultValidator class
└── errors.py                # ScenarioAssertionError, ScenarioExecutionError
```

### Fluent API

```python
from event_sourcing.testing import scenario

# Happy path - verify events emitted
scenario(CartAggregate).given([
    CartCreatedEvent(cart_id="cart-1"),
]).when(AddItemCommand("cart-1", "item-1", 29.99)).expect_events([
    ItemAddedEvent(cart_id="cart-1", item_id="item-1", price=29.99),
])

# Error path - verify exception
scenario(CartAggregate).given([
    CartCreatedEvent(cart_id="cart-1"),
]).when(SubmitCartCommand("cart-1")).expect_exception(
    BusinessRuleViolationError
).expect_exception_message("Cannot submit empty cart")

# State verification
scenario(CartAggregate).given([
    CartCreatedEvent(cart_id="cart-1"),
]).when(AddItemCommand("cart-1", "item-1", 29.99)).expect_state(
    lambda agg: assert agg.get_item_count() == 1
)

# Setup via commands
scenario(CartAggregate).given_commands([
    CreateCartCommand("cart-1"),
    AddItemCommand("cart-1", "item-1", 15.00),
]).when(SubmitCartCommand("cart-1")).expect_events([
    CartSubmittedEvent(cart_id="cart-1", total=15.00),
])
```

### Status
- ✅ Implementation complete and tested
- ❌ NOT yet adopted in AEF codebase
- Current AEF tests use traditional pytest fixtures

### Documentation
- ADR: `lib/event-sourcing-platform/docs/adrs/ADR-015-es-test-kit-architecture.md`
- User Guide: `lib/event-sourcing-platform/docs-site/docs/event-sourcing/testing/scenario-testing.md`

---

## 2. Current "Bounded Contexts" Analysis

### Overview (from Architecture Diagram)

```
Domain Contexts (Bounded Contexts)
┌─────────────┬─────────────┬─────────────┐
│   metrics   │  artifacts  │    costs    │
│ (1 feature) │ (4 features)│ (4 features)│
│ get_metrics │ list/create │ exec/session│
│             │ upload/svc  │ record/svc  │
├─────────────┼─────────────┼─────────────┤
│  workflows  │   agents    │observability│
│ (8 features)│ (0 features)│ (2 features)│
│ execute/etc │   EMPTY!    │ token/tool  │
├─────────────┼─────────────┼─────────────┤
│ workspaces  │  sessions   │   github    │
│ (6 features)│ (4 features)│ (5 features)│
│ create/term │ start/comp  │ install/etc │
└─────────────┴─────────────┴─────────────┘

CORE Totals:
- Commands: 12 total
- Events: 31 total
- Projections: 13 total
```

### Detailed Breakdown

| Context | Aggregate | Features | Assessment |
|---------|-----------|----------|------------|
| **workflows** | WorkflowAggregate, WorkflowExecutionAggregate | 8 | ✅ True bounded context |
| **workspaces** | WorkspaceAggregate | 6 | ✅ True bounded context |
| **sessions** | AgentSessionAggregate | 4 | ✅ True bounded context |
| **github** | InstallationAggregate | 5 | ⚠️ True context, but aggregate not using ES framework |
| **artifacts** | ArtifactAggregate | 4 | ⚠️ Minimal (creation only) |
| **metrics** | NONE | 1 | ❌ Just a projection - NOT a bounded context |
| **costs** | NONE | 4 | ❌ Just projections - NOT a bounded context |
| **observability** | NONE | 2 | ❌ Just projections - NOT a bounded context |
| **agents** | NONE | 0 | ❌ EMPTY - should be removed |

### Aggregates Detail

#### 1. WorkspaceAggregate (workspaces context)
- **Status:** Fully implemented with ES framework
- **Commands:** CreateWorkspaceCommand, InjectTokensCommand, ExecuteCommandCommand, TerminateWorkspaceCommand
- **Events:** 12 events (WorkspaceCreated, IsolationStarted, TokensInjected, CommandExecuted, etc.)
- **Lines:** 572

#### 2. WorkflowAggregate (workflows context)
- **Status:** Minimal - creation only
- **Commands:** CreateWorkflowCommand
- **Events:** WorkflowCreatedEvent
- **Lines:** 195

#### 3. WorkflowExecutionAggregate (workflows context)
- **Status:** Fully implemented
- **Commands:** Start, Complete, Fail, StartPhase, CompletePhase, Pause, Resume, Cancel
- **Events:** 9 events
- **Lines:** 540

#### 4. AgentSessionAggregate (sessions context)
- **Status:** Fully implemented with v2 observability
- **Commands:** StartSessionCommand, RecordOperationCommand, CompleteSessionCommand
- **Events:** SessionStarted, OperationRecorded, SessionCompleted
- **Lines:** 320

#### 5. ArtifactAggregate (artifacts context)
- **Status:** Minimal - creation only
- **Commands:** CreateArtifactCommand (upload handled outside)
- **Events:** ArtifactCreated, ArtifactUploaded
- **Lines:** 205

#### 6. InstallationAggregate (github context)
- **Status:** NOT using ES framework (plain dataclass)
- **Methods:** install(), revoke(), record_token_refresh()
- **Events:** AppInstalled, InstallationRevoked, TokenRefreshed
- **Lines:** 175
- **Issue:** Needs migration to AggregateRoot with @command_handler

---

## 3. Problems Identified

### Problem 1: VSA Misclassifies Directories as Bounded Contexts

**Root Cause:** VSA auto-discovers directories at depth 1 from root
```rust
// From scanner.rs
for entry in WalkDir::new(&self.root)
    .min_depth(1)
    .max_depth(1)  // Only depth 1 - direct children
```

**Effect:** Any subdirectory becomes a "bounded context", including projection-only modules

### Problem 2: Projection-Only "Contexts"

These have NO aggregates - they're just read model projections:
- `metrics/` - DashboardMetricsProjection
- `costs/` - ExecutionCostProjection, SessionCostProjection
- `observability/` - TokenMetricsProjection, ToolTimelineProjection

In DDD, these should be organized as:
```
projections/
├── dashboard/      # Cross-context dashboard metrics
├── costs/          # Cost tracking read models
└── observability/  # Token/tool metrics
```

### Problem 3: Empty Context

`agents/` context:
- 0 features
- Only contains `__init__.py` with docstring
- Agent functionality is in `sessions/` via AgentSessionAggregate
- Should be **REMOVED**

### Problem 4: Inconsistent Aggregate Implementation

`InstallationAggregate` doesn't use the ES framework:
- No `@aggregate` decorator
- No `@command_handler` decorators
- Uses plain dataclass methods
- Manual event management

---

## 4. Recommended Simplification

### True Bounded Contexts (4)

#### 1. Orchestration (merge workspaces + workflows)
```
contexts/orchestration/
├── workspaces/
│   └── domain/WorkspaceAggregate.py
├── workflows/
│   ├── domain/WorkflowAggregate.py
│   └── domain/WorkflowExecutionAggregate.py
└── slices/
    ├── create_workspace/
    ├── execute_workflow/
    └── ...
```

#### 2. Sessions
```
contexts/sessions/
├── domain/AgentSessionAggregate.py
└── slices/
    ├── start_session/
    ├── record_operation/
    └── complete_session/
```

#### 3. GitHub (external integration)
```
contexts/github/
├── domain/InstallationAggregate.py  # MIGRATE to ES framework
└── slices/
    ├── install_app/
    └── refresh_token/
```

#### 4. Artifacts
```
contexts/artifacts/
├── domain/ArtifactAggregate.py
└── slices/
    ├── create_artifact/
    └── upload_artifact/
```

### Projection Modules (NOT bounded contexts)
```
projections/
├── dashboard/          # DashboardMetricsProjection
├── costs/              # ExecutionCostProjection, SessionCostProjection
└── observability/      # TokenMetricsProjection, ToolTimelineProjection
```

### Remove
- `contexts/agents/` - empty, functionality in sessions

---

## 5. Missing Given-When-Then Tests

| Aggregate | Current Tests | Scenario Tests Status |
|-----------|--------------|----------------------|
| WorkspaceAggregate | ✅ Fixture-based (comprehensive) | ❌ Need migration |
| WorkflowAggregate | ⚠️ Minimal | ❌ Need scenarios |
| WorkflowExecutionAggregate | ⚠️ Minimal | ❌ Need scenarios |
| AgentSessionAggregate | ⚠️ Minimal | ❌ Need scenarios |
| ArtifactAggregate | ⚠️ Minimal | ❌ Need scenarios |
| InstallationAggregate | ⚠️ Non-standard | ❌ Need migration + scenarios |

### Test Coverage Needed

For each aggregate, we need scenarios covering:
1. **Happy paths** - Normal command → event flows
2. **Error paths** - Business rule violations
3. **State verification** - Aggregate state after operations
4. **Idempotency** - Commands that should be idempotent
5. **Invariants** - Business invariants that must hold

---

## 6. VSA Tool Investigation (COMPLETE)

### Root Cause Analysis

**Location:** `lib/event-sourcing-platform/vsa/vsa-core/src/scanner.rs`

The scanner treats **every directory at depth 1** as a bounded context:

```rust
pub fn scan_contexts(&self) -> Result<Vec<ContextInfo>> {
    let mut contexts = Vec::new();

    for entry in WalkDir::new(&self.root)
        .min_depth(1)
        .max_depth(1)  // ← Only depth 1 - direct children
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_dir())
    {
        let name = entry.file_name().to_string_lossy().to_string();

        // Skip _shared directory
        if name.starts_with('_') {  // ← Only exclusion rule
            continue;
        }

        contexts.push(ContextInfo { name, path: entry.path().to_path_buf() });
    }

    Ok(contexts)
}
```

**Key Issues:**
1. **No content validation** - Doesn't check if directory has aggregates
2. **No aggregate detection** - Bounded context detection is purely structural
3. **Projections counted** - `component_count()` includes projections

### How component_count() Works

```rust
// lib/event-sourcing-platform/vsa/vsa-core/src/domain/mod.rs
pub fn component_count(&self) -> usize {
    self.aggregates.len()
        + self.commands.len()
        + self.queries.len()
        + self.events.len()
        + self.projections.len()  // ← Projections included!
        + self.upcasters.len()
        + self.value_objects.len()
}
```

A projection-only module (e.g., `metrics/`) has `projections.len() > 0` but `aggregates.len() == 0`, so it still passes the `component_count() > 0` check.

### Missing Methods in DomainModel

The `DomainModel` struct is missing methods to distinguish:
- `has_write_side()` - Has aggregates/commands/events
- `is_projection_only()` - Has projections but no write-side

### Current Schema Limitations

From `vsa-schema.json`:
- No `exclude` configuration option
- No `context_type` field (bounded_context vs projection_module)
- No way to mark directories as projection-only

Only exclusion mechanism is `_` prefix convention (e.g., `_shared`).

### Proposed Fixes for VSA Tool

#### Fix 1: Add classification methods to DomainModel

```rust
impl DomainModel {
    /// Check if this domain model has write-side components
    pub fn has_write_side(&self) -> bool {
        !self.aggregates.is_empty() 
            || !self.commands.is_empty() 
            || !self.events.is_empty()
    }
    
    /// Check if this is projection-only (read-side only)
    pub fn is_projection_only(&self) -> bool {
        !self.has_write_side() && !self.projections.is_empty()
    }
}
```

#### Fix 2: Add context_type to ContextManifest

```rust
#[derive(Debug, Serialize, Deserialize)]
pub enum ContextType {
    BoundedContext,    // Has write-side (aggregates)
    ProjectionModule,  // Only has projections
    Empty,             // No domain components
}

pub struct ContextManifest {
    pub name: String,
    pub path: String,
    pub features: Vec<FeatureManifest>,
    pub context_type: ContextType,  // NEW
    pub infrastructure_folders: Vec<String>,
}
```

#### Fix 3: Add exclude config to vsa.yaml schema

```json
{
  "exclude": {
    "type": "array",
    "description": "Directories to exclude from bounded context detection",
    "items": {
      "type": "string"
    },
    "examples": [
      ["projections", "metrics", "costs"]
    ]
  }
}
```

#### Fix 4: Update visualizer to show context types differently

In `architecture-svg-generator.ts`:
- Different colors for projection modules (e.g., green)
- Different border styles (dashed for projections)
- Optional separate section for projections

### Files to Modify

1. `lib/event-sourcing-platform/vsa/vsa-core/src/domain/mod.rs`
   - Add `has_write_side()` and `is_projection_only()` methods

2. `lib/event-sourcing-platform/vsa/vsa-core/src/manifest.rs`
   - Add `ContextType` enum
   - Update `ContextManifest` struct
   - Classify contexts during generation

3. `lib/event-sourcing-platform/vsa/vsa-core/src/config.rs`
   - Add `exclude` field to `VsaConfig`

4. `lib/event-sourcing-platform/vsa/vsa-core/src/scanner.rs`
   - Filter excluded directories

5. `lib/event-sourcing-platform/vsa/vscode-extension/schemas/vsa-schema.json`
   - Add `exclude` and `context_type` to schema

6. `lib/event-sourcing-platform/vsa/vsa-visualizer/src/generators/architecture-svg-generator.ts`
   - Update rendering to distinguish context types

---

## 7. Immediate Workaround for AEF

While we fix the VSA tool, we can use the `_` prefix convention:

### Option A: Prefix projection directories with `_`

```
contexts/
├── workflows/        # ✅ True bounded context (has aggregates)
├── workspaces/       # ✅ True bounded context (has aggregates)
├── sessions/         # ✅ True bounded context (has aggregates)
├── github/           # ✅ True bounded context (has aggregates)
├── artifacts/        # ✅ True bounded context (has aggregates)
├── _metrics/         # 🚫 Excluded (projection-only)
├── _costs/           # 🚫 Excluded (projection-only)
├── _observability/   # 🚫 Excluded (projection-only)
└── _shared/          # 🚫 Excluded (shared infrastructure)
```

### Option B: Move projections to a dedicated folder

```
contexts/
├── workflows/
├── workspaces/
├── sessions/
├── github/
├── artifacts/
└── _projections/     # 🚫 Excluded
    ├── dashboard/
    ├── costs/
    └── observability/
```

**Recommendation:** Option A is less disruptive but Option B is cleaner long-term.

---

## 8. Action Plan

### Phase 1: Fix VSA Tool (Dogfooding)
- [ ] Add `has_write_side()` and `is_projection_only()` to `DomainModel`
- [ ] Add `ContextType` enum to `ContextManifest`
- [ ] Update manifest generation to classify contexts
- [ ] Add `exclude` config option to schema
- [ ] Update visualizer to render context types differently
- [ ] Write tests for new classification logic

### Phase 2: Reorganize AEF Domain
- [ ] Remove `agents/` directory (empty)
- [ ] Rename projection-only directories with `_` prefix OR
- [ ] Move projections to `_projections/` folder
- [ ] Update imports in dependent code
- [ ] Regenerate manifest

### Phase 3: Adopt Given-When-Then Tests
- [ ] Write scenario tests for WorkspaceAggregate
- [ ] Write scenario tests for WorkflowAggregate
- [ ] Write scenario tests for WorkflowExecutionAggregate
- [ ] Write scenario tests for AgentSessionAggregate
- [ ] Write scenario tests for ArtifactAggregate
- [ ] Migrate InstallationAggregate to ES framework + write tests

### Phase 4: Consider Context Consolidation (Future)
- [ ] Evaluate merging workspaces + workflows → orchestration
- [ ] Document bounded context boundaries
- [ ] Define integration events between contexts

---

## Appendix: File Locations

### Event Sourcing Platform - Test Harness
- Entry Point: `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/testing/scenario/__init__.py`
- Scenario Class: `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/testing/scenario/aggregate_scenario.py`
- Test Executor: `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/testing/scenario/test_executor.py`
- Result Validator: `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/testing/scenario/result_validator.py`
- Example Tests: `lib/event-sourcing-platform/event-sourcing/python/tests/unit/test_scenario.py`
- ADR: `lib/event-sourcing-platform/docs/adrs/ADR-015-es-test-kit-architecture.md`

### Event Sourcing Platform - VSA Tool
- Scanner: `lib/event-sourcing-platform/vsa/vsa-core/src/scanner.rs`
- Manifest Generation: `lib/event-sourcing-platform/vsa/vsa-core/src/manifest.rs`
- Domain Model: `lib/event-sourcing-platform/vsa/vsa-core/src/domain/mod.rs`
- Config: `lib/event-sourcing-platform/vsa/vsa-core/src/config.rs`
- JSON Schema: `lib/event-sourcing-platform/vsa/vscode-extension/schemas/vsa-schema.json`
- Visualizer: `lib/event-sourcing-platform/vsa/vsa-visualizer/src/generators/architecture-svg-generator.ts`
- Projection Scanner: `lib/event-sourcing-platform/vsa/vsa-core/src/scanners/projection_scanner.rs`
- Aggregate Scanner: `lib/event-sourcing-platform/vsa/vsa-core/src/scanners/aggregate_scanner.rs`

### AEF Domain
- Contexts Root: `packages/aef-domain/src/aef_domain/contexts/`
- VSA Config (Root): `vsa.yaml`
- VSA Config (Domain): `packages/aef-domain/vsa.yaml`
- Generated Manifest: `.topology/aef-manifest.json`

### AEF Aggregates
- WorkspaceAggregate: `packages/aef-domain/src/aef_domain/contexts/workspaces/domain/WorkspaceAggregate.py`
- WorkflowAggregate: `packages/aef-domain/src/aef_domain/contexts/workflows/domain/WorkflowAggregate.py`
- WorkflowExecutionAggregate: `packages/aef-domain/src/aef_domain/contexts/workflows/domain/WorkflowExecutionAggregate.py`
- AgentSessionAggregate: `packages/aef-domain/src/aef_domain/contexts/sessions/domain/AgentSessionAggregate.py`
- ArtifactAggregate: `packages/aef-domain/src/aef_domain/contexts/artifacts/domain/ArtifactAggregate.py`
- InstallationAggregate: `packages/aef-domain/src/aef_domain/contexts/github/domain/InstallationAggregate.py`

### Current Aggregate Tests
- WorkspaceAggregate: `packages/aef-domain/src/aef_domain/contexts/workspaces/_shared/test_workspace_aggregate.py`

---

## Appendix: VSA Scanner Detection Logic

### Bounded Context Detection

```
1. Scan root directory at depth 1
2. For each subdirectory:
   - If name starts with '_' → SKIP
   - Otherwise → Add to bounded_contexts list
3. No content validation performed
```

### Domain Model Detection (when --include-domain)

```
For each bounded context:
1. Check if context_path/domain/ exists
2. If yes, scan for:
   - Aggregates: *Aggregate.{ts,py,rs}
   - Commands: *Command.{ts,py,rs}
   - Events: *Event.{ts,py,rs}
   - Queries: *Query.{ts,py,rs}
   - Projections: *Projection.{ts,py,rs} or projection.{ts,py,rs}
3. Merge into combined DomainModel
4. Context included if component_count() > 0
```

### Current Problem Flow

```
metrics/
├── slices/get_metrics/projection.py  ← Detected as projection
└── domain/                           ← No aggregates

Result:
- bounded_contexts includes "metrics" (directory exists)
- DomainModel.projections includes "DashboardMetricsProjection"
- component_count() = 1 (projection)
- metrics appears as bounded context with 1 feature

Expected:
- metrics should be classified as "projection module", not "bounded context"
```
