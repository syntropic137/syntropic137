# Metrics Implementation Status

> Last updated: 2025-12-17

## Current Phase: Phase 0-2 (Foundation)

---

## 📊 Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully implemented and in UI |
| ⚠️ | Data captured, not in UI |
| 🔧 | Partially implemented |
| ❌ | Not yet implemented |
| 📋 | Issue created |

---

## Agent KPIs Status

| Metric | Data Captured | Calculated | In UI | Notes |
|--------|---------------|------------|-------|-------|
| **Token Usage (Total)** | ✅ | ✅ | ✅ | SDK `ResultMessage.usage` |
| **Cost (Total)** | ✅ | ✅ | ✅ | SDK `total_cost_usd` |
| **Duration** | ✅ | ✅ | ✅ | Per session and workflow |
| **Tool Calls** | ✅ | ✅ | ✅ | Count and timeline |
| **Tool Success Rate** | ✅ | ❌ | ❌ | Data exists, need aggregation |
| **Per-Tool Tokens** | ❌ | ❌ | ❌ | 📋 [Issue #30](https://github.com/AgentParadise/agentic-engineering-framework/issues/30) |
| **Cognitive Efficiency** | 🔧 | ❌ | ❌ | Need commit tracking |
| **Semantic Durability** | ❌ | ❌ | ❌ | Need rework detection |
| **Rework Token Ratio** | ❌ | ❌ | ❌ | Need rework events |
| **Token Velocity** | ⚠️ | ❌ | ❌ | Can calculate from existing data |
| **Semantic Yield** | ❌ | ❌ | ❌ | Requires durability + rework |

## DORA Metrics Status

| Metric | Data Captured | Calculated | In UI | Notes |
|--------|---------------|------------|-------|-------|
| **Deployment Frequency** | ❌ | ❌ | ❌ | Need `deployment.completed` events |
| **Lead Time** | ❌ | ❌ | ❌ | Need commit→deploy tracking |
| **Change Failure Rate** | ❌ | ❌ | ❌ | Need deployment status |
| **MTTR** | ❌ | ❌ | ❌ | Need incident tracking |

## Session/Workflow Metrics Status

| Metric | Data Captured | Calculated | In UI | Notes |
|--------|---------------|------------|-------|-------|
| **Session Started** | ✅ | ✅ | ✅ | TimescaleDB |
| **Session Completed** | ✅ | ✅ | ✅ | TimescaleDB |
| **Session Duration** | ✅ | ✅ | ✅ | Calculated from events |
| **Workflow Started** | ✅ | ✅ | ✅ | Event Store |
| **Workflow Completed** | ✅ | ✅ | ✅ | Event Store |
| **Phase Progress** | ✅ | ✅ | ⚠️ | Basic display |
| **Workspace Path** | ✅ | ✅ | ❌ | Just added, needs UI |

## Tool Metrics Status

| Metric | Data Captured | Calculated | In UI | Notes |
|--------|---------------|------------|-------|-------|
| **Tool Started** | ✅ | ✅ | ✅ | Timeline |
| **Tool Completed** | ✅ | ✅ | ✅ | Timeline |
| **Tool Name** | ✅ | ✅ | ✅ | Bash, Write, Read, etc. |
| **Tool Duration** | ⚠️ | ❌ | ❌ | Can calculate from start/complete |
| **Tool Input Preview** | ✅ | ✅ | ✅ | "Show details" button |
| **Tool Output Preview** | 🔧 | 🔧 | ❌ | Partially captured |
| **Tool Estimated Tokens** | ❌ | ❌ | ❌ | 📋 Issue #30 |

## Milestone Metrics Status

| Metric | Data Captured | Calculated | In UI | Notes |
|--------|---------------|------------|-------|-------|
| **Milestone Started** | ❌ | ❌ | ❌ | Need milestone events |
| **Milestone Completed** | ❌ | ❌ | ❌ | Need milestone events |
| **Token Estimation Accuracy** | ❌ | ❌ | ❌ | Need estimates |
| **Deliverable Completion Rate** | ❌ | ❌ | ❌ | Need deliverable tracking |

---

## What We Can Calculate TODAY

With current data, we can calculate:

### From TimescaleDB (`agent_observations`)
```sql
-- Total tokens per session
SELECT session_id,
       SUM((data->>'input_tokens')::int) as input_tokens,
       SUM((data->>'output_tokens')::int) as output_tokens,
       MAX((data->>'total_cost_usd')::numeric) as cost
FROM agent_observations
WHERE observation_type = 'execution_completed'
GROUP BY session_id;

-- Tool usage breakdown
SELECT data->>'tool_name' as tool,
       COUNT(*) as call_count,
       COUNT(*) FILTER (WHERE data->>'success' = 'true') as success_count
FROM agent_observations
WHERE observation_type = 'tool_completed'
GROUP BY data->>'tool_name';

-- Session duration
SELECT session_id,
       MAX(time) - MIN(time) as duration
FROM agent_observations
GROUP BY session_id;
```

### From Event Store
```sql
-- Workflow completion rate
SELECT workflow_id,
       COUNT(*) FILTER (WHERE status = 'completed') as completed,
       COUNT(*) as total
FROM workflow_executions
GROUP BY workflow_id;
```

---

## Priority Implementation Order

### Phase 1 (Now)
1. ✅ Total tokens and cost
2. ✅ Tool call timeline
3. ⏳ Workspace path in UI
4. ⏳ Tool success rate aggregation

### Phase 2 (Next Sprint)
1. Per-tool token estimation (Issue #30)
2. Token velocity calculation
3. Tool duration calculation
4. Session duration breakdown

### Phase 3 (Future)
1. Commit tracking integration
2. Cognitive efficiency calculation
3. Rework detection
4. DORA metrics foundation

---

## Events We Need to Add

To fully implement all metrics, we need these events:

| Event | Purpose | Priority |
|-------|---------|----------|
| `code.committed` | Track commits for cognitive efficiency | High |
| `deployment.completed` | DORA deployment frequency | Medium |
| `rework.detected` | Semantic durability | Medium |
| `milestone.started` | Milestone tracking | Medium |
| `milestone.completed` | Milestone tracking | Medium |
| `incident.detected` | MTTR calculation | Low |
| `incident.resolved` | MTTR calculation | Low |

---

## Related Documents

- [Agentic Analytics KPIs](./agentic-analytics-kpis.md) - Full metric definitions
- [Analytics Event Reference](../../lib/agentic-primitives/docs/analytics-event-reference.md) - Event types
- [ADR-026: TimescaleDB for Observability](../adrs/ADR-026-timescaledb-observability.md)
