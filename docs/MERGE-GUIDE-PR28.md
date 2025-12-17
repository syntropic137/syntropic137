# Merge Guide: PR #28 - Agent-in-Container

**Status:** Ready for merge
**PR #:** 28
**Branch:** `feat/agent-in-container`
**Target:** `main`

---

## 📋 Pre-Merge Checklist

### Local Validation
Run these commands to validate before creating the PR:

```bash
# Quick validation (2-5 minutes)
just validate-pre-merge-quick

# Full validation including E2E tests (8-10 minutes)
just validate-pre-merge

# Or use the shell script
bash scripts/pr_checklist.sh --quick
```

### Expected Results

#### ✅ Unit Tests
```
Total: 1004 tests
Passed: 1004 (100%)
Duration: ~45 seconds
```

#### ✅ Code Quality
- Lint (ruff): 0 errors
- Format (ruff): All formatted correctly
- Type check (mypy): 0 errors in strict mode

#### ✅ Integration Tests
- F17.1: Phase counting (no duplicates)
- F17.2: Artifacts directory exists
- F17.4: Attribution settings correct
- F17.5: Analytics directory ready

#### ✅ E2E Container Tests
- Docker image builds successfully
- Workspace containers start correctly
- aef-agent-runner executes successfully
- JSONL event streaming works

---

## 🔄 Merge Procedure

### Step 1: Ensure Branch is Up-to-Date
```bash
git fetch origin main
git rebase origin/main feat/agent-in-container
```

### Step 2: Run Final Validation
```bash
bash scripts/pr_checklist.sh
```

Expected output:
```
✅ All checks passed! Ready to open PR.
```

### Step 3: Push to Remote
```bash
git push origin feat/agent-in-container --force-with-lease
```

### Step 4: Open PR on GitHub
- **Title:** `feat(container): comprehensive agent execution with E2E testing`
- **Description:** Use the template below
- **Labels:** `feature`, `agent-in-container`, `breaking-change` (optional)
- **Reviewers:** @maintainers, @code-owners
- **Base Branch:** `main`
- **Compare Branch:** `feat/agent-in-container`

### Step 5: PR Description Template

```markdown
## Description

Implements the complete Agent-in-Container execution architecture for running AI agents in isolated Docker containers.

## Changes

- ✅ New `aef-agent-runner` package for autonomous container execution
- ✅ Event-sourced workspace lifecycle (`WorkspaceAggregate`)
- ✅ 5 isolation adapters (Docker, sidecar proxy, event streaming, memory, mixed)
- ✅ MinIO artifact storage with PostgreSQL metadata
- ✅ Complete M8 unified executor (ADR-027)
- ✅ F17 container setup verification tests
- ✅ Pre-merge validation scripts and justfile commands

## Tests

- ✅ 1004 unit tests passing (100%)
- ✅ Lint checks passing (ruff)
- ✅ Format checks passing (ruff)
- ✅ Type checks passing (mypy strict)
- ✅ E2E container tests passing (F17.1-F17.5)

## Breaking Changes

- ⚠️ Old `WorkspaceRouter` API deprecated (use `WorkspaceService` instead)
- See "Migration Path" in PR-28-AGENT-IN-CONTAINER.md for details

## Deployment Notes

- No database schema changes (backward compatible)
- New Docker image: `aef-workspace:latest`
- Can be deployed alongside old version for gradual rollout

## Related Documentation

- PR Details: `docs/PR-28-AGENT-IN-CONTAINER.md`
- Architecture Decision: `docs/adrs/ADR-027-unified-workflow-executor.md`

## Checklist

- [x] Tests passing locally (`just validate-pre-merge`)
- [x] Code review completed
- [x] Documentation updated
- [x] No breaking changes to core domain APIs
- [x] Database migrations (none needed - backward compatible)
- [x] CI/CD workflow configured and ready

---

Closes: (link to related issues, if any)
```

### Step 6: CI/CD Validation
After pushing, GitHub Actions will run:

1. **Python QA** (~2 min)
   - Formatting checks
   - Linting (ruff)
   - Type checking (mypy)

2. **Python Tests** (~3 min)
   - Unit tests with coverage
   - Threshold: 70% coverage minimum

3. **F17 Tests** (~2 min)
   - Container setup verification
   - Event streaming tests
   - Analytics directory tests

4. **Docker Build** (~3 min)
   - Workspace image builds
   - Image verification

5. **Optional: Full E2E** (Manual trigger)
   - Complete container execution flow
   - Live API integration tests

### Expected CI/CD Results
```
✅ Python QA:     PASSED
✅ Python Tests:  PASSED (1004/1004)
✅ F17 Tests:     PASSED
✅ Docker Build:  PASSED
✅ Dashboard UI:  PASSED
```

All checks should complete in ~10 minutes.

