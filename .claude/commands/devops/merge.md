---
description: Merge PR and cleanup branch
argument-hint: [--target develop] [--method squash] [--no-delete]
model: sonnet
allowed-tools: Bash
---

# Merge

Merge the current PR and optionally delete the feature branch.

## Purpose

*Level 3 (Control Flow)*

Complete the PR workflow by merging to target branch and cleaning up.

## Variables

TARGET_BRANCH: $1 || "develop"     # Target branch for merge
MERGE_METHOD: $2 || "squash"       # squash, merge, or rebase
DELETE_BRANCH: $3 || true          # Delete feature branch after merge

## Instructions

- Verify CI is green before merging
- If CI not green, abort with clear instructions
- Use gh CLI for merge operations
- Handle merge conflicts gracefully

## Workflow

### 1. Get Current State

```bash
echo "=== Current State ==="
BRANCH=$(git branch --show-current)
echo "Feature branch: ${BRANCH}"
echo "Target branch: ${TARGET_BRANCH}"
echo "Merge method: ${MERGE_METHOD}"
echo "Delete branch: ${DELETE_BRANCH}"

# Verify we're not on target branch
if [ "${BRANCH}" = "${TARGET_BRANCH}" ]; then
  echo "❌ Cannot merge: already on ${TARGET_BRANCH}"
  exit 1
fi
```

### 2. Verify CI Status

```bash
echo ""
echo "=== Verifying CI Status ==="

# Check if PR exists
PR_NUMBER=$(gh pr view --json number -q '.number' 2>/dev/null)
if [ -z "${PR_NUMBER}" ]; then
  echo "❌ No PR found for branch ${BRANCH}"
  echo ""
  echo "Create a PR first:"
  echo "  gh pr create --base ${TARGET_BRANCH}"
  exit 1
fi
echo "PR #${PR_NUMBER}"

# Check CI status
CI_STATUS=$(gh pr checks --json state -q '.[].state' 2>/dev/null | sort -u)

if echo "$CI_STATUS" | grep -q "FAILURE"; then
  echo "❌ CI is failing - cannot merge"
  echo ""
  gh pr checks
  echo ""
  echo "Fix CI failures before merging."
  exit 1
fi

if echo "$CI_STATUS" | grep -q "PENDING"; then
  echo "⏳ CI is still running"
  echo ""
  echo "Wait for CI to complete or use /devops/push to monitor."
  exit 1
fi

echo "✅ CI is green"
```

### 3. Check Review Status

```bash
echo ""
echo "=== Review Status ==="

REVIEW_DECISION=$(gh pr view --json reviewDecision -q '.reviewDecision' 2>/dev/null)
echo "Review decision: ${REVIEW_DECISION:-"None"}"

# Warning if not approved (but don't block)
if [ "${REVIEW_DECISION}" = "CHANGES_REQUESTED" ]; then
  echo "⚠️ Changes have been requested"
  echo "Consider addressing review comments before merging."
fi
```

### 4. Merge PR

```bash
echo ""
echo "=== Merging PR ==="

# Build merge command
MERGE_CMD="gh pr merge ${PR_NUMBER}"

case "${MERGE_METHOD}" in
  squash)
    MERGE_CMD="${MERGE_CMD} --squash"
    ;;
  merge)
    MERGE_CMD="${MERGE_CMD} --merge"
    ;;
  rebase)
    MERGE_CMD="${MERGE_CMD} --rebase"
    ;;
  *)
    echo "❌ Invalid merge method: ${MERGE_METHOD}"
    echo "Valid options: squash, merge, rebase"
    exit 1
    ;;
esac

if [ "${DELETE_BRANCH}" = "true" ]; then
  MERGE_CMD="${MERGE_CMD} --delete-branch"
fi

echo "Running: ${MERGE_CMD}"
${MERGE_CMD}

MERGE_RESULT=$?
if [ $MERGE_RESULT -ne 0 ]; then
  echo ""
  echo "❌ Merge failed"
  echo ""
  echo "Common issues:"
  echo "  - Merge conflicts: resolve locally and push"
  echo "  - Branch protection: ensure requirements met"
  echo "  - Stale branch: pull and rebase"
  exit 1
fi

echo "✅ PR merged successfully"
```

### 5. Cleanup Local

```bash
echo ""
echo "=== Cleanup ==="

# Switch to target branch
git checkout ${TARGET_BRANCH}
git pull origin ${TARGET_BRANCH}

# Delete local feature branch if it still exists
if [ "${DELETE_BRANCH}" = "true" ]; then
  git branch -d ${BRANCH} 2>/dev/null && echo "✅ Deleted local branch ${BRANCH}" || echo "ℹ️ Local branch already deleted"
fi

echo ""
echo "✅ Now on ${TARGET_BRANCH}"
git log -1 --oneline
```

## Report

```markdown
## Merge Complete

**PR:** #${PR_NUMBER}
**Branch:** ${BRANCH} → ${TARGET_BRANCH}
**Method:** ${MERGE_METHOD}
**Branch Deleted:** ${DELETE_BRANCH}

### Result

| Step | Status |
|------|--------|
| CI Verification | ✅ |
| Merge | ✅ |
| Cleanup | ✅ |

### Current State

Now on: ${TARGET_BRANCH}
Latest commit: <hash> <message>

### Next Steps

- Start a new feature branch for next work
- Or run `/workflow/merge-cycle` on another branch
```

## Examples

### Example 1: Default merge to develop
```
/merge
```
Squash merges to `develop`, deletes feature branch.

### Example 2: Merge to main
```
/merge main
```
Squash merges to `main`.

### Example 3: Regular merge, keep branch
```
/merge develop merge --no-delete
```
Regular merge commit, keeps feature branch.

### Example 4: Rebase merge
```
/merge develop rebase
```
Rebases onto develop.

## Integration Points

- Final step in `/workflow/merge-cycle`
- Requires CI to be green (use `/devops/push` first)
- Uses `gh` CLI for GitHub operations
