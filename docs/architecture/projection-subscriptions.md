# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Data Source:** `.topology/syn-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the Syn137 system.

**Total Relationships:** 36 events → 16 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_execution_started]
        e2[workflow_completed]
        e3[workflow_template_created]
        e4[phase_started]
        e5[workflow_failed]
        e6[phase_completed]
        e7[trigger_fired]
        e8[session_cost_finalized]
        e9[session_summary]
        e10[artifact_created]
    end

    subgraph projections["Projections"]
        p1[ArtifactListProjection]
        p2[DashboardMetricsProjection]
        p3[ExecutionCostProjection]
        p4[InstallationProjection]
        p5[SessionCostProjection]
        p6[SessionListProjection]
        p7[TokenMetricsProjection]
        p8[ToolTimelineProjection]
        p9[TriggerHistoryProjection]
        p10[TriggerRuleProjection]
        p11[WorkflowDetailProjection]
        p12[WorkflowExecutionDetailProjection]
        p13[WorkflowExecutionListProjection]
        p14[WorkflowListProjection]
        p15[WorkflowPhaseMetricsProjection]
    end

    e2 --> p12
    e2 --> p13
    e2 --> p2
    e7 --> p9
    e7 --> p10
    e8 --> p5
    e8 --> p3
    e1 --> p12
    e1 --> p11
    e1 --> p13
    e1 --> p14
    e1 --> p2
    e9 --> p5
    e9 --> p3
    e10 --> p1
    e10 --> p2
    e3 --> p11
    e3 --> p14
    e3 --> p2
    e4 --> p12
    e4 --> p15
    e4 --> p2
    e5 --> p12
    e5 --> p13
    e5 --> p2
    e6 --> p12
    e6 --> p13
    e6 --> p15
```

---

## Statistics

- **Events with projections:** 36
- **Unique projections:** 16
- **Total event-to-projection mappings:** 59

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| workflow_execution_started | WorkflowExecutionDetailProjection, WorkflowDetailProjection, WorkflowExecutionListProjection... | 5 |
| workflow_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, DashboardMetricsProjection | 3 |
| workflow_template_created | WorkflowDetailProjection, WorkflowListProjection, DashboardMetricsProjection | 3 |
| phase_started | WorkflowExecutionDetailProjection, WorkflowPhaseMetricsProjection, DashboardMetricsProjection | 3 |
| workflow_failed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, DashboardMetricsProjection | 3 |
| phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, WorkflowPhaseMetricsProjection | 3 |
| trigger_fired | TriggerHistoryProjection, TriggerRuleProjection | 2 |
| session_cost_finalized | SessionCostProjection, ExecutionCostProjection | 2 |
| session_summary | SessionCostProjection, ExecutionCostProjection | 2 |
| artifact_created | ArtifactListProjection, DashboardMetricsProjection | 2 |

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
