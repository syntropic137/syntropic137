# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Data Source:** `.topology/syn-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the Syn137 system.

**Total Relationships:** 42 events → 18 projections

```mermaid
graph LR
    subgraph events["Key Events"]
        e1[workflow_execution_started]
        e2[workflow_failed]
        e3[workflow_template_created]
        e4[phase_started]
        e5[phase_completed]
        e6[workflow_completed]
        e7[session_started]
        e8[session_cost_finalized]
        e9[workflow_interrupted]
        e10[artifact_created]
    end

    subgraph projections["Projections"]
        p1[ArtifactListProjection]
        p2[DashboardMetricsProjection]
        p3[ExecutionCostProjection]
        p4[InstallationProjection]
        p5[RepoProjection]
        p6[SessionCostProjection]
        p7[SessionListProjection]
        p8[SystemProjection]
        p9[TokenMetricsProjection]
        p10[ToolTimelineProjection]
        p11[TriggerHistoryProjection]
        p12[TriggerRuleProjection]
        p13[WorkflowDetailProjection]
        p14[WorkflowExecutionDetailProjection]
        p15[WorkflowExecutionListProjection]
    end

    e7 --> p7
    e7 --> p2
    e8 --> p6
    e8 --> p3
    e2 --> p14
    e2 --> p15
    e2 --> p2
    e3 --> p13
    e3 --> p2
    e9 --> p14
    e9 --> p15
    e10 --> p1
    e10 --> p2
    e1 --> p14
    e1 --> p13
    e1 --> p15
    e1 --> p2
    e4 --> p14
    e4 --> p2
    e5 --> p14
    e5 --> p15
    e6 --> p14
    e6 --> p15
    e6 --> p2
```

---

## Statistics

- **Events with projections:** 42
- **Unique projections:** 18
- **Total event-to-projection mappings:** 65

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
| workflow_execution_started | WorkflowExecutionDetailProjection, WorkflowDetailProjection, WorkflowExecutionListProjection... | 5 |
| workflow_failed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, DashboardMetricsProjection | 3 |
| workflow_template_created | WorkflowDetailProjection, WorkflowListProjection, DashboardMetricsProjection | 3 |
| phase_started | WorkflowExecutionDetailProjection, WorkflowPhaseMetricsProjection, DashboardMetricsProjection | 3 |
| phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, WorkflowPhaseMetricsProjection | 3 |
| workflow_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, DashboardMetricsProjection | 3 |
| session_started | SessionListProjection, DashboardMetricsProjection | 2 |
| session_cost_finalized | SessionCostProjection, ExecutionCostProjection | 2 |
| workflow_interrupted | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
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
