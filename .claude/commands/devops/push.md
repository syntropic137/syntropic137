---
description: Push to remote and wait for CI status
argument-hint: [--no-wait] [--remote origin]
model: sonnet
allowed-tools: Bash
---

# Push

Push changes to remote and optionally wait for CI to complete.

## Purpose

*Level 3 (Control Flow)*

Push the current branch to remote and monitor CI status until completion or timeout.

## Variables

REMOTE: $1 || "origin"          # Remote name
WAIT_FOR_CI: $2 || true         # Wait for CI (--no-wait to disable)
CI_TIMEOUT: 600                 # Timeout in seconds (10 min)
POLL_INTERVAL: 30               # Check every 30 seconds

## Instructions

- If branch has no upstream, use -u flag to set it
- Poll CI status until pass/fail or timeout
- Report final status with details
- Exit 0 on success, 1 on failure

## Workflow

### 1. Get Current Branch

```bash
echo "=== Current State ==="
BRANCH=$(git branch --show-current)
echo "Branch: ${BRANCH}"
echo "Remote: ${REMOTE}"
```

### 2. Push to Remote

```bash
echo ""
echo "=== Pushing to ${REMOTE} ==="

# Check if upstream exists
if git rev-parse --abbrev-ref @{u} > /dev/null 2>&1; then
  git push ${REMOTE} ${BRANCH}
else
  echo "Setting upstream..."
  git push -u ${REMOTE} ${BRANCH}
fi

PUSH_RESULT=$?
if [ $PUSH_RESULT -ne 0 ]; then
  echo "❌ Push failed"
  exit 1
fi
echo "✅ Pushed to ${REMOTE}/${BRANCH}"
```

### 3. Wait for CI (if enabled)

If WAIT_FOR_CI is true:

```bash
echo ""
echo "=== Waiting for CI ==="

ELAPSED=0
while [ $ELAPSED -lt $CI_TIMEOUT ]; do
  # Check CI status via gh CLI
  STATUS=$(gh pr checks --json state -q '.[].state' 2>/dev/null | sort -u)

  # Check for any failures
  if echo "$STATUS" | grep -q "FAILURE"; then
    echo ""
    echo "❌ CI failed"
    echo ""
    gh pr checks
    exit 1
  fi

  # Check if still pending
  if echo "$STATUS" | grep -q "PENDING"; then
    echo "⏳ CI pending... (${ELAPSED}s / ${CI_TIMEOUT}s)"
    sleep $POLL_INTERVAL
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
    continue
  fi

  # If we get here, no failures and no pending = success
  if [ -n "$STATUS" ]; then
    echo ""
    echo "✅ CI passed"
    gh pr checks
    exit 0
  fi

  # No status yet (PR might not exist)
  echo "⏳ Waiting for CI to start... (${ELAPSED}s)"
  sleep $POLL_INTERVAL
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

# Timeout reached
echo ""
echo "⚠️ CI timeout after ${CI_TIMEOUT}s"
gh pr checks 2>/dev/null || echo "No PR checks available"
exit 1
```

### 4. Skip CI Wait

If WAIT_FOR_CI is false:

```bash
echo ""
echo "✅ Push complete (CI wait skipped)"
echo "Run 'gh pr checks' to monitor CI status"
```

## Report

```markdown
## Push Complete

**Branch:** ${BRANCH}
**Remote:** ${REMOTE}
**CI Wait:** ${WAIT_FOR_CI}

### Result

| Step | Status |
|------|--------|
| Push | ✅ Success |
| CI | ✅ Passed / ❌ Failed / ⏳ Skipped / ⚠️ Timeout |

### CI Checks
<gh pr checks output if available>

### Next Steps
- If CI passed: Run `/review/fetch` to check for review comments
- If CI failed: Fix issues and run `/qa/pre-commit-qa` again
- If no PR: Create PR with `gh pr create`
```

## Examples

### Example 1: Push and wait for CI (default)
```
/push
```

### Example 2: Push without waiting
```
/push --no-wait
```
Sets WAIT_FOR_CI to false.

### Example 3: Push to different remote
```
/push upstream
```
Pushes to `upstream` remote instead of `origin`.

## Integration Points

- Called by `/workflow/merge-cycle` after commit
- Pairs with `/devops/commit` for full commit-push flow
- Uses `gh` CLI for CI status (requires GitHub CLI installed)
