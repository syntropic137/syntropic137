# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-regen` to update

**Data Source:** `.topology/syn-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the Syn137 system.

**Total Relationships:** 82 events → 28 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_failed]
        e2[workflow_completed]
        e3[workflow_execution_started]
        e4[execution_cancelled]
        e5[phase_completed]
        e6[workflow_interrupted]
        e7[next_phase_ready]
        e8[trigger_fired]
        e9[workflow_template_created]
        e10[workflow_template_updated]
    end

    subgraph projections["Projections"]
        p1[ArtifactListProjection]
        p2[ClaudePluginLockProjection]
        p3[DashboardMetricsProjection]
        p4[EvalListProjection]
        p5[ExecutionCostProjection]
        p6[ExecutionTodoProjection]
        p7[FailureStreakProjection]
        p8[GlobalClaudePluginsProjection]
        p9[InstallationProjection]
        p10[RepoCorrelationProjection]
        p11[RepoCostProjection]
        p12[RepoHealthProjection]
        p13[RepoProjection]
        p14[SessionCostProjection]
        p15[SessionListProjection]
    end

    e4 --> p6
    e7 --> p6
    e5 --> p6
    e8 --> p10
    e2 --> p6
    e2 --> p7
    e2 --> p11
    e2 --> p12
    e3 --> p6
    e3 --> p10
    e1 --> p6
    e1 --> p7
    e1 --> p11
    e1 --> p12
    e6 --> p6
    e9 --> p3
    e10 --> p3
```

---

## Statistics

- **Events with projections:** 82
- **Unique projections:** 28
- **Total event-to-projection mappings:** 130

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| workflow_failed | ExecutionTodoProjection, FailureStreakProjection, RepoCostProjection... | 7 |
| workflow_completed | ExecutionTodoProjection, FailureStreakProjection, RepoCostProjection... | 6 |
| workflow_execution_started | ExecutionTodoProjection, RepoCorrelationProjection, WorkflowDetailProjection... | 6 |
| execution_cancelled | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| phase_completed | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| workflow_interrupted | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| next_phase_ready | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| trigger_fired | RepoCorrelationProjection, TriggerHistoryProjection, TriggerRuleProjection | 3 |
| workflow_template_created | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |
| workflow_template_updated | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |

---

## Related Documentation

- [Event Architecture](./event-architecture.md) - Domain vs Observability events
- [Infrastructure Data Flow](./infrastructure-data-flow.md)

---

🤖 **This file is auto-generated** - Do not edit manually. To regenerate:

```bash
just docs-regen
```
