# 🎬 Complete Agentic Analytics - Metrics & KPIs Reference

## Overview

We're tracking two main categories:

- **DORA Metrics** - Industry-standard software delivery performance
- **Agent/Semantic Metrics** - AI agent efficiency and output quality

---

## DORA Metrics (Software Delivery Performance)

| Metric | What It Measures | Formula | Goal | How We Capture |
|--------|------------------|---------|------|----------------|
| **Deployment Frequency** | How often you ship to production | Deployments per time period | ↑ Higher is better | `deployment.completed` events |
| **Lead Time for Changes** | Time from commit to production | Time(commit → deploy) | ↓ Lower is better | `code.committed` → `deployment.completed` |
| **Change Failure Rate** | % of deployments that fail | Failed deploys / Total deploys × 100 | ↓ Lower is better | `deployment.completed` with status='failed' |
| **Mean Time to Restore (MTTR)** | Time to recover from failure | Time(incident detected → resolved) | ↓ Lower is better | `incident.detected` → `incident.resolved` |

### DORA Performance Levels

| Level | Deployment Frequency | Lead Time | Change Failure Rate | MTTR |
|-------|---------------------|-----------|---------------------|------|
| **Elite** | Multiple times per day | < 1 hour | < 5% | < 1 hour |
| **High** | Once per week to once per month | 1 day - 1 week | 5-10% | < 1 day |
| **Medium** | Once per month to once every 6 months | 1 week - 1 month | 10-15% | 1 day - 1 week |
| **Low** | Fewer than once every 6 months | > 1 month | > 15% | > 1 week |

---

## Agent KPIs (AI Agent Efficiency)

### Core Agent Metrics

| Metric | What It Measures | Formula | Goal | Events Used |
|--------|------------------|---------|------|-------------|
| **Cognitive Efficiency** | % of tokens that produced lasting work | Committed Tokens / Total Tokens | ↑ Higher (close to 1.0) | `agent_session.tokens_used`, `code.committed` |
| **Cost Efficiency** | Cost per unit of committed work | Cost / Committed Tokens | ↓ Lower is better | Token usage × pricing, commits |
| **Semantic Durability** | % of work that doesn't need rework | Retained Tokens / Committed Tokens | ↑ Higher (close to 1.0) | Track rework via file history |
| **Rework Token Ratio** | % of tokens spent on rework | Rework Tokens / Total Tokens | ↓ Lower is better | `rework.detected` events |
| **Token Velocity** | Speed of producing quality output | Quality Tokens / Hour | ↑ Higher is better | `agent_session` duration + tokens |
| **Semantic Yield** | Overall system efficiency | Retained Tokens / Total Tokens | ↑ Higher (close to 1.0) | Combines durability + rework |

### Detailed Formulas

```
Cognitive Efficiency = Committed Tokens / Total Tokens Used

Where:
- Total Tokens Used = All tokens from agent_session.tokens_used events
- Committed Tokens = Tokens in commits that made it to the codebase

Example: 10,000 total tokens, 8,500 in commits = 0.85 (85% efficiency)
```

```
Semantic Durability = Retained Tokens / Committed Tokens

Where:
- Committed Tokens = Tokens in initial commits
- Retained Tokens = Tokens that weren't reworked later

Example: 8,500 committed, 1,000 reworked = 7,500/8,500 = 0.88 (88% durability)
```

```
Rework Token Ratio = Rework Tokens / Total Tokens Used

Where:
- Rework Tokens = Tokens used to fix/change previously committed work
- Total Tokens = All tokens used

Example: 1,000 rework / 10,000 total = 0.10 (10% rework)
```

```
Token Velocity = (Committed Tokens × Quality Factor) / Hours

Where:
- Quality Factor = Tests passing, no immediate rework (0-1)
- Hours = Duration of agent session

Example: (8,500 tokens × 0.9 quality) / 2 hours = 3,825 tokens/hour
```

```
Semantic Yield = (Committed Tokens - Rework Tokens) / Total Tokens

Overall efficiency combining both durability and rework.

Example: (8,500 - 1,000) / 10,000 = 0.75 (75% yield)
```

### Additional Agent Metrics

