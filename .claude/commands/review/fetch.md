---
description: Fetch PR review comments from GitHub
argument-hint: [pr-number] - auto-detects from current branch if omitted
model: sonnet
allowed-tools: Bash
---

# Fetch Review Comments

Retrieve all review comments for a pull request.

## Purpose

*Level 2 (Workflow)*

Fetch and parse PR review comments to identify required changes.

## Variables

PR_NUMBER: $1 || ""    # Auto-detect if not provided

## Workflow

### 1. Detect PR Number

```bash
echo "=== Detecting PR ==="

if [ -z "${PR_NUMBER}" ]; then
  PR_NUMBER=$(gh pr view --json number -q '.number' 2>/dev/null)

  if [ -z "${PR_NUMBER}" ]; then
    echo "❌ No PR found for current branch"
    echo ""
    echo "To create a PR, run:"
    echo "  gh pr create"
    exit 0  # Exit cleanly - no comments is valid state
  fi
fi

echo "PR #${PR_NUMBER}"
```

### 2. Get PR Details

```bash
echo ""
echo "=== PR Details ==="

gh pr view ${PR_NUMBER} --json title,state,reviewDecision,reviews \
  --template '{{.title}}
State: {{.state}}
Review Decision: {{.reviewDecision}}
Reviews: {{len .reviews}}
'
```

### 3. Fetch Review Comments

```bash
echo ""
echo "=== Review Comments ==="

# Get review summaries
gh pr view ${PR_NUMBER} --json reviews \
  --jq '.reviews[] | "[\(.state)] @\(.author.login): \(.body // "No comment")"'
```

### 4. Fetch Inline Comments

```bash
echo ""
echo "=== Inline Comments ==="

# Get inline/file comments using API
gh api repos/{owner}/{repo}/pulls/${PR_NUMBER}/comments \
  --jq '.[] | "[\(.path):\(.line // .original_line)] @\(.user.login):\n  \(.body)\n"' 2>/dev/null \
  || echo "No inline comments"
```

### 5. Check for Pending Reviews

```bash
echo ""
echo "=== Pending Reviews ==="

gh pr view ${PR_NUMBER} --json reviewRequests \
  --jq '.reviewRequests[] | "Awaiting: @\(.login // .name)"' 2>/dev/null \
  || echo "No pending review requests"
```

## Report

```markdown
## PR #${PR_NUMBER} Review Comments

### Summary

| Metric | Value |
|--------|-------|
| PR Number | #${PR_NUMBER} |
| State | Open / Merged / Closed |
| Review Decision | Approved / Changes Requested / Pending |
| Total Comments | X |

### Reviews

#### @reviewer1 - APPROVED
> Great work!

#### @copilot - COMMENTED
> Consider adding error handling for edge cases.

### Inline Comments

#### `path/to/file.py:42`
@reviewer: This could be simplified using a list comprehension.

#### `path/to/other.py:15`
@copilot: Potential null pointer dereference here.

### Action Items

Based on the comments above:

- [ ] Address comment at file.py:42
- [ ] Fix issue at other.py:15
- [ ] Respond to reviewer questions

### Next Steps

- If changes requested: Fix issues, then run `/qa/pre-commit-qa`
- If approved: Run `/devops/merge` to complete
- To prioritize comments: Run `/review/prioritize`
```

## Examples

### Example 1: Auto-detect PR
```
/review/fetch
```
Detects PR from current branch.

### Example 2: Specific PR
```
/review/fetch 42
```
Fetches comments for PR #42.

## Integration Points

- Called by `/workflow/merge-cycle` after CI passes
- Output feeds into `/review/prioritize` for triage
- Requires `gh` CLI with repo access
