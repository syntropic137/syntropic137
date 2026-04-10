# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Data Source:** `.topology/syn-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the Syn137 system.

**Total Relationships:** 57 events → 22 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_execution_started]
        e2[workflow_failed]
        e3[workflow_completed]
        e4[phase_completed]
        e5[trigger_fired]
        e6[workflow_template_created]
        e7[phase_started]
        e8[workflow_interrupted]
        e9[execution_cancelled]
        e10[agent_observation]
    end

    subgraph projections["Projections"]
        p1[ArtifactListProjection]
        p2[DashboardMetricsProjection]
        p3[ExecutionCostProjection]
        p4[ExecutionTodoProjection]
        p5[InstallationProjection]
        p6[RepoCorrelationProjection]
        p7[RepoCostProjection]
        p8[RepoHealthProjection]
        p9[RepoProjection]
        p10[SessionCostProjection]
        p11[SessionListProjection]
        p12[SystemProjection]
        p13[TokenMetricsProjection]
        p14[ToolTimelineProjection]
        p15[TriggerHistoryProjection]
    end

    e10 --> p10
    e10 --> p3
    e5 --> p6
    e5 --> p15
    e6 --> p2
    e2 --> p8
    e2 --> p7
    e2 --> p4
    e2 --> p2
    e1 --> p6
    e1 --> p4
    e1 --> p2
    e7 --> p2
    e8 --> p4
    e9 --> p4
    e3 --> p8
    e3 --> p7
    e3 --> p4
    e3 --> p2
    e4 --> p4
```

---

## Statistics

- **Events with projections:** 57
- **Unique projections:** 22
- **Total event-to-projection mappings:** 92

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| workflow_execution_started | RepoCorrelationProjection, WorkflowExecutionDetailProjection, WorkflowDetailProjection... | 7 |
| workflow_failed | RepoHealthProjection, RepoCostProjection, WorkflowExecutionDetailProjection... | 6 |
| workflow_completed | RepoHealthProjection, RepoCostProjection, WorkflowExecutionDetailProjection... | 6 |
| phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, ExecutionTodoProjection... | 4 |
| trigger_fired | RepoCorrelationProjection, TriggerHistoryProjection, TriggerRuleProjection | 3 |
| workflow_template_created | WorkflowDetailProjection, WorkflowListProjection, DashboardMetricsProjection | 3 |
| phase_started | WorkflowExecutionDetailProjection, WorkflowPhaseMetricsProjection, DashboardMetricsProjection | 3 |
| workflow_interrupted | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, ExecutionTodoProjection | 3 |
| execution_cancelled | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, ExecutionTodoProjection | 3 |
| agent_observation | SessionCostProjection, ExecutionCostProjection | 2 |

---

## Related Documentation

- [Event Architecture](./event-architecture.md) - Domain vs Observability events
- [Infrastructure Data Flow](./infrastructure-data-flow.md)

---

🤖 **This file is auto-generated** - Do not edit manually. To regenerate:

```bash
just docs-gen
```

Or regenerate the manifest first:

```bash
vsa manifest --config vsa.yaml --output .topology/syn-manifest.json --include-domain
just docs-gen
```