| Metric | What It Measures | How to Calculate | Events Used |
|--------|------------------|------------------|-------------|
| **Attempts (Iterations)** | How many tries to get it right | Count of `agent_session.tokens_used` per milestone | Token usage events |
| **Presence (Context Use)** | How much context was used | Input tokens / Available context | Token usage events |
| **Size (Output Volume)** | How much code generated | Output tokens or lines of code | Token usage, commits |
| **Streak (Consistency)** | Consecutive successful milestones | Count milestones without rework | Milestone events |
| **Rework Percentage** | % of milestones needing rework | Reworked Milestones / Total Milestones | Rework detection |

---

## Milestone-Level Metrics

| Metric | What It Measures | Formula | Goal |
|--------|------------------|---------|------|
| **Token Estimation Accuracy** | How well we estimate | Actual Tokens / Estimated Tokens | ≈ 1.0 (±20%) |
| **Milestone Completion Time** | Time to finish milestone | Time(milestone.started → completed) | ↓ Lower is better |
| **Deliverable Completion Rate** | % of planned deliverables shipped | Delivered / Planned | 1.0 (100%) |
| **Success Criteria Hit Rate** | % of success criteria met | Met / Total Criteria | 1.0 (100%) |

---

## Workflow-Level Metrics

| Metric | What It Measures | How to Calculate |
|--------|------------------|------------------|
| **Workflow Lead Time** | Time to complete entire workflow | Time(workflow.started → completed) |
| **Phase Efficiency** | Time spent per phase | Duration per phase / Total duration |
| **Artifact Reuse** | How often artifacts are referenced | Reference count per artifact |
| **Parallel Efficiency** | How well parallelization works | Time saved via parallel milestones |

---

## Classification-Based Metrics

Track everything by classification (from your taxonomy):

| Classification | Metrics to Track |
|---------------|------------------|
| `feature` | Token velocity, commit count, time to deploy |
| `bug` | MTTR, rework ratio, fix time |
| `chore` | Token efficiency, completion time |
| `rework-correction` | Tokens wasted, original issue reference |
| `rework-omission` | Tokens needed, scope completeness |
| `refactor` | Before/after performance, test pass rate |
| `hotfix` | MTTR, deployment frequency spike |

---

## Key Questions Each Metric Answers

### DORA Metrics Answer:
- ✅ How fast can we ship features? (Deployment Frequency)
- ✅ How long does it take from code to production? (Lead Time)
- ✅ How often do our deployments break things? (Change Failure Rate)
- ✅ How quickly can we fix production issues? (MTTR)

### Agent Metrics Answer:
- ✅ How efficient is the agent at producing lasting work? (Cognitive Efficiency)
- ✅ How much work needs to be redone? (Rework Token Ratio)
- ✅ How stable is the agent's output? (Semantic Durability)
- ✅ How fast is the agent producing quality output? (Token Velocity)
- ✅ What's the overall ROI on agent token usage? (Semantic Yield)
- ✅ How accurate are our estimates? (Token Estimation Accuracy)

### Milestone Metrics Answer:
- ✅ Which milestones are problematic? (Completion time, rework rate)
- ✅ Are we estimating correctly? (Estimated vs actual tokens)
- ✅ What types of work are most efficient? (By classification)

---

## Dashboard Views

### Executive Dashboard

```
┌─────────────────────────────────────────┐
│ DORA Metrics (Last 30 Days)             │
├─────────────────────────────────────────┤
│ Deployment Frequency:  5.2/week  ↑      │
│ Lead Time:             2.3 days   ↓      │
│ Change Failure Rate:   8.5%       ↓      │
│ MTTR:                  3.2 hours  ↓      │
│                                          │
│ Performance Level: HIGH ⭐              │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Agent Efficiency (Last 30 Days)         │
├─────────────────────────────────────────┤
│ Cognitive Efficiency:   87%       ↑      │
│ Semantic Yield:         73%       →      │
│ Rework Token Ratio:     12%       ↓      │
│ Token Velocity:         3,200/hr  ↑      │
│                                          │
│ Agent Performance: GOOD ✓               │
└─────────────────────────────────────────┘
```

### Milestone Dashboard

