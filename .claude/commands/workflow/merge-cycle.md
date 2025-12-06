---
description: Full merge cycle orchestrator with QA, CI, and review gates
argument-hint: [target-branch] [qa-retries] [ci-retries] [review-rounds]
model: sonnet
allowed-tools: Read, Bash
---

# Merge Cycle

Orchestrate the complete merge workflow from local changes to merged PR.

## Purpose

*Level 3 (Control Flow)*

Automate the full development cycle with configurable retry limits:
- QA checks with auto-fix
- Conventional commits
- Push with CI monitoring
- Review comment handling
- Final merge

## Variables

TARGET_BRANCH: $1 || "develop"     # Branch to merge into
QA_MAX_RETRIES: $2 || 3            # Max QA retry attempts
CI_MAX_RETRIES: $3 || 2            # Max CI retry attempts
REVIEW_MAX_ROUNDS: $4 || 2         # Max review/fix rounds
AUTO_FIX_STYLE: $5 || true         # Auto-fix style issues
MERGE_METHOD: $6 || "squash"       # squash, merge, or rebase

## Instructions

- Each phase has a retry limit to prevent infinite loops
- On phase failure, report status and exit with actionable guidance
- Track current retry counts across phases
- Security and logic issues (🔴 MUST_FIX) are always blocking
- Style issues (🟢 OPTIONAL) are addressed based on AUTO_FIX_STYLE
- Exit 0 on successful merge, exit 1 on any blocking failure

## Workflow

### Phase 1: QA Gate

Run QA checks with retry logic.

**Loop up to QA_MAX_RETRIES times:**

1. Run `/qa/pre-commit-qa --fix`
2. If all checks pass → proceed to Phase 2
3. If checks fail:
   - Review failures
   - Attempt auto-fix where possible
   - Increment retry counter
   - If retries exhausted → ABORT with detailed report
   - Otherwise → retry

```
QA_ATTEMPT = 0
while QA_ATTEMPT < QA_MAX_RETRIES:
    QA_ATTEMPT += 1
    print(f"=== QA Attempt {QA_ATTEMPT}/{QA_MAX_RETRIES} ===")

    result = run("/qa/pre-commit-qa --fix")

    if result.passed:
        break
    elif QA_ATTEMPT >= QA_MAX_RETRIES:
        ABORT("QA failed after {QA_MAX_RETRIES} attempts")
        print("Manual intervention required. Fix remaining issues and restart.")
```

**On Success:** Continue to Phase 2
**On Failure:** Report issues, suggest fixes, exit 1

---

### Phase 2: Commit & Push

Create commit and push to remote.

1. Run `/devops/commit` to create conventional commit
2. Run `/devops/push` to push and wait for CI

```
run("/devops/commit")
run("/devops/push")
```

**On Success:** Continue to Phase 3
**On Failure:** Report error, exit 1

---

### Phase 3: CI Gate

Wait for CI and handle failures.

**Loop up to CI_MAX_RETRIES times:**

1. Wait for CI completion (handled by `/devops/push`)
2. If CI passes → proceed to Phase 4
3. If CI fails:
   - Pull latest changes (in case of merge conflicts)
   - Increment retry counter
   - If retries exhausted → ABORT
   - Otherwise → return to Phase 1

```
CI_ATTEMPT = 0
while CI_ATTEMPT < CI_MAX_RETRIES:
    CI_ATTEMPT += 1
    print(f"=== CI Attempt {CI_ATTEMPT}/{CI_MAX_RETRIES} ===")

    # CI was already checked by /devops/push
    # If we're here in a retry, pull and re-run QA

    if CI_ATTEMPT > 1:
        run("git pull origin {current_branch}")
        goto Phase 1  # Re-run full QA cycle

    if CI_PASSED:
        break
    elif CI_ATTEMPT >= CI_MAX_RETRIES:
        ABORT("CI failed after {CI_MAX_RETRIES} attempts")
```

**On Success:** Continue to Phase 4
**On Failure:** Report CI errors, suggest fixes, exit 1

---

### Phase 4: Review Gate

Fetch and address review comments.

**Loop up to REVIEW_MAX_ROUNDS times:**

1. Run `/review/fetch` to get comments
2. If no comments → proceed to Phase 5
3. If comments exist:
   - Run `/review/prioritize` to categorize
   - Fix all 🔴 MUST_FIX issues (required)
   - Fix 🟡 SHOULD_FIX issues (recommended)
   - If AUTO_FIX_STYLE: fix 🟢 OPTIONAL issues
   - Increment round counter
   - Return to Phase 1 (re-run full cycle with fixes)

