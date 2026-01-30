# Event Flow Summary

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

---

## Top Event Flows

This table shows the most important event flows in AEF (events that feed the most projections):

| Command | Event | Projections | Count |
|---------|-------|-------------|-------|
| ? | workflow_execution_started | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowDetailProjection... | 5 |
| ? | workflow_failed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| ? | workflow_completed | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| ? | workflow_created | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |
| ? | phase_started | DashboardMetricsProjection, WorkflowExecutionDetailProjection | 2 |
| ? | session_started | DashboardMetricsProjection, SessionListProjection | 2 |
| ? | phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| ? | execution_resumed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| ? | agent_observation | ExecutionCostProjection, SessionCostProjection | 2 |
| ? | execution_cancelled | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| ? | session_cost_finalized | ExecutionCostProjection, SessionCostProjection | 2 |
| ? | artifact_created | DashboardMetricsProjection, ArtifactListProjection | 2 |
| ? | session_completed | DashboardMetricsProjection, SessionListProjection | 2 |
| ? | execution_paused | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| ? | workspace_destroyed | WorkspaceMetricsProjection | 1 |

---

## Detailed Flow Diagrams

📝 **Manual diagrams** - These show detailed sequence flows for key operations:

- [Workflow Creation](./workflow-creation.md) - `CreateWorkflow` → `WorkflowCreated` flow

---

## Related Documentation

- [Event Architecture](../event-architecture.md)
- [Projection Subscriptions](../projection-subscriptions.md)

---

🤖 **This file is auto-generated** - Do not edit manually. To regenerate:

```bash
just docs-gen
```
