# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Data Source:** `.topology/aef-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the AEF system.

**Total Relationships:** 28 events → 12 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_execution_started]
        e2[workflow_completed]
        e3[workflow_created]
        e4[workflow_failed]
        e5[agent_observation]
        e6[execution_paused]
        e7[artifact_created]
        e8[execution_resumed]
        e9[session_cost_finalized]
        e10[phase_completed]
    end

    subgraph projections["Projections"]
        p1[ArtifactListProjection]
        p2[DashboardMetricsProjection]
        p3[ExecutionCostProjection]
        p4[SessionCostProjection]
        p5[SessionListProjection]
        p6[TokenMetricsProjection]
        p7[ToolTimelineProjection]
        p8[WorkflowDetailProjection]
        p9[WorkflowExecutionDetailProjection]
        p10[WorkflowExecutionListProjection]
        p11[WorkflowListProjection]
        p12[WorkspaceMetricsProjection]
    end

    e5 --> p3
    e5 --> p4
    e2 --> p2
    e2 --> p9
    e2 --> p10
    e6 --> p9
    e6 --> p10
    e7 --> p2
    e7 --> p1
    e3 --> p2
    e3 --> p8
    e3 --> p11
    e1 --> p2
    e1 --> p9
    e1 --> p8
    e1 --> p10
    e1 --> p11
    e8 --> p9
    e8 --> p10
    e9 --> p3
    e9 --> p4
    e10 --> p9
    e10 --> p10
    e4 --> p2
    e4 --> p9
    e4 --> p10
```

---

## Statistics

- **Events with projections:** 28
- **Unique projections:** 12
- **Total event-to-projection mappings:** 48

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| workflow_execution_started | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowDetailProjection... | 5 |
| workflow_completed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| workflow_created | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |
| workflow_failed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| agent_observation | ExecutionCostProjection, SessionCostProjection | 2 |
| execution_paused | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| artifact_created | DashboardMetricsProjection, ArtifactListProjection | 2 |
| execution_resumed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| session_cost_finalized | ExecutionCostProjection, SessionCostProjection | 2 |
| phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |

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
vsa manifest --config vsa.yaml --output .topology/aef-manifest.json --include-domain
just docs-gen
```
