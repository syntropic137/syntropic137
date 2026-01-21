---
description: Create a new git worktree for isolated feature development
argument-hint: <feature-name>
model: sonnet
allowed-tools: Bash, Read
---

# Create Git Worktree

Creates a new git worktree in the standardized location for isolated feature development.

## What is a Git Worktree?

Git worktrees allow you to work on multiple branches simultaneously by creating separate working directories that share the same git repository. This is useful for:

- **Isolated feature development** - Keep main workspace clean
- **Parallel work** - Work on multiple features without stashing
- **Limited context** - AI agents see only relevant code
- **Easy cleanup** - Delete worktree after merge

## Variables

```bash
FEATURE_NAME="$1"
DATE=$(date +%Y%m%d)
REPO_NAME=$(basename $(git rev-parse --show-toplevel))
WORKTREE_ROOT="../${REPO_NAME}_worktrees"
WORKTREE_PATH="${WORKTREE_ROOT}/${DATE}_${FEATURE_NAME}"
```

## Workflow

### Step 1: Validate Input

```bash
if [ -z "$FEATURE_NAME" ]; then
    echo "❌ Error: Feature name required"
    echo ""
    echo "Usage: /git/create-worktree <feature-name>"
    echo ""
    echo "Example: /git/create-worktree vsa-qa-integration"
    exit 1
fi

# Sanitize feature name (replace spaces with hyphens, lowercase)
FEATURE_NAME=$(echo "$FEATURE_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
```

### Step 2: Check Repository

```bash
echo "🔍 Checking git repository..."

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Not in a git repository"
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")
CURRENT_BRANCH=$(git branch --show-current)

echo "   Repository: $REPO_NAME"
echo "   Current branch: $CURRENT_BRANCH"
```

### Step 3: Create Worktree Directory Structure

```bash
echo ""
echo "📁 Creating worktree structure..."

WORKTREE_ROOT="../${REPO_NAME}_worktrees"
DATE=$(date +%Y%m%d)
WORKTREE_PATH="${WORKTREE_ROOT}/${DATE}_${FEATURE_NAME}"

# Create worktrees parent directory if it doesn't exist
mkdir -p "$WORKTREE_ROOT"

if [ -d "$WORKTREE_PATH" ]; then
    echo "⚠️  Worktree already exists: $WORKTREE_PATH"
    echo ""
    echo "Options:"
    echo "  1. Use existing worktree: cd $WORKTREE_PATH"
    echo "  2. Delete and recreate: rm -rf $WORKTREE_PATH && /git/create-worktree $FEATURE_NAME"
    exit 1
fi
```

### Step 4: Create Branch and Worktree

```bash
echo ""
echo "🌿 Creating branch and worktree..."

BRANCH_NAME="feature/${DATE}-${FEATURE_NAME}"

# Create new branch from current HEAD
git branch "$BRANCH_NAME"

# Create worktree
git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"

if [ $? -ne 0 ]; then
    echo "❌ Failed to create worktree"
    exit 1
fi
```

### Step 5: Summary and Next Steps

```bash
echo ""
echo "✅ Worktree created successfully!"
echo ""
echo "📊 Summary:"
echo "   Location: $WORKTREE_PATH"
echo "   Branch:   $BRANCH_NAME"
echo ""
echo "🚀 Next Steps:"
echo ""
echo "1. Navigate to worktree:"
echo "   cd $WORKTREE_PATH"
echo ""
echo "2. Open in your editor:"
echo "   cursor ."
echo "   # or: code ."
echo "   # or: claude"
echo ""
echo "3. Start working on your feature"
echo ""
echo "4. When done, merge and cleanup:"
echo "   git checkout main"
echo "   git merge $BRANCH_NAME"
echo "   git worktree remove $WORKTREE_PATH"
echo "   git branch -d $BRANCH_NAME"
echo ""
echo "📝 Worktree Management:"
echo "   List all worktrees:  git worktree list"
echo "   Remove worktree:     git worktree remove $WORKTREE_PATH"
echo "   Prune stale:         git worktree prune"
```

## Example Usage

```bash
# Create worktree for VSA integration feature
/git/create-worktree vsa-qa-integration

# Results in:
../agentic-engineering-framework_worktrees/20260118_vsa-qa-integration/

# With branch:
feature/20260118-vsa-qa-integration
```

## Tips

**For AI Agents:**
- Worktrees provide isolated context - only feature-relevant code is visible
- Reduces token usage by limiting file access
- Clean state for testing

**Multiple Worktrees:**
You can have multiple worktrees active simultaneously:
```bash
/git/create-worktree feature-a
/git/create-worktree feature-b
/git/create-worktree hotfix-c
```

**Cleanup:**
Always remove worktrees when done to avoid stale references:
```bash
git worktree remove ../repo_worktrees/20260118_feature-name
git worktree prune
```

