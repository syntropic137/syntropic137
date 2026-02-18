---
description: Evaluate changes since last version and automatically bump version
---

# Version Evaluate & Bump

Create a new semantic version release with automated tagging, changelog generation, and deployment.

## Purpose

Analyze changes since the last version, automatically determine the appropriate version bump (patch/minor/major), and create a new release. Agent-driven version selection based on change analysis.

## Variables

CHANNEL: beta      # beta | stable (stable requires explicit confirmation)
REPO: aef          # aef | agentic-primitives | both
MESSAGE: ""        # Optional version message

## Agent Instructions

**Your job is to analyze the changes since the last version and determine the appropriate version bump.**

- Read the git log and diffs since the last tag
- Analyze the nature of changes (features, fixes, breaking)
- Automatically choose `minor` or `patch` (most common)
- Only ask for human confirmation if you detect a **breaking change** (rare)

**Decision criteria:**
- **patch**: Bug fixes, documentation, refactoring, no new features
- **minor**: New features, enhancements, non-breaking changes (most common in beta)
- **major**: Breaking changes (requires human confirmation before proceeding)

## Current Status

**AEF is in BETA** - All releases should use `beta` channel until production-ready.

Beta versions follow: `v0.{minor}.{patch}-beta.{build}`
Example: `v0.3.0-beta.1`, `v0.3.0-beta.2`, etc.

## Workflow

### Phase 1: Pre-Release Checks

1. **Verify Clean State**
   ```bash
   cd /Users/neural/Code/syntropic137/agentic-engineering-framework

   # Check for uncommitted changes
   if [ -n "$(git status --porcelain)" ]; then
     echo "❌ Uncommitted changes found. Commit or stash first."
     exit 1
   fi

   # Check we're on main
   BRANCH=$(git branch --show-current)
   if [ "$BRANCH" != "main" ]; then
     echo "⚠️  Current branch: $BRANCH (should be main)"
     echo "Continue? (y/n)"
     # Wait for confirmation
   fi
   ```

2. **Run Full QA**
   ```bash
   echo "=== Running QA Checks ==="
   just qa 2>&1 | tee qa-results.log

   if [ ${PIPESTATUS[0]} -ne 0 ]; then
     echo "❌ QA checks failed. Fix issues before releasing."
     exit 1
   fi
   ```

3. **Check CI Status** (if on feature branch)
   ```bash
   if [ "$BRANCH" != "main" ]; then
     echo "=== Checking CI Status ==="
     gh pr checks --watch
   fi
   ```

### Phase 2: Change Analysis & Version Calculation

4. **Get Current Version**
   ```bash
   echo "=== Current Version ==="

   # For AEF
   CURRENT_AEF=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
   echo "AEF: $CURRENT_AEF"

   # For agentic-primitives (if both)
   if [ "$REPO" = "both" ]; then
     cd lib/agentic-primitives
     CURRENT_PRIM=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
     echo "agentic-primitives: $CURRENT_PRIM"
     cd ../..
   fi
   ```

5. **Analyze Changes Since Last Version**
   ```bash
   echo ""
   echo "=== Analyzing Changes Since $CURRENT_AEF ==="

   # Get commit messages
   git log $CURRENT_AEF..HEAD --pretty=format:"%s" --no-merges > /tmp/commits.txt

   # Get file changes
   git diff $CURRENT_AEF..HEAD --stat > /tmp/diffstat.txt
   git diff $CURRENT_AEF..HEAD --name-only > /tmp/files.txt

   # Show summary
   echo ""
   echo "Commits since last version:"
   cat /tmp/commits.txt
   echo ""
   echo "Files changed:"
   cat /tmp/diffstat.txt
   ```

6. **Determine Version Type (Agent Decision)**

   **Read the files from /tmp/ and analyze:**

   a) **Look for breaking changes:**
      - API changes that remove/rename endpoints
      - Database schema changes requiring migration
      - Configuration format changes
      - Removed or renamed public functions/classes
      - Changes to CLI command signatures

   b) **Look for new features:**
      - New files in `features/`, `commands/`, `api/`
      - Commit messages starting with `feat:`, `feature:`
      - New public API methods/classes
      - New CLI commands
      - New workflow capabilities

   c) **Look for bug fixes only:**
      - Commit messages with `fix:`, `bugfix:`
      - Changes only in test files
      - Documentation updates
      - Refactoring without new features

   **Decision logic:**
   ```
   IF breaking changes detected:
     TYPE = "major"
     STOP and ask user: "⚠️ Potential breaking change detected: {description}. Proceed with major version? (y/n)"

   ELSE IF new features detected (feat: commits, new files, new capabilities):
     TYPE = "minor"

   ELSE (only fixes, docs, refactoring):
     TYPE = "patch"
   ```

   **Output your analysis:**
   ```
   ## Change Analysis

   **Breaking changes:** {list or "None detected"}
   **New features:** {list}
   **Bug fixes:** {list}
   **Other changes:** {list}

   **Recommendation:** {TYPE} version bump
   **Reason:** {explanation}
   ```

