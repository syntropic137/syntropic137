# ADR-035: QA Workflow Standard

**Status:** Accepted  
**Date:** 2026-01-21  
**Version:** 1.0.0

## Context

During the VSA slice refactoring (PR #56), we discovered that our pre-commit QA workflow only ran static checks (lint/format) but not tests. This led to import errors in apps and adapters that weren't caught until CI, requiring multiple fix commits.

**The problem:**
- Inconsistent QA command naming (`check`, `qa`, `test`)
- No clear separation between static checks and tests
- No distinction between fast local checks and comprehensive CI validation
- Developers didn't know which command to run when

## Decision

We adopt a **three-tier QA workflow standard** with clear command naming and scope:

### Version 1.0.0 Command Definitions

```
just check      → Static analysis only (fast)
just qa         → check + unit tests (pre-commit)
just qa-full    → qa + all tests (pre-push, CI)
```

### Detailed Specifications

#### Tier 1: `just check` - Static Checks

**Purpose:** Fast feedback for syntax, style, and type errors  
**Runtime Target:** 5-15 seconds  
**When to run:** Before every commit, during development

**Includes:**
1. **Linting** - `ruff check .`
   - Code quality rules
   - Import sorting
   - Unused imports
2. **Format validation** - `ruff format --check .`
   - Code style consistency
   - No actual changes, just validation
3. **Type checking** - `pyright`
   - Static type analysis
   - Currently non-blocking (warnings only)

**Auto-fix variant:** `just check-fix`
- Runs `ruff check --fix .`
- Runs `ruff format .`
- Does NOT run type checking (not auto-fixable)

#### Tier 2: `just qa` - Quick QA

**Purpose:** Pre-commit validation with fast tests  
**Runtime Target:** 30-60 seconds  
**When to run:** Before committing significant changes

**Includes:**
- All `check` steps
- **Unit tests** - `pytest -m unit --tb=short`
  - Fast, isolated tests
  - No external dependencies
  - Mocked I/O

**Auto-fix variant:** `just qa-fix`
- Runs `check-fix` first
- Then runs unit tests

#### Tier 3: `just qa-full` - Complete QA

**Purpose:** Comprehensive validation before pushing  
**Runtime Target:** 3-10 minutes  
**When to run:** Before pushing to remote, in CI

**Includes:**
- All `check` steps
- **All tests** - `pytest --tb=short`
  - Unit tests (`@pytest.mark.unit`)
  - Integration tests (`@pytest.mark.integration`)
  - E2E tests (`@pytest.mark.e2e`)

### Test Marker Standard

Tests MUST be marked with one of these markers:

| Marker | Definition | Max Runtime | Dependencies |
|--------|-----------|-------------|--------------|
| `@pytest.mark.unit` | Pure logic, no I/O | 1s per test | None |
| `@pytest.mark.integration` | Tests with services | 10s per test | DB, Redis, etc. |
| `@pytest.mark.e2e` | Full system flows | 60s per test | All services |
| `@pytest.mark.slow` | Expensive operations | 60s+ per test | Varies |

**Unmarked tests default to unit tests.**

### CI Pipeline Mapping

```yaml
# Fast feedback (runs on every push)
- name: Static Checks
  run: just check

# Parallel test execution
- name: Unit Tests
  run: pytest -m unit -n auto

# Sequential (requires infrastructure)
- name: Integration Tests
  run: pytest -m integration

# Optional (manual trigger)
- name: E2E Tests
  run: pytest -m e2e
```

## Rationale

### Why Three Tiers?

1. **Developer Velocity**
   - `check` gives instant feedback (5s)
   - `qa` catches most issues before commit (30s)
   - `qa-full` ensures nothing breaks (3min)

2. **Clear Mental Model**
   - `check` = "Is my code syntactically correct?"
   - `qa` = "Will this break existing functionality?"
   - `qa-full` = "Is this production-ready?"

3. **CI Optimization**
   - Run `check` first (fail fast)
   - Run `unit` tests in parallel
   - Run `integration` tests sequentially
   - Run `e2e` tests on-demand

### Why Not Include Tests in `check`?

**Rejected alternative:** `check` runs all tests

**Problems:**
- Too slow for rapid iteration (3min vs 5s)
- Breaks the "check syntax" mental model
- Forces developers to wait for tests during refactoring
- Conflates static analysis with dynamic validation

**Decision:** Keep `check` fast and focused on static analysis.

### Why `qa` and not `test`?

**Rejected alternative:** `just test` for pre-commit

**Problems:**
- `test` is ambiguous (unit? integration? all?)
- Doesn't convey "quality assurance" intent
- Conflicts with existing `just test` (runs all tests)

**Decision:** `qa` clearly means "quality gate before commit"

## Consequences

### Positive

✅ **Clear workflow:** Developers know exactly what to run when  
✅ **Fast feedback:** `check` runs in seconds  
✅ **Comprehensive validation:** `qa-full` catches everything  
✅ **CI alignment:** Local commands match CI stages  
✅ **Documented standard:** ADR + docs/development/qa-workflow.md

### Negative

⚠️ **Breaking change:** Existing `qa` command behavior changes  
⚠️ **Learning curve:** Developers must learn new commands  
⚠️ **Test marking required:** All tests need proper markers

### Migration Path

1. **Phase 1 (Immediate):**
   - Add new `check`, `qa`, `qa-full` commands
   - Comment out old `qa` command
   - Update documentation

2. **Phase 2 (1 week):**
   - Add test markers to unmarked tests
   - Update CI to use new commands
   - Announce in team channels

3. **Phase 3 (2 weeks):**
   - Remove old `qa` command
   - Make `check` required in pre-commit hook
   - Update onboarding docs

## Implementation

### Justfile Commands

```just
# Static checks: lint + format + typecheck (fast, pre-commit)
check:
    @echo "=== Static Checks ==="
    @uv run ruff check .
    @uv run ruff format --check .
    @uv run pyright || echo "⚠️  Type check failed (non-blocking)"
    @echo "✅ Static checks passed!"

# QA: check + unit tests (pre-commit, fast)
qa: check
    @echo "=== Running Unit Tests ==="
    @uv run pytest -m unit --tb=short
    @echo "✅ QA passed! Ready to commit."

# Full QA: check + all tests (pre-push, CI)
qa-full: check
    @echo "=== Running All Tests ==="
    @uv run pytest --tb=short
    @echo "✅ Full QA passed! Ready to push."
```

### Documentation

- **ADR-035** (this document): Standard definition
- **docs/development/qa-workflow.md**: Developer guide
- **README.md**: Quick reference

## References

- **Incident:** PR #56 - VSA slice refactoring import errors
- **Related ADRs:**
  - ADR-034: Test Infrastructure
- **External:**
  - [pytest markers](https://docs.pytest.org/en/stable/example/markers.html)
  - [Ruff documentation](https://docs.astral.sh/ruff/)

## Versioning

**Version 1.0.0** (2026-01-21)
- Initial standard definition
- Three-tier workflow: check, qa, qa-full
- Test marker requirements

**Future versions:**
- 1.1.0: Add `qa:watch` for continuous testing
- 2.0.0: Add `qa:affected` for changed files only
