---
description: Review implementation against project plan and verify completeness
argument-hint: <path-to-project-plan.md>
model: sonnet
allowed-tools: Read, Grep, Glob, Bash
---

# Review Implementation

Systematically review the implementation against the project plan to ensure all tasks are complete and the implementation matches the intended design.

## Variables

PLAN_PATH: $ARGUMENTS
STRICT_MODE: false

## Instructions

1. Read the project plan thoroughly
2. For each milestone/task, verify implementation exists
3. Check that implementation matches the plan's specifications
4. Flag any deviations (additions, omissions, changes)
5. Run pre-commit QA checks if all tasks are complete

## Workflow

### Phase 1: Plan Analysis
1. **Read Plan** - `cat $PLAN_PATH`
2. **Extract Tasks** - Identify all checkboxes `- [ ]` and `- [x]`
3. **Extract Files** - Note all file paths mentioned in the plan
4. **Extract Acceptance Criteria** - List expected outcomes

### Phase 2: Implementation Verification
For each task in the plan:

1. **Locate Implementation** - Find the files/code mentioned
2. **Verify Existence** - Confirm files exist: `ls -la <path>`
3. **Verify Content** - Check implementation matches plan
4. **Check Completeness** - All acceptance criteria met?

### Phase 3: Deviation Detection
1. **Additions** - Files/features not in plan (flag if significant)
2. **Omissions** - Planned items not implemented (⚠️ BLOCKER)
3. **Changes** - Implementation differs from plan (note why)

### Phase 4: QA Checkpoint

If implementation is complete:

1. **Verify QA Setup** - Ensure standardized commands exist:
   ```
   /qa-setup audit
   ```

2. **Run Pre-Commit QA** - Execute all checks:
   ```
   /pre-commit-qa
   ```

The QA checks are tool-agnostic and use whatever the project has configured:
- [ ] Format check passes
- [ ] Lint check passes
- [ ] Type check passes
- [ ] Tests pass
- [ ] Build succeeds (if applicable)

## Report

Generate a structured review report:

```markdown
## Implementation Review

**Plan:** $PLAN_PATH
**Date:** <current date>
**Reviewer:** Agent

---

### Milestone Status

| # | Milestone | Status | Notes |
|---|-----------|--------|-------|
| 1 | <name> | ✅/⚠️/❌ | <notes> |
| ... | ... | ... | ... |

---

### Task Verification

#### Milestone 1: <name>
- [x] Task 1.1 - <verified how>
- [x] Task 1.2 - <verified how>
- [ ] Task 1.3 - ⚠️ NOT FOUND: <details>

... (repeat for each milestone)

---

### Deviations Detected

#### ⚠️ Omissions (Blockers)
<list any missing implementations>

#### ℹ️ Additions (Non-blocking)
<list any extra implementations not in plan>

#### 🔄 Changes (Review needed)
<list any implementations that differ from plan>

---

### QA Checkpoint Results

| Check | Status | Details |
|-------|--------|---------|
| Types | ✅/❌ | <output summary> |
| Build | ✅/❌ | <output summary> |
| Lint | ✅/❌ | <output summary> |
| Tests | ✅/❌ | <pass/fail count> |

---

### Verdict

**Status:** ✅ READY TO COMMIT / ⚠️ NEEDS ATTENTION / ❌ BLOCKERS FOUND

**Summary:**
<1-2 sentence summary of review findings>

**Next Steps:**
- <action items if any>
```

## Examples

### Example 1: Reviewing a completed milestone
```
/review PROJECT-PLAN_20251129_prompts-tools-system.md
```

### Example 2: Strict mode (fail on any deviation)
```
STRICT_MODE=true /review PROJECT-PLAN_20251129_prompts-tools-system.md
```