7. **Calculate Next Version**
   ```bash
   # Parse current version (e.g., v0.2.0-beta.3)
   VERSION_CORE=$(echo $CURRENT_AEF | sed 's/-beta.*//' | sed 's/^v//')
   MAJOR=$(echo $VERSION_CORE | cut -d. -f1)
   MINOR=$(echo $VERSION_CORE | cut -d. -f2)
   PATCH=$(echo $VERSION_CORE | cut -d. -f3)

   # Get beta number if exists
   if [[ $CURRENT_AEF == *"-beta."* ]]; then
     BETA_NUM=$(echo $CURRENT_AEF | sed 's/.*-beta\.//')
   else
     BETA_NUM=0
   fi

   # Calculate next version based on TYPE
   case $TYPE in
     major)
       MAJOR=$((MAJOR + 1))
       MINOR=0
       PATCH=0
       BETA_NUM=1
       ;;
     minor)
       MINOR=$((MINOR + 1))
       PATCH=0
       BETA_NUM=1
       ;;
     patch)
       PATCH=$((PATCH + 1))
       BETA_NUM=1
       ;;
     beta)
       # Just increment beta number
       BETA_NUM=$((BETA_NUM + 1))
       ;;
   esac

   # Construct new version
   if [ "$CHANNEL" = "beta" ]; then
     NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}-beta.${BETA_NUM}"
   else
     NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
   fi

   echo ""
   echo "📦 Next version: $NEW_VERSION"
   ```

### Phase 3: Generate Changelog

6. **Create Changelog Entry**
   ```bash
   echo "=== Generating Changelog ==="

   # Get commits since last tag
   CHANGELOG=$(git log $CURRENT_AEF..HEAD --pretty=format:"- %s (%h)" --no-merges)

   # Get PR numbers if available
   PR_LINKS=$(git log $CURRENT_AEF..HEAD --pretty=format:"%s" --no-merges | \
              grep -oE '\(#[0-9]+\)' | sort -u)

   echo ""
   echo "## $NEW_VERSION ($(date +%Y-%m-%d))"
   echo ""
   if [ -n "$MESSAGE" ]; then
     echo "$MESSAGE"
     echo ""
   fi
   echo "### Changes"
   echo "$CHANGELOG"

   if [ -n "$PR_LINKS" ]; then
     echo ""
     echo "### Pull Requests"
     echo "$PR_LINKS"
   fi
   ```

### Phase 4: Update Version Files

7. **Update Package Versions**
   ```bash
   echo "=== Updating Package Files ==="

   # Update pyproject.toml files
   find . -name "pyproject.toml" -not -path "*/\.*" | while read -r file; do
     if grep -q "^version = " "$file"; then
       sed -i '' "s/^version = .*/version = \"${MAJOR}.${MINOR}.${PATCH}\"/" "$file"
       echo "✓ Updated: $file"
     fi
   done

   # Update package.json (dashboard)
   if [ -f "apps/syn-dashboard-ui/package.json" ]; then
     cd apps/syn-dashboard-ui
     npm version "${MAJOR}.${MINOR}.${PATCH}" --no-git-tag-version
     echo "✓ Updated: package.json"
     cd ../..
   fi
   ```

8. **Commit Version Bump**
   ```bash
   git add -A
   git commit -m "chore: bump version to $NEW_VERSION"
   ```

### Phase 5: Tag and Release

9. **Create Git Tag**
   ```bash
   echo "=== Creating Git Tag ==="

   # Create annotated tag with changelog
   git tag -a "$NEW_VERSION" -m "Release $NEW_VERSION

$(echo "$CHANGELOG" | head -20)

$(if [ -n "$MESSAGE" ]; then echo "$MESSAGE"; fi)"

   echo "✓ Created tag: $NEW_VERSION"
   ```

