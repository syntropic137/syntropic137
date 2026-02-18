# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Data Source:** `.topology/syn-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the AEF system.

**Total Relationships:** 31 events → 13 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_execution_started]
        e2[workflow_completed]
        e3[workflow_failed]
        e4[workflow_created]
        e5[execution_cancelled]
        e6[execution_paused]
        e7[session_started]
        e8[session_cost_finalized]
        e9[artifact_created]
        e10[execution_resumed]
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
        p9[WorkflowDetailProjection]
        p10[WorkflowExecutionDetailProjection]
        p11[WorkflowExecutionListProjection]
        p12[WorkflowListProjection]
        p13[WorkspaceMetricsProjection]
    end

    e5 --> p10
    e5 --> p11
    e6 --> p10
    e6 --> p11
    e7 --> p2
    e7 --> p6
    e8 --> p3
    e8 --> p5
    e9 --> p2
    e9 --> p1
    e10 --> p10
    e10 --> p11
    e2 --> p2
    e2 --> p10
    e2 --> p11
    e1 --> p2
    e1 --> p10
    e1 --> p9
    e1 --> p11
    e1 --> p12
    e3 --> p2
    e3 --> p10
    e3 --> p11
    e4 --> p2
    e4 --> p9
    e4 --> p12
```

---

## Statistics

- **Events with projections:** 31
- **Unique projections:** 13
- **Total event-to-projection mappings:** 51

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| workflow_execution_started | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowDetailProjection... | 5 |
| workflow_completed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| workflow_failed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| workflow_created | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |
| execution_cancelled | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| execution_paused | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| session_started | DashboardMetricsProjection, SessionListProjection | 2 |
| session_cost_finalized | ExecutionCostProjection, SessionCostProjection | 2 |
| artifact_created | DashboardMetricsProjection, ArtifactListProjection | 2 |
| execution_resumed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |

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