```
REVIEW_ROUND = 0
while REVIEW_ROUND < REVIEW_MAX_ROUNDS:
    REVIEW_ROUND += 1
    print(f"=== Review Round {REVIEW_ROUND}/{REVIEW_MAX_ROUNDS} ===")

    comments = run("/review/fetch")

    if not comments.has_actionable_items:
        break

    prioritized = run("/review/prioritize", comments)

    # Fix issues by priority
    fix(prioritized.MUST_FIX)    # Always fix
    fix(prioritized.SHOULD_FIX)  # Fix if time permits

    if AUTO_FIX_STYLE:
        fix(prioritized.OPTIONAL)

    # Re-run full cycle with fixes
    goto Phase 1
```

**On Success:** Continue to Phase 5
**On Max Rounds:** Report remaining comments, suggest manual review, exit 1

---

### Phase 5: Merge & Cleanup

Complete the merge.

1. Final CI verification (should already be green)
2. Run `/devops/merge --target ${TARGET_BRANCH} --method ${MERGE_METHOD}`
3. Report success

```
run(f"/devops/merge {TARGET_BRANCH} {MERGE_METHOD}")
print("✅ Successfully merged!")
```

**On Success:** Exit 0
**On Failure:** Report merge error, exit 1

---

## Report

### Success Report

```markdown
## ✅ Merge Cycle Complete

**Target:** ${TARGET_BRANCH}
**Method:** ${MERGE_METHOD}

### Phase Summary

| Phase | Attempts | Status |
|-------|----------|--------|
| QA | {QA_ATTEMPT}/{QA_MAX_RETRIES} | ✅ Passed |
| Commit | 1/1 | ✅ Created |
| Push | 1/1 | ✅ Pushed |
| CI | {CI_ATTEMPT}/{CI_MAX_RETRIES} | ✅ Passed |
| Review | {REVIEW_ROUND}/{REVIEW_MAX_ROUNDS} | ✅ Resolved |
| Merge | 1/1 | ✅ Merged |

### Issues Addressed

| Priority | Count | Action |
|----------|-------|--------|
| 🔴 Critical | X | Fixed |
| 🟡 Important | X | Fixed |
| 🟢 Style | X | {Fixed / Skipped} |

### Result

**PR merged to ${TARGET_BRANCH}!**

Current commit: <hash> <message>
```

### Failure Report

```markdown
## ❌ Merge Cycle Aborted

**Phase:** {failed_phase}
**Attempts:** {attempts}/{max_attempts}

### Failure Details

{specific error information}

### Remaining Issues

{list of unresolved issues}

### To Resume

1. Fix the issues listed above
2. Run `/workflow/merge-cycle ${TARGET_BRANCH}` again

### Manual Override

If you need to bypass checks:
- Skip QA: Fix issues manually, commit, push
- Skip Review: Address comments, request re-review
- Force merge: `gh pr merge --admin` (requires permissions)
```

## Examples

### Example 1: Default merge to develop
```
/workflow/merge-cycle
```
Uses all defaults: develop, 3 QA retries, 2 CI retries, 2 review rounds.

### Example 2: Merge to main with strict limits
```
/workflow/merge-cycle main 2 1 1
```
Merge to main, fewer retries for faster failure.

### Example 3: Thorough review cycle
```
/workflow/merge-cycle develop 5 3 3
```
More retries for complex changes.

### Example 4: Skip style fixes
```
/workflow/merge-cycle develop 3 2 2 false
```
Don't auto-fix optional style issues.

## Dependencies

This workflow orchestrates these commands:
- `/qa/pre-commit-qa` - QA checks
- `/devops/commit` - Create commits
- `/devops/push` - Push and wait for CI
- `/review/fetch` - Get review comments
- `/review/prioritize` - Categorize comments
- `/devops/merge` - Final merge

## Error Handling

| Error | Behavior |
|-------|----------|
| QA max retries | Abort, list remaining issues |
| CI max retries | Abort, show CI errors |
| Review max rounds | Abort, list unresolved comments |
| Merge conflict | Abort, instructions to resolve |
| Network error | Retry once, then abort |
| Permission denied | Abort, suggest admin help |
