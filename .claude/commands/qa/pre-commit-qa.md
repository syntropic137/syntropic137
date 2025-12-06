---
description: Run standardized QA checks before committing changes
argument-hint: [--fix to auto-fix issues]
model: sonnet
allowed-tools: Read, Bash
---

# Pre-Commit QA

Run comprehensive quality assurance checks using standardized commands. This prompt is **tool-agnostic** - it uses whatever lint/format/test tools the project has configured via its runner.

> **Prerequisite:** Project must have standardized commands configured.
> Run `/qa-setup audit` to verify, or `/qa-setup setup` to create them.

## Variables

AUTO_FIX: false  # Set to true with --fix argument
RUNNER: auto     # auto-detected: just | npm | uv

## Standard Commands Used

This prompt calls these standardized commands (configured per-project):

| Command | Purpose |
|---------|---------|
| `check` | Run all checks (lint, format, typecheck, test) |
| `check-fix` | Run all checks with auto-fix |
| `lint` | Check for lint errors |
| `format` | Check formatting |
| `typecheck` | Run type checker |
| `test` | Run test suite |
| `build` | Verify project builds |

## Workflow

### Phase 0: Detect Runner

```bash
echo "=== Detecting Runner ==="

if [ -f "justfile" ] || [ -f "Justfile" ]; then
  RUNNER="just"
  echo "Using: just"
elif [ -f "package.json" ] && grep -q '"scripts"' package.json; then
  RUNNER="npm run"
  echo "Using: npm"
elif [ -f "pyproject.toml" ] && grep -q "\[tool.poe" pyproject.toml; then
  RUNNER="poe"
  echo "Using: poe (poethepoet)"
elif [ -f "Makefile" ]; then
  RUNNER="make"
  echo "Using: make (legacy)"
else
  echo "❌ No runner found. Run /qa-setup first."
  exit 1
fi
```

### Phase 1: Quick Check (All-in-One)

If project has a `check` command, use it:

```bash
echo ""
echo "=== Running All Checks ==="

if [ "$AUTO_FIX" = "true" ]; then
  $RUNNER check-fix 2>&1
else
  $RUNNER check 2>&1
fi

CHECK_RESULT=$?
```

### Phase 2: Individual Checks (Fallback or Detailed)

If `check` command fails or doesn't exist, run individually:

```bash
echo ""
echo "=== Individual Checks ==="

# Formatting
echo "--- Format ---"
if [ "$AUTO_FIX" = "true" ]; then
  $RUNNER format-fix 2>&1 || $RUNNER format:fix 2>&1
else
  $RUNNER format 2>&1
fi
FORMAT_RESULT=$?

# Linting
echo ""
echo "--- Lint ---"
$RUNNER lint 2>&1
LINT_RESULT=$?

# Type Checking
echo ""
echo "--- Type Check ---"
$RUNNER typecheck 2>&1
TYPE_RESULT=$?

# Tests
echo ""
echo "--- Tests ---"
$RUNNER test 2>&1
TEST_RESULT=$?

# Build (optional but recommended)
echo ""
echo "--- Build ---"
$RUNNER build 2>&1 || echo "Build command not configured (optional)"
BUILD_RESULT=$?
```

### Phase 3: Staged Changes Review

```bash
echo ""
echo "=== Staged Changes ==="

# Show what will be committed
git diff --cached --stat

# Check for debug statements in staged changes
echo ""
echo "--- Debug Statement Check ---"
if git diff --cached | grep -E "console\.log|print\(|debugger|dbg!" > /dev/null; then
  echo "⚠️ Debug statements found in staged changes:"
  git diff --cached | grep -n -E "console\.log|print\(|debugger|dbg!"
else
  echo "✓ No debug statements found"
fi

# Check for TODO/FIXME
echo ""
echo "--- TODO/FIXME Check ---"
if git diff --cached | grep -E "TODO|FIXME|XXX|HACK" > /dev/null; then
  echo "ℹ️ Pending items in staged changes:"
  git diff --cached | grep -n -E "TODO|FIXME|XXX|HACK"
else
  echo "✓ No pending items found"
fi
```

## Report

```markdown
## Pre-Commit QA Results

**Date:** <timestamp>
**Runner:** $RUNNER
**Auto-fix:** $AUTO_FIX

---

### Check Summary

| Check | Status | Notes |
|-------|--------|-------|
| Format | ✅/❌ | |
| Lint | ✅/❌ | |
| Types | ✅/❌ | |
| Tests | ✅/❌ | |
| Build | ✅/❌/⚪ | (optional) |

---

### Issues Found

<list any errors from individual checks>

---

### Staged Changes

**Files:** <count>
**Debug statements:** <count or "None">
**TODO/FIXME:** <count or "None">

---

### Verdict

**Status:** ✅ READY TO COMMIT / ❌ FIX REQUIRED

<If ready>
**Suggested commit:**
```bash
git commit -m "<type>(<scope>): <description>"
```
</If>

<If not ready>
**To Fix:**
1. Run `$RUNNER check-fix` to auto-fix what's possible
2. Manually fix remaining issues
3. Re-run `/pre-commit-qa`
</If>
```

## Examples

### Example 1: Standard check
```
/pre-commit-qa
```

### Example 2: Auto-fix mode
```
/pre-commit-qa --fix
```

### Example 3: Force specific runner
```
RUNNER=just /pre-commit-qa
```

## Integration Points

- Called by `/review` after implementation verification
- Can be used in pre-commit git hooks
- Mirrors CI/CD pipeline checks locally

## CI/CD Alignment

Configure your CI to use the same commands:

```yaml
# GitHub Actions example
- name: QA Checks
  run: just check  # or: npm run check, poe check
```

This ensures local `/pre-commit-qa` catches the same issues CI would.
