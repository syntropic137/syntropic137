---
description: Create conventional commits with proper formatting
argument-hint: [type] [scope] [message] - or leave blank for interactive
model: sonnet
allowed-tools: Read, Bash
---

# Commit

Create a well-formatted conventional commit.

## Purpose

*Level 2 (Workflow)*

Stage related files logically and create conventional commit messages following the format: `type(scope): description`

## Variables

TYPE: $1 || ""           # feat, fix, docs, style, refactor, test, chore
SCOPE: $2 || ""          # Component/area affected
MESSAGE: $3 || ""        # Commit message (auto-generated if blank)

## Workflow

### 1. Analyze Changes

```bash
echo "=== Analyzing Changes ==="
git status --short
echo ""
echo "=== Diff Summary ==="
git diff --stat
echo ""
echo "=== Staged Changes ==="
git diff --cached --stat
```

Review the changes to understand:
- What files were modified
- Whether changes are already staged
- The nature of the changes (new feature, fix, docs, etc.)

### 2. Determine Commit Type

If TYPE not provided, analyze changes to suggest:

| Pattern | Suggested Type |
|---------|----------------|
| New files/features | `feat` |
| Bug fixes, error handling | `fix` |
| Documentation only (.md, comments) | `docs` |
| Formatting, whitespace | `style` |
| Code restructure, no behavior change | `refactor` |
| Test files only | `test` |
| Dependencies, config, tooling | `chore` |

### 3. Determine Scope

If SCOPE not provided, infer from file paths:

| Path Pattern | Suggested Scope |
|--------------|-----------------|
| `cli/` | cli |
| `primitives/` | primitives |
| `docs/` | docs |
| `tests/` | tests |
| `*.rs` | core |
| `*.py` | python |
| Multiple distinct areas | omit scope |

### 4. Generate Message

If MESSAGE not provided:
- Summarize the changes in **imperative mood** ("add", not "added")
- Keep under 72 characters
- Focus on **what** changed, not **how**
- Be specific but concise

Good examples:
- `feat(cli): add version bump command`
- `fix(validators): handle empty metadata files`
- `docs: update ADR-019 with examples`

Bad examples:
- `fixed stuff` (vague)
- `Updated the validation logic to check for...` (too long, wrong tense)

### 5. Stage Changes

```bash
# If nothing staged, stage all changes
if [ -z "$(git diff --cached --name-only)" ]; then
  echo "=== Staging All Changes ==="
  git add -A
  git status --short
fi
```

### 6. Create Commit

```bash
# Build commit message
if [ -n "${SCOPE}" ]; then
  FULL_MESSAGE="${TYPE}(${SCOPE}): ${MESSAGE}"
else
  FULL_MESSAGE="${TYPE}: ${MESSAGE}"
fi

echo ""
echo "=== Creating Commit ==="
echo "Message: ${FULL_MESSAGE}"
echo ""

git commit -m "${FULL_MESSAGE}"
```

### 7. Verify

```bash
echo ""
echo "=== Commit Created ==="
git log -1 --oneline
git log -1 --stat
```

## Report

```markdown
## Commit Created

**Hash:** <short-hash>
**Type:** ${TYPE}
**Scope:** ${SCOPE}
**Message:** ${MESSAGE}

**Full commit:**
\`\`\`
${TYPE}(${SCOPE}): ${MESSAGE}
\`\`\`

**Files Changed:**
<file list with +/- stats>

**Next Steps:**
- Run `/devops/push` to push to remote
- Or continue making changes
```

## Conventional Commit Types

| Type | When to Use | Example |
|------|-------------|---------|
| `feat` | New feature for users | `feat(auth): add OAuth login` |
| `fix` | Bug fix for users | `fix(api): handle null response` |
| `docs` | Documentation only | `docs: add setup instructions` |
| `style` | Formatting, no code change | `style: fix indentation` |
| `refactor` | Code change, no behavior change | `refactor: extract helper function` |
| `test` | Adding/updating tests | `test: add unit tests for parser` |
| `chore` | Maintenance, tooling | `chore(deps): update dependencies` |

## Examples

### Example 1: Auto-detect everything
```
/commit
```
Analyzes changes and suggests type, scope, and message.

### Example 2: Specify type only
```
/commit feat
```
Uses `feat` type, auto-detects scope and message.

### Example 3: Full specification
```
/commit feat cli "add version bump command"
```
Creates: `feat(cli): add version bump command`

### Example 4: No scope
```
/commit docs "" "update README with examples"
```
Creates: `docs: update README with examples`
