# 🚀 START HERE

Welcome to the VSA QA Integration worktree! This is an isolated workspace for implementing VSA validation into the AEF QA pipeline.

## 📍 You Are Here

```
Worktree: agentic-engineering-framework_worktrees/20260118_vsa-qa-integration/
Branch:   feature/20260118-vsa-qa-integration
Mission:  Integrate VSA validation + fix 22 warnings
```

## 📚 Read These Files (In Order)

1. **`HANDOFF-VSA-QA-INTEGRATION.md`** ⭐ START HERE
   - Complete context and quick start guide
   - Essential info for new agents
   - Code examples and patterns

2. **`PROJECT-PLAN_20260118_VSA-QA-INTEGRATION.md`**
   - Full implementation plan with 9 milestones
   - Detailed task breakdown
   - Success criteria

3. **`vsa.yaml`**
   - VSA configuration
   - Bounded contexts defined
   - Validation rules

## ⚡ Quick Commands

### See Current State
```bash
# Run VSA validation (shows 22 warnings)
vsa validate

# Run QA checks
just qa-python

# Run tests
just test-unit
```

### Start Implementation
```bash
# Navigate to worktree
cd /Users/neural/Code/AgentParadise/agentic-engineering-framework_worktrees/20260118_vsa-qa-integration

# Open in your editor
cursor .
# or: code .
# or: claude
```

## 🎯 Your Mission

**Integrate VSA validation into AEF QA pipeline and fix all warnings**

### Phase 1: Integration (Milestone 2)
Add VSA to:
- `justfile` (vsa-validate target)
- `scripts/pre_merge_validation.py`
- `.claude/commands/qa/`

### Phase 2: Fix Warnings (Milestones 3-7)
Create 22 missing files:
- Handlers (11 files)
- Tests (11 files)

### Phase 3: Validate (Milestone 8)
- Run full QA suite
- Verify 0 warnings
- All tests pass

## 📊 Current Status

```
✅ Worktree created
✅ Project plan written
✅ Handoff document prepared
✅ /git/create-worktree command created
⏳ Ready for implementation
```

## 🔗 Important Files

**Must Edit:**
- `justfile` (line 391-393, 406, 411)
- `scripts/pre_merge_validation.py`
- `.claude/commands/qa/pre-commit-qa.md`
- `.claude/commands/qa/vsa-validate.md` (NEW)

**Will Create (~22 files):**
- `packages/aef-domain/src/aef_domain/contexts/*/Handler.py`
- `packages/aef-domain/src/aef_domain/contexts/*/test_*.py`

## ✅ Success = 0 Warnings

When you run `vsa validate`, you should see:

```
🔍 Validating VSA structure...
✅ Validation passed with 0 warnings
```

## 💡 Pro Tips

1. **Start with Milestone 2** - Get VSA in the pipeline first
2. **Use patterns** - Handlers and tests follow consistent templates
3. **Check adapters** - Logic may already exist, just needs wrapper
4. **Validate often** - Run `vsa validate` after each change
5. **Work incrementally** - One context at a time

## 🎬 Ready?

Read the HANDOFF document, then start with Milestone 2!

---

**Good luck! 🚀**
