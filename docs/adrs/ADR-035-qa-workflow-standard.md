# ADR-035: QA Workflow Standard - Comprehensive Quality at Speed

**Status:** Accepted
**Date:** 2026-01-21
**Version:** 1.0.0

## Context

AI agents need to iterate rapidly on code changes while maintaining top quality. This requires a QA system that:

1. **Validates comprehensively** - Every angle: unit tests, integration tests, architecture compliance, complexity analysis, security, formatting, types
2. **Runs fast** - Sub-1-minute target for full validation suite
3. **Enables autonomy** - AI agents can run checks without human intervention
4. **Provides clear signals** - Pass/fail, no ambiguity

**The Challenge:** Comprehensive validation is inherently slow. Traditional sequential execution of all checks takes 5-10 minutes. We need to innovate on HOW we execute to hit the speed target.

## Decision

We establish a **two-tier QA standard** optimized for both speed and completeness:

### Tier 1: `just check` - Fast Static Analysis

**Purpose:** Instant feedback on code quality
**Target:** <5 seconds
**Scope:** Static analysis only (no runtime)

```just
check:
    - lint (ruff check)
    - format validation (ruff format --check)
    - type checking (pyright)
```

**When to use:** During development, before every commit

### Tier 2: `just qa` - Comprehensive Validation

**Purpose:** Complete quality validation across ALL dimensions
**Target:** <1 minute (current: ~3 minutes, needs optimization)
**Scope:** Everything needed for production confidence

```just
qa:
    - lint (ruff check)
    - format (ruff format)
    - typecheck (pyright)
    - test (pytest - all tests)
    - dashboard-qa (frontend lint + build)
    - test-debt (no skipped/xfail without issues)
    - vsa-validate (architecture compliance)
```

**When to use:** Before commit (AI agents), before push (humans), in CI

## Quality Dimensions

The `qa` command validates across **7 critical dimensions**:

| Dimension | Check | Purpose | Current Time |
|-----------|-------|---------|--------------|
| **Code Quality** | `lint` | Style, complexity, best practices | ~5s |
| **Formatting** | `format` | Consistent style | ~3s |
| **Type Safety** | `typecheck` | Static type validation | ~10s |
| **Functionality** | `test` | Unit + integration tests | ~90s |
| **Frontend** | `dashboard-qa` | UI lint + build | ~30s |
| **Test Hygiene** | `test-debt` | No orphaned skips/xfails | ~2s |
| **Architecture** | `vsa-validate` | Bounded context compliance | ~5s |

**Total Current:** ~145s (2.4 minutes)
**Target:** <60s (1 minute)

## Performance Optimization Strategy

To achieve sub-1-minute validation, we need to innovate on execution:

### Phase 1: Parallel Execution (Immediate)

**Current:** Sequential execution
**Target:** Parallel execution of independent checks

```bash
# Run in parallel
lint & format & typecheck & test-debt & vsa-validate & dashboard-qa & wait
# Then tests (need clean state)
test
```

**Expected savings:** ~30-40s (checks that can run in parallel)

### Phase 2: Test Optimization (Short-term)

**Strategies:**
1. **Parallel test execution** - `pytest -n auto` for unit tests
2. **Smart test selection** - Only run tests affected by changes
3. **Test fixtures caching** - Reuse database fixtures across tests
4. **Fast test containers** - Pre-warmed containers for integration tests

**Target:** Reduce test time from 90s to 30s

### Phase 3: Infrastructure Innovation (Medium-term)

**Explorations:**
1. **Sidecar containers** - Pre-running services (DB, Redis) in background
2. **Incremental validation** - Cache validation results, only re-validate changes
3. **Distributed execution** - Split tests across multiple machines
4. **JIT compilation** - Compile Python to C for faster test execution

**Target:** Sub-20s for full validation suite

## Current State (v1.0.0)

### Commands

