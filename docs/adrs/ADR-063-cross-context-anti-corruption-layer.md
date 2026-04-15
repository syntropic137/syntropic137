# ADR-063: Cross-Context Anti-Corruption Layer

- **Status**: Accepted
- **Date**: 2026-04-15
- **Issue**: [#671](https://github.com/syntropic137/syntropic137/issues/671)
- **Related**: ADR-020 (Bounded Context Convention), ADR-032 (Domain Event Type Safety), ADR-062 (Fitness Functions)

## Context

Repository identity crosses bounded context boundaries as `dict[str, str]` with implicit field-name conventions. The same concept uses different field names and formats in different contexts:

| Context | Field | Format | Example |
|---------|-------|--------|---------|
| GitHub (triggers) | `repository` | slug | `owner/repo` |
| Orchestration (templates) | `repository_url` | full URL | `https://github.com/owner/repo` |
| Orchestration (inputs) | `inputs["repos"]` | CSV of URLs | `https://github.com/a/b,https://github.com/c/d` |
| Organization | `full_name` | slug | `owner/repo` |

A trigger-fired execution bug proved the fragility: the GitHub context puts the repository under `inputs["repository"]` (slug from webhook payload), while the orchestration context looks for `inputs["repos"]` (full URL CSV). The ad-hoc translation in `_resolve_repos()` caught this with fallback logic, but pyright couldn't verify the contract.

ADR-062 (#675) enforced cross-context *code* boundaries (no deep imports). This ADR addresses cross-context *data* boundaries (no implicit dict-key contracts).

## Decision

### 1. Value objects at boundaries

Cross-context data that carries domain identity MUST use typed value objects, not raw `dict[str, str]` with implicit key conventions. Value objects are frozen dataclasses in `contexts/_shared/` (the shared kernel).

First value object: `RepositoryRef` - normalizes repository identity between slug and URL forms.

```python
@dataclass(frozen=True)
class RepositoryRef:
    owner: str
    name: str

    @classmethod
    def from_slug(cls, slug: str) -> RepositoryRef: ...
    @classmethod
    def from_url(cls, url: str) -> RepositoryRef: ...

    @property
    def slug(self) -> str: ...       # "owner/repo"
    @property
    def https_url(self) -> str: ...  # "https://github.com/owner/repo"
```

### 2. Translation at the boundary, not deep in handlers

The producing context translates its internal representation to the shared value object at the protocol boundary. The consuming context receives typed data.

**Before** (implicit dict contract):
```
GitHub trigger fires
  -> workflow_inputs = {"repository": "owner/repo", ...}  (dict[str, object])
  -> dispatch projection passes inputs through unchanged
  -> ExecuteWorkflowHandler._resolve_repos() fishes "repository" from dict
  -> normalizes slug to URL ad-hoc
```

**After** (typed boundary):
```
GitHub trigger fires
  -> workflow_inputs = {"repository": "owner/repo", ...}  (dict[str, object])
  -> dispatch projection extracts RepositoryRef.from_slug(inputs["repository"])
  -> passes repos=[RepositoryRef(...)] to ExecutionService protocol
  -> ExecuteWorkflowCommand receives typed repos
  -> _resolve_repos() uses command.repos first (no dict fishing)
```

### 3. Fitness function enforcement

`ci/fitness/code_quality/test_typed_cross_context_boundaries.py` scans Protocol definitions for `dict[str, str]`, `dict[str, Any]`, or `dict[str, object]` parameters. New protocols MUST use typed value objects. Legacy violations are grandfathered in `fitness_exceptions.toml` with budgets ratcheting toward zero.

### 4. Domain events are exempt

Domain events are immutable facts. `TriggerFiredEvent.workflow_inputs` stays `dict[str, object]` - the translation happens when the event is *consumed* at the boundary, not when it's produced.

## Consequences

### Positive

- pyright catches field-name mismatches at compile time
- Repository identity has a single canonical type across contexts
- The `_resolve_repos()` fallback chain simplifies (typed repos first, legacy dict last)
- Fitness function prevents regression

### Negative

- Slight ceremony: constructing `RepositoryRef` at boundaries instead of passing raw strings
- Legacy `inputs` dict still flows through for non-identity fields (task, pr_number, branch, etc.)

### Neutral

- No ESP changes needed - frozen dataclasses are the established value object pattern
- No VSA rule changes - Python fitness function is sufficient and cheaper to iterate on
- Template-level `repository_url` / `repos` fields are orchestration-internal, not affected

## Implementation

- Value object: `packages/syn-domain/src/syn_domain/contexts/_shared/repository_ref.py`
- Boundary typed: `_ExecutionService` protocol, `BackgroundWorkflowDispatcher`, `ExecuteWorkflowCommand`
- Handler simplified: `ExecuteWorkflowHandler._resolve_repos()` prefers `command.repos`
- Fitness function: `ci/fitness/code_quality/test_typed_cross_context_boundaries.py`