10. **Push to Remote**
    ```bash
    echo "=== Pushing to Remote ==="

    git push origin main
    git push origin "$NEW_VERSION"

    echo "✓ Pushed to origin"
    ```

11. **Create GitHub Release**
    ```bash
    echo "=== Creating GitHub Release ==="

    # Determine if pre-release
    PRERELEASE_FLAG=""
    if [ "$CHANNEL" = "beta" ]; then
      PRERELEASE_FLAG="--prerelease"
    fi

    gh release create "$NEW_VERSION" \
      --title "$NEW_VERSION" \
      --notes "$CHANGELOG" \
      $PRERELEASE_FLAG

    echo "✓ Created GitHub release"
    ```

### Phase 6: Post-Release

12. **Verify Release**
    ```bash
    echo "=== Verifying Release ==="

    # Check tag exists
    git tag -l "$NEW_VERSION"

    # Check GitHub release
    gh release view "$NEW_VERSION"

    # Check CI/CD triggered
    gh run list --limit 3
    ```

13. **Update Submodules** (if both repos)
    ```bash
    if [ "$REPO" = "both" ]; then
      echo ""
      echo "⚠️  Remember to update agentic-primitives submodule pointer in AEF!"
      echo ""
      echo "Commands:"
      echo "  cd lib/agentic-primitives"
      echo "  git checkout v{version}"
      echo "  cd ../.."
      echo "  git add lib/agentic-primitives"
      echo "  git commit -m 'chore: update agentic-primitives to {version}'"
    fi
    ```

## Beta Release Strategy

**Current Phase: Beta (v0.x.x-beta.N)**

- All releases are beta until explicitly marked stable
- Beta versions allow for breaking changes
- Format: `v0.{minor}.{patch}-beta.{build}`

**Agent automatically chooses:**
- **patch** (v0.3.1-beta.1): Only bug fixes, no new features
- **minor** (v0.4.0-beta.1): New features or enhancements (most common)
- **major** (v1.0.0-beta.1): Breaking changes (asks for confirmation)

**Examples from actual changes:**
- "fix: template copying in prompts" → **patch**
- "feat: add workspace file capture to recordings" → **minor**
- "feat!: remove legacy execute method, change artifact paths" → **major** (confirm)

**Moving to Stable (v1.0.0):**
- Requires explicit `CHANNEL=stable`
- Agent still analyzes changes for version type
- Full test coverage required
- Production deployments validated
- Documentation complete

## Report

## Version Release Summary

**Repository:** {REPO}
**Previous Version:** {CURRENT_VERSION}
**New Version:** {NEW_VERSION}
**Type:** {TYPE}
**Channel:** {CHANNEL}

---

### Changes

{CHANGELOG}

---

### Updated Files
- {list of updated version files}

---

### Git Tags
- ✅ Tag created: {NEW_VERSION}
- ✅ Pushed to remote

### GitHub Release
- ✅ Release created: {URL}
- 🔗 {RELEASE_URL}

---

### Next Steps

{if beta}
- ✅ Beta release available for testing
- Run workflows using new version
- Monitor for issues
- Plan next release based on feedback
{endif}

{if stable}
- ✅ Stable release published
- Update production deployments
- Announce to users
- Update documentation site
{endif}

## Examples

### Example 1: Automatic version evaluation & bump
```
/version-eval-and-bump
```
Agent analyzes changes and automatically chooses minor or patch.

### Example 2: With custom message
```
/version-eval-and-bump "Add multi-phase workflow support"
```
Agent analyzes, chooses version type, includes your message.

### Example 3: Release both repos
```
/version-eval-and-bump both
```
Agent analyzes both repos and versions appropriately.

### Example 4: Move to stable channel
```
/version-eval-and-bump stable "Production ready release"
```
Agent still analyzes changes but releases to stable channel.

### Example 5: Agent detects breaking change
```
/version-eval-and-bump
```
Output:
```
⚠️ Potential breaking change detected:
- Removed WorkspaceService.execute_legacy() method
- Changed artifact path structure (breaking for existing workflows)

This would be a MAJOR version bump (v1.0.0).
Proceed? (y/n)
```

## Safety Checks

- ❌ Blocks if uncommitted changes exist
- ⚠️  Warns if not on main branch
- ❌ Blocks if QA checks fail
- ⚠️  Warns before stable release (requires confirmation)
- ✅ Creates annotated tags with changelog
- ✅ Marks beta releases as pre-release on GitHub

--- End Command ---