```
┌──────────────────────────────────────────────────────────┐
│ Milestone Performance                                     │
├──────────────────────────────────────────────────────────┤
│ Milestone │ Est. Tokens │ Actual │ Efficiency │ Status   │
├──────────────────────────────────────────────────────────┤
│ M1a       │ 2,000       │ 2,100  │ 95%        │ ✅ Done   │
│ M1b       │ 1,500       │ 1,800  │ 83%        │ ✅ Done   │
│ M2        │ 2,500       │ 3,200  │ 78%        │ ✅ Done   │
│ M3        │ 1,800       │ 1,500  │ 120%       │ 🔄 Active│
└──────────────────────────────────────────────────────────┘

Average Efficiency: 94% (good!)
Total Tokens: 8,600 (vs 7,800 estimated)
```

### Trend Dashboard

```
Token Efficiency Over Time

100% │         ●
     │       ●   ●
 80% │     ●       ●
     │   ●           ●
 60% │ ●
     └─────────────────────
       M1  M2  M3  M4  M5

Rework Rate by Classification

feature:     8%  ████
bug:        15%  ███████
refactor:    3%  █
chore:       5%  ██
```

---

## SQL Queries for Each Metric

### Cognitive Efficiency

```sql
WITH token_totals AS (
  SELECT
    SUM((data->>'total_tokens')::int) as total_tokens
  FROM agent_observations
  WHERE observation_type = 'execution_completed'
    AND time > NOW() - INTERVAL '30 days'
),
committed_tokens AS (
  SELECT
    SUM((data->>'estimated_tokens')::int) as committed
  FROM events
  WHERE event_type = 'code.committed'
    AND timestamp > NOW() - INTERVAL '30 days'
)
SELECT
  committed::float / total_tokens as cognitive_efficiency
FROM token_totals, committed_tokens;
```

### Deployment Frequency

```sql
SELECT
  COUNT(*)::float / 30 as deployments_per_day
FROM events
WHERE event_type = 'deployment.completed'
  AND data->>'environment' = 'production'
  AND timestamp > NOW() - INTERVAL '30 days';
```

### Lead Time

```sql
WITH commits AS (
  SELECT
    data->>'commit_hash' as hash,
    timestamp as commit_time
  FROM events
  WHERE event_type = 'code.committed'
),
deploys AS (
  SELECT
    data->'commits' as commit_hashes,
    timestamp as deploy_time
  FROM events
  WHERE event_type = 'deployment.completed'
)
SELECT
  AVG(deploy_time - commit_time) as avg_lead_time
FROM commits c
JOIN deploys d ON d.commit_hashes @> to_jsonb(c.hash);
```

### Change Failure Rate

```sql
SELECT
  COUNT(*) FILTER (WHERE data->>'status' = 'failed')::float /
  COUNT(*) * 100 as change_failure_rate_pct
FROM events
WHERE event_type = 'deployment.completed'
  AND timestamp > NOW() - INTERVAL '30 days';
```

---

## Metric Priorities

### Phase 0-2 (Weeks 1-3): Track These First
- ✅ Commits per milestone
- ✅ Token usage per milestone (estimated)
- ✅ Milestone completion time

### Phase 3-4 (Weeks 4-5): Add These
- ✅ Token efficiency (estimated vs actual)
- ✅ Rework detection (basic)
- ✅ Classification distribution

### Phase 5+ (Week 6+): Add Full Suite
- ✅ All DORA metrics
- ✅ All Agent KPIs
- ✅ Trend analysis
- ✅ Predictive metrics

---

## Summary: What Matters Most

### For Agent Performance:
1. **Cognitive Efficiency** - Are tokens being used effectively?
2. **Rework Token Ratio** - How much work is wasted?
3. **Token Velocity** - How fast is quality output?

### For Software Delivery:
1. **Lead Time** - How fast from code to production?
2. **Deployment Frequency** - How often do we ship?
3. **Change Failure Rate** - How often do deploys break?

### For Project Planning:
1. **Token Estimation Accuracy** - Are estimates improving?
2. **Milestone Completion Time** - Are we on schedule?
3. **Parallel Efficiency** - Is parallelization working?

**Start with these 9 metrics, then expand from there!**