```just
# Fast static checks (~5s)
check: lint + format-check + typecheck

# Auto-fix variant
check-fix: lint --fix + format + typecheck

# Comprehensive QA (~2.4min)
qa: lint + format + typecheck + test + dashboard-qa + test-debt + vsa-validate

# QA with coverage (~3min)
qa-full: qa + coverage-report
```

### Performance Baseline

| Command | Current | Target | Status |
|---------|---------|--------|--------|
| `check` | 5s | <5s | ✅ At target |
| `qa` | 145s (2.4min) | <60s | 🟡 Warning zone |
| `qa-full` | 180s (3min) | <90s | 🟡 Warning zone |

### Performance Thresholds (Andon System)

We use a **three-zone performance model** inspired by lean manufacturing:

| Zone | Threshold | Signal | Action |
|------|-----------|--------|--------|
| 🟢 **Green** | <1 minute | ✅ Target performance | Continue normal operation |
| 🟡 **Yellow** | 1-2 minutes | ⚠️ Warning | Monitor, plan optimization |
| 🔴 **Red** | >2 minutes | 🚨 Andon | **STOP THE LINE** - Swarm on optimization |

**Critical rule:** If `qa` exceeds **10 minutes**, this is a **production-critical Andon signal**:
- ⛔ **STOP all feature work**
- 🚨 **All hands on deck** - Swarm on performance optimization
- 📊 **Root cause analysis** - What caused the regression?
- 🔧 **Fix immediately** - This is the bottleneck for ALL iteration

**Why 10 minutes is critical:**
- AI agents iterate 6 times/hour at 10min/iteration
- Humans lose context after 10min wait
- Productivity drops by 90% above this threshold
- The entire development pipeline is blocked

## AI Agent Integration

AI agents should use this workflow:

```python
# 1. During development iteration
run("just check")  # Fast feedback (<5s)
if failed:
    fix_issues()
    continue

# 2. Before proposing changes
run("just qa")  # Comprehensive validation
if failed:
    analyze_failures()
    fix_issues()
    retry

# 3. Success
propose_changes()
```

**Key principle:** AI agents should run `qa` before EVERY commit proposal to ensure zero manual validation needed.

## Rationale

### Why Two Tiers?

**Option 1 (Rejected):** Single `qa` command
- Problem: Too slow for development iteration (2.4min)
- Breaks flow state, encourages skipping checks

**Option 2 (Accepted):** Fast `check` + comprehensive `qa`
- `check` provides instant feedback during coding
- `qa` provides confidence before commit
- Clear mental model: "check syntax, then validate behavior"

### Why Sub-1-Minute Target?

**Research shows:**
- <10s: Immediate feedback, maintains flow
- 10-60s: Tolerable wait, agent can continue
- >60s: Context switch penalty, productivity loss

**For AI agents:**
- Fast validation enables rapid iteration
- Sub-1-minute means agents can try 10+ approaches per hour
- >1-minute creates bottleneck in agent velocity

### Why Comprehensive Validation?

**Human QA is expensive:**
- Manual code review: 30-60min per PR
- Manual testing: 1-2 hours per feature
- Missed issues: 5-10% escape rate

**Automated QA is cheap:**
- Runs in <1min
- Catches 95%+ of issues
- Zero human time required
- Consistent every time

**ROI:** Eliminate humans from the validation loop = 100x productivity gain for AI agents

## Success Metrics

### Quality Metrics (Must Maintain)

- ✅ 0% regression rate (no new bugs introduced)
- ✅ 95%+ code coverage
- ✅ 0 architecture violations
- ✅ 0 test debt (skips/xfails without issues)

### Performance Metrics (Must Improve)

**Current State:**
- 🟡 `qa` runtime: 145s (2.4min) → **Warning zone** → target <60s (green)
- 🟡 `qa-full` runtime: 180s (3min) → **Warning zone** → target <90s (green)
- ✅ `check` runtime: 5s → **Green zone** → maintain <5s

