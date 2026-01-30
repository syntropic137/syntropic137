# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Data Source:** `.topology/aef-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the AEF system.

**Total Relationships:** 31 events → 13 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_execution_started]
        e2[workflow_failed]
        e3[workflow_created]
        e4[workflow_completed]
        e5[execution_cancelled]
        e6[agent_observation]
        e7[artifact_created]
        e8[session_started]
        e9[phase_completed]
        e10[phase_started]
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
    e2 --> p2
    e2 --> p10
    e2 --> p11
    e6 --> p3
    e6 --> p5
    e7 --> p2
    e7 --> p1
    e8 --> p2
    e8 --> p6
    e1 --> p2
    e1 --> p10
    e1 --> p9
    e1 --> p11
    e1 --> p12
    e3 --> p2
    e3 --> p9
    e3 --> p12
    e9 --> p10
    e9 --> p11
    e10 --> p2
    e10 --> p10
    e4 --> p2
    e4 --> p10
    e4 --> p11
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
| workflow_failed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| workflow_created | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |
| workflow_completed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| execution_cancelled | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| agent_observation | ExecutionCostProjection, SessionCostProjection | 2 |
| artifact_created | DashboardMetricsProjection, ArtifactListProjection | 2 |
| session_started | DashboardMetricsProjection, SessionListProjection | 2 |
| phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| phase_started | DashboardMetricsProjection, WorkflowExecutionDetailProjection | 2 |

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
