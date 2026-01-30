# Event Flow Summary

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

---

## Top Event Flows

This table shows the most important event flows in AEF (events that feed the most projections):

| Command | Event | Projections | Count |
|---------|-------|-------------|-------|
| ? | idEvent | ArtifactListProjection, ArtifactListProjection, ArtifactListProjection... | 53 |
| ? | workflow_execution_startedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 10 |
| ? | workflow_createdEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowDetailProjection... | 6 |
| ? | workflow_completedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 6 |
| ? | workflow_failedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 6 |
| ? | phase_startedEvent | DashboardMetricsProjection, DashboardMetricsProjection, WorkflowExecutionDetailProjection... | 4 |
| ? | phase_completedEvent | WorkflowExecutionDetailProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| ? | artifact_createdEvent | DashboardMetricsProjection, DashboardMetricsProjection, ArtifactListProjection... | 4 |
| ? | session_completedEvent | DashboardMetricsProjection, DashboardMetricsProjection, SessionListProjection... | 4 |
| ? | session_startedEvent | DashboardMetricsProjection, DashboardMetricsProjection, SessionListProjection... | 4 |
| ? | workspace_creatingEvent | WorkspaceMetricsProjection, WorkspaceMetricsProjection | 2 |
| ? | subagent_startedEvent | SessionListProjection, SessionListProjection | 2 |
| ? | idsEvent | ExecutionCostProjection, ExecutionCostProjection | 2 |
| ? | execution_pausedEvent | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| ? | execution_cancelledEvent | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |

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