**Performance SLA:**
- `qa` must be <1 minute (green zone)
- `qa` at 1-2 minutes triggers optimization planning (yellow zone)
- `qa` at >2 minutes requires immediate optimization (red zone)
- `qa` at >10 minutes is **Andon signal** - stop all work, swarm on fix

### Adoption Metrics

- ⚪ AI agents run `qa` before 100% of commits
- ⚪ Humans run `qa` before 80%+ of pushes
- ⚪ CI runs `qa-full` on 100% of PRs

## Implementation Roadmap

### Phase 1: Documentation (Complete)
- [x] ADR-035 written
- [x] Commands documented in justfile
- [ ] Update docs/development/qa-workflow.md

### Phase 2: Parallel Execution (Week 1)
- [ ] Identify parallelizable checks
- [ ] Implement parallel execution script
- [ ] Measure performance improvement
- [ ] Target: 145s → 100s

### Phase 3: Test Optimization (Week 2-3)
- [ ] Enable `pytest -n auto` for unit tests
- [ ] Implement test selection (pytest-picked)
- [ ] Optimize test fixtures
- [ ] Target: 100s → 70s

### Phase 4: Infrastructure Innovation (Week 4-6)
- [ ] Sidecar container POC
- [ ] Incremental validation POC
- [ ] Measure impact
- [ ] Target: 70s → <60s

### Phase 5: Continuous Optimization (Ongoing)
- [ ] Monitor performance metrics
- [ ] Identify bottlenecks
- [ ] Iterate on optimization
- [ ] Target: Maintain <60s as codebase grows

## References

- **Incident:** PR #56 - Import errors not caught by incomplete QA
- **Research:** ["The Cost of Context Switching"](https://www.apa.org/news/press/releases/2006/07/multitasking)
- **Tools:**
  - [pytest-xdist](https://github.com/pytest-dev/pytest-xdist) - Parallel test execution
  - [pytest-picked](https://github.com/anapaulagomes/pytest-picked) - Smart test selection
  - [testcontainers](https://testcontainers.com/) - Fast integration tests

## Consequences

### Positive

✅ **Clear quality standard** - AI agents know exactly what to run
✅ **Fast enough** - 2.4min is tolerable, <1min is the goal
✅ **Comprehensive** - Validates all quality dimensions
✅ **Documented** - ADR + inline docs + developer guide
✅ **Measurable** - Clear metrics for success

### Negative

⚠️ **Still too slow** - 2.4min is 2.4x over target
⚠️ **Requires investment** - Optimization work needed
⚠️ **Infrastructure deps** - May need sidecar containers
⚠️ **Maintenance** - Performance can degrade over time

### Risks

🔴 **Performance regression** - Without monitoring, `qa` can slow down
🔴 **Andon threshold breach** - `qa` >10min stops all work
🟡 **Optimization complexity** - Parallel execution can be tricky
🟡 **False positives** - Aggressive caching may miss issues

### Monitoring & Alerting

**Required monitoring:**
1. **Track `qa` duration** - Every run logged with timestamp
2. **Alert on yellow zone** - Slack notification when `qa` >1min
3. **Escalate on red zone** - PagerDuty alert when `qa` >2min
4. **Trigger Andon** - Incident declared when `qa` >10min

**Dashboard metrics:**
- P50, P95, P99 `qa` runtime (weekly)
- Trend analysis (is performance degrading?)
- Breakdown by dimension (which check is slow?)
- Historical baseline (what's normal?)

## Versioning

**Version 1.0.0** (2026-01-21)
- Initial standard definition
- Two-tier workflow: check (fast) + qa (comprehensive)
- Performance targets established
- Optimization roadmap defined

**Future versions:**
- 1.1.0: Parallel execution implemented
- 1.2.0: Test optimization implemented
- 2.0.0: Sub-1-minute achieved
