# Event Flow Summary

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

---

## Top Event Flows

This table shows the most important event flows in Syn137 (events that feed the most projections):

| Command | Event | Projections | Count |
|---------|-------|-------------|-------|
| ? | workflow_execution_started | RepoCorrelationProjection, WorkflowExecutionDetailProjection, WorkflowDetailProjection... | 7 |
| ? | workflow_completed | RepoHealthProjection, RepoCostProjection, WorkflowExecutionDetailProjection... | 6 |
| ? | workflow_failed | RepoHealthProjection, RepoCostProjection, WorkflowExecutionDetailProjection... | 6 |
| ? | phase_completed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, ExecutionTodoProjection... | 4 |
| ? | workflow_template_created | WorkflowDetailProjection, WorkflowListProjection, DashboardMetricsProjection | 3 |
| ? | phase_started | WorkflowExecutionDetailProjection, WorkflowPhaseMetricsProjection, DashboardMetricsProjection | 3 |
| ? | workflow_interrupted | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, ExecutionTodoProjection | 3 |
| ? | execution_cancelled | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection, ExecutionTodoProjection | 3 |
| ? | trigger_fired | RepoCorrelationProjection, TriggerHistoryProjection, TriggerRuleProjection | 3 |
| ? | session_started | SessionListProjection, DashboardMetricsProjection | 2 |
| ? | session_summary | SessionCostProjection, ExecutionCostProjection | 2 |
| ? | artifact_created | ArtifactListProjection, DashboardMetricsProjection | 2 |
| ? | agent_observation | SessionCostProjection, ExecutionCostProjection | 2 |
| ? | session_completed | SessionListProjection, DashboardMetricsProjection | 2 |
| ? | session_cost_finalized | SessionCostProjection, ExecutionCostProjection | 2 |

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
