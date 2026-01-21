# QA Workflow Standard

## Overview

This document defines the standard QA workflow for the Agentic Engineering Framework. It ensures code quality while optimizing for developer velocity.

## Command Hierarchy

```
just check      → Static analysis (fast, pre-commit)
just qa         → check + unit tests (pre-commit)
just qa-full    → qa + integration tests (pre-push, CI)
```

## Commands

### `just check` - Static Checks

**Purpose:** Fast static analysis before committing  
**Runtime:** ~5-10 seconds  
**When:** Before every commit

**Includes:**
1. **Linting** - `ruff check .`
2. **Format validation** - `ruff format --check .`
3. **Type checking** - `pyright` (non-blocking warnings)

**Usage:**
```bash
# Check only
just check

# Check with auto-fix
just check-fix
```

### `just qa` - Quick QA

**Purpose:** Pre-commit validation with fast tests  
**Runtime:** ~15-30 seconds  
**When:** Before committing significant changes

**Includes:**
- All `check` steps
- **Unit tests** - `pytest -m unit`

**Usage:**
```bash
# QA with existing formatting
just qa

# QA with auto-fix
just qa-fix
```

### `just qa-full` - Complete QA

**Purpose:** Comprehensive validation before pushing  
**Runtime:** ~2-5 minutes  
**When:** Before pushing to remote, in CI

**Includes:**
- All `check` steps
- **All tests** - `pytest` (unit + integration + e2e)

**Usage:**
```bash
just qa-full
```

## Test Markers

Tests are organized using pytest markers:

| Marker | Purpose | Runtime | Run In |
|--------|---------|---------|--------|
| `@pytest.mark.unit` | Fast, isolated tests | <1s each | Local, CI |
| `@pytest.mark.integration` | Tests with external services | 1-10s each | CI, optional local |
| `@pytest.mark.e2e` | Full end-to-end flows | 10s+ each | CI, manual local |
| `@pytest.mark.slow` | Expensive tests | 30s+ each | CI only |

## CI vs Local Tests

### Local Development (Fast Feedback)

```bash
# Before commit
just qa              # Unit tests only (~30s)

# Before push (optional)
just qa-full         # All tests (~5min)
```

### CI Pipeline (Comprehensive)

```yaml
# .github/workflows/ci.yaml
- name: QA Checks
  run: just check

- name: Unit Tests
  run: pytest -m unit

- name: Integration Tests
  run: pytest -m integration

- name: E2E Tests
  run: pytest -m e2e
```

## Recommended Workflow

### Daily Development

```bash
# 1. Make changes
vim file.py

# 2. Quick validation
just check           # Fast feedback

# 3. Run related tests
pytest path/to/test.py -v

# 4. Full QA before commit
just qa

# 5. Commit
git commit -m "feat: add feature"
```

### Before Push

```bash
# Full validation
just qa-full

# Push
git push origin feature-branch
```

## Git Hooks (Optional)

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
just qa || exit 1
```

Add to `.git/hooks/pre-push`:

```bash
#!/bin/bash
just qa-full || exit 1
```

## Test Organization

### Unit Tests (Fast)

```python
@pytest.mark.unit
def test_pure_function():
    """No I/O, no mocks needed."""
    result = calculate(1, 2)
    assert result == 3
```

### Integration Tests (Medium)

```python
@pytest.mark.integration
async def test_with_database(db_pool):
    """Tests with real services."""
    async with db_pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
        assert result == 1
```

### E2E Tests (Slow)

```python
@pytest.mark.e2e
async def test_full_workflow(test_infrastructure):
    """Full system test."""
    workflow = await execute_workflow("test")
    assert workflow.status == "completed"
```

## Performance Targets

| Command | Target Runtime | Max Runtime |
|---------|---------------|-------------|
| `just check` | 5s | 15s |
| `just qa` | 30s | 1min |
| `just qa-full` | 3min | 10min |

## Troubleshooting

### "Tests are too slow"

1. Ensure tests have proper markers
2. Use `pytest -m unit` for fast feedback
3. Consider using `pytest-xdist` for parallelization

### "Check failed but code looks fine"

```bash
# Auto-fix formatting/lint issues
just check-fix

# Re-run checks
just check
```

### "Integration tests fail locally"

```bash
# Start test infrastructure
just test-stack

# Run integration tests
pytest -m integration

# Cleanup
just test-stack-down
```

## References

- [pytest markers documentation](https://docs.pytest.org/en/stable/example/markers.html)
- [Ruff configuration](https://docs.astral.sh/ruff/)
- [ADR-034: Test Infrastructure](../adrs/ADR-034-test-infrastructure.md)