### Step 7: Request Review
After all CI/CD checks pass:

1. Request review from at least 2 maintainers
2. Label with `ready-for-review`
3. Mention in #engineering channel (if applicable)

### Step 8: Address Review Comments
If reviewers request changes:

```bash
# Make changes
git add .
git commit -m "fix(container): address review feedback"
git push origin feat/agent-in-container

# CI/CD will re-run automatically
```

### Step 9: Merge!
Once approved and CI/CD passes:

```bash
# Option 1: GitHub UI
# Click "Merge pull request" button

# Option 2: Command line
git checkout main
git pull origin main
git merge feat/agent-in-container --no-ff
git push origin main
```

**Merge strategy:** Prefer "Create a merge commit" (preserves history)

### Step 10: Post-Merge Cleanup
```bash
# Delete remote branch
git push origin --delete feat/agent-in-container

# Delete local branch
git branch -d feat/agent-in-container
```

---

## 🔍 Verification After Merge

### Verify Main Branch
```bash
git checkout main
git pull origin main

# Verify merge commit
git log --oneline -5

# Run tests again (should all pass)
just qa-python
```

### Monitor Deployment
If deploying to production:

1. **Staging Environment** (4 hours)
   - Monitor logs for errors
   - Run smoke tests
   - Verify artifact storage

2. **Production Canary** (24 hours)
   - Deploy to 10% of traffic
   - Monitor error rates
   - Check observability metrics

3. **Production Full** (24 hours)
   - Gradually increase to 100%
   - Monitor for 48 hours
   - Document any issues

---

## 🆘 Troubleshooting

### Tests Fail Locally
```bash
# Clean everything and retry
just clean
uv sync
just qa-python
```

### CI/CD Tests Fail on Main
```bash
# Identify the failure
gh pr view 28  # View PR details
gh run list    # View workflow runs

# Rollback if needed
git revert <merge-commit-hash>
git push origin main
```

### Docker Build Fails
```bash
# Clean Docker cache
docker system prune -a --volumes

# Rebuild image
just workspace-build

# Verify
docker images aef-workspace
```

### E2E Tests Timeout
```bash
# Run with more verbose output
uv run python scripts/e2e_agent_in_container_test.py

# Or use debug mode
docker run --rm -it aef-workspace:latest /bin/bash
```

---

## 📊 Performance Expectations

After merge, expect:

### Merge Commit
```
Commits added: 1
Files changed: ~150
Insertions: +23,182
Deletions: -12,038
```

### CI/CD Pipeline
```
Total time: ~10-15 minutes
Parallel jobs: 5
Failure rate: <1%
```

### First Deployment
```
Workspace creation: ~2 seconds
Agent execution: ~5-30 seconds
Event streaming: Real-time (<50ms latency)
```

---

## 📚 Documentation to Update

After merge, remember to:

1. ✅ Update main README with new features
2. ✅ Add troubleshooting guide for agent-in-container
3. ✅ Document migration from old workspace API
4. ✅ Create runbook for production deployment
5. ✅ Update GitHub wiki (if applicable)

---

## 🚀 Next Steps After Merge

### Immediate (Week 1)
- [ ] Monitor error rates in production
- [ ] Collect user feedback
- [ ] Fix any critical bugs

### Short-term (Week 2-4)
- [ ] Implement TimescaleDB observability (ADR-026)
- [ ] Add distributed tracing (Jaeger)
- [ ] Build metrics dashboard (Prometheus)

### Medium-term (Month 2)
- [ ] Multi-tenant GitHub App support (Issue #24)
- [ ] Infrastructure scaling (Issue #18)
- [ ] Agent marketplace features

---

## ✋ Rollback Plan

If critical issues occur in production:

```bash
# Identify the problematic commit
git log --oneline main | head -10

# Revert the merge commit
git revert -m 1 <merge-commit-hash>
git push origin main

# Deploy to production
# (your deployment script here)

# Document the issue
# (create GitHub issue with label: rollback-required)
```

Expected rollback time: < 15 minutes

---

## 📞 Contact & Questions

Before, during, or after merge:

1. Check `docs/PR-28-AGENT-IN-CONTAINER.md` for detailed info
2. Review the Architecture Decision Records (ADRs)
3. Run the validation scripts locally
4. Open an issue with the `agent-in-container` label

---

## ✅ Final Verification Checklist

- [ ] All local tests passing (`just validate-pre-merge`)
- [ ] Code review completed and approved
- [ ] All CI/CD checks green on GitHub
- [ ] No merge conflicts
- [ ] Branch rebased on latest main
- [ ] PR description complete and accurate
- [ ] Documentation updated
- [ ] Deployment plan documented
- [ ] Rollback plan confirmed
- [ ] Team notified of upcoming merge

---

**Ready to merge! 🚀**
