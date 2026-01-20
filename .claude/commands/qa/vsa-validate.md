---
description: Run VSA (Vertical Slice Architecture) validation
globs:
alwaysApply: false
---

# VSA Validation

Run VSA validation to ensure all bounded contexts follow vertical slice architecture conventions.

## What is VSA?

**Vertical Slice Architecture** organizes code by business features (vertical slices) rather than technical layers. Each slice contains:
- Command (what we want to do)
- Event (what happened)
- Handler (business logic)
- Aggregate (domain model)
- Tests (validation)

## Running VSA Validation

```bash
# Run VSA validation
just vsa-validate

# Or directly
vsa validate

# Watch mode (auto-validate on changes)
vsa validate --watch
```

## What VSA Checks

VSA validates:
1. **Complete vertical slices** - Each feature has all required components
2. **Naming conventions** - Handlers end with `Handler`, tests start with `test_`
3. **Co-location** - Tests are in the same directory as the feature
4. **Bounded contexts** - Features are properly organized by context

## Expected Output

**Success (0 warnings):**
```
🔍 Validating VSA structure...
✅ Validation passed with 0 warnings
```

**With warnings:**
```
🔍 Validating VSA structure...
⚠️  2 Warning(s)
  ! Feature 'create_artifact' has a command but no handler
  ! Feature 'create_artifact' is missing tests
✅ Validation passed with warnings
```

## Warnings vs Errors

- **Errors:** Block validation (structural violations) - MUST fix
- **Warnings:** Log but allow pass (incomplete features) - SHOULD fix
- **Goal:** 0 warnings for clean architecture

## Configuration

VSA is configured in `vsa.yaml`:
- **Root:** `./packages/aef-domain/src/aef_domain/contexts`
- **Language:** Python
- **Contexts:** artifacts, workflows, workspaces, sessions, github, costs

## Integration

VSA validation is integrated into:
- ✅ `just qa` - Full QA suite
- ✅ `just qa-python` - Python-only QA
- ✅ `scripts/pre_merge_validation.py` - Pre-merge checks

## Fixing Warnings

### Missing Handler

Create a handler file following the naming convention:

```python
# File: packages/aef-domain/src/aef_domain/contexts/<context>/<feature>/<Feature>Handler.py

from .<Feature>Command import <Feature>Command

class <Feature>Handler:
    """Handler for <Feature> command (VSA compliance)."""

    async def handle(self, command: <Feature>Command) -> None:
        """Handle the command."""
        # Implementation or delegate to adapter
        pass
```

### Missing Tests

Create a test file following the naming convention:

```python
# File: packages/aef-domain/src/aef_domain/contexts/<context>/<feature>/test_<feature>.py

import pytest
from .<Feature>Handler import <Feature>Handler

@pytest.mark.unit
def test_handler_exists():
    """VSA requires handler exists."""
    assert <Feature>Handler is not None
```

## Resources

- **VSA Documentation:** `lib/event-sourcing-platform/vsa/README.md`
- **Configuration:** `vsa.yaml`
- **Bounded Contexts:** `packages/aef-domain/src/aef_domain/contexts/`

## When to Run

Run VSA validation:
- ✅ Before committing changes to domain code
- ✅ After adding new features/commands
- ✅ As part of pre-merge validation
- ✅ In CI/CD pipeline

VSA helps maintain clean architecture and ensures all features are complete!

