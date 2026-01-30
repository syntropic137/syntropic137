# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Last Generated:** 2026-01-29 16:11:18
**Data Source:** `.topology/aef-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the AEF system.

**Total Relationships:** 37 events → 13 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[idEvent]
        e2[workflow_execution_startedEvent]
        e3[workflow_createdEvent]
        e4[workflow_completedEvent]
        e5[workflow_failedEvent]
        e6[phase_startedEvent]
        e7[phase_completedEvent]
        e8[artifact_createdEvent]
        e9[session_completedEvent]
        e10[session_startedEvent]
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

    e3 --> p2
    e3 --> p2
    e3 --> p9
    e3 --> p9
    e3 --> p12
    e3 --> p12
    e4 --> p2
    e4 --> p2
    e4 --> p10
    e4 --> p10
    e4 --> p11
    e4 --> p11
    e6 --> p2
    e6 --> p2
    e6 --> p10
    e6 --> p10
    e7 --> p10
    e7 --> p10
    e7 --> p11
    e7 --> p11
    e8 --> p2
    e8 --> p2
    e8 --> p1
    e8 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p1
    e1 --> p3
    e1 --> p3
    e1 --> p3
    e1 --> p3
    e1 --> p3
    e1 --> p5
    e1 --> p5
    e1 --> p5
    e1 --> p5
    e1 --> p5
    e1 --> p5
    e1 --> p5
    e1 --> p5
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p10
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p11
    e1 --> p7
    e1 --> p7
    e1 --> p8
    e1 --> p8
    e1 --> p13
    e1 --> p6
    e1 --> p6
    e1 --> p6
    e1 --> p6
    e1 --> p4
    e1 --> p4
    e1 --> p4
    e1 --> p4
    e9 --> p2
    e9 --> p2
    e9 --> p6
    e9 --> p6
    e2 --> p2
    e2 --> p2
    e2 --> p10
    e2 --> p10
    e2 --> p9
    e2 --> p9
    e2 --> p11
    e2 --> p11
    e2 --> p12
    e2 --> p12
    e10 --> p2
    e10 --> p2
    e10 --> p6
    e10 --> p6
    e5 --> p2
    e5 --> p2
    e5 --> p10
    e5 --> p10
    e5 --> p11
    e5 --> p11
```

---

## Statistics

- **Events with projections:** 37
- **Unique projections:** 13
- **Total event-to-projection mappings:** 146

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| idEvent | ArtifactListProjection, ArtifactListProjection, ArtifactListProjection... | 53 |
| workflow_execution_startedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 10 |
| workflow_createdEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowDetailProjection... | 6 |
| workflow_completedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 6 |
| workflow_failedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 6 |
| phase_startedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 4 |
| phase_completedEvent | WorkflowExecutionDetailProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| artifact_createdEvent | DashboardMetricsProjection, DashboardMetricsProjection, ArtifactListProjection... | 4 |
| session_completedEvent | DashboardMetricsProjection, DashboardMetricsProjection, SessionListProjection... | 4 |
| session_startedEvent | DashboardMetricsProjection, DashboardMetricsProjection, SessionListProjection... | 4 |

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
