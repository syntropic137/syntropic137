# Event Flow Summary

🤖 **Auto-generated from VSA manifest** - Run `just docs-regen` to update

---

## Top Event Flows

This table shows the most important event flows in Syn137 (events that feed the most projections):

| Command | Event | Projections | Count |
|---------|-------|-------------|-------|
| ? | workflow_execution_started | DashboardMetricsProjection, ExecutionTodoProjection, RepoCorrelationProjection... | 7 |
| ? | workflow_failed | DashboardMetricsProjection, ExecutionTodoProjection, RepoCostProjection... | 7 |
| ? | workflow_completed | DashboardMetricsProjection, ExecutionTodoProjection, RepoCostProjection... | 6 |
| ? | execution_cancelled | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| ? | phase_completed | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| ? | workflow_interrupted | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection... | 4 |
| ? | next_phase_ready | ExecutionTodoProjection, WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 3 |
| ? | phase_started | DashboardMetricsProjection, WorkflowExecutionDetailProjection, WorkflowPhaseMetricsProjection | 3 |
| ? | trigger_fired | RepoCorrelationProjection, TriggerHistoryProjection, TriggerRuleProjection | 3 |
| ? | workflow_template_created | DashboardMetricsProjection, WorkflowDetailProjection, WorkflowListProjection | 3 |
| ? | agent_execution_completed | ExecutionTodoProjection, WorkflowExecutionDetailProjection | 2 |
| ? | agent_observation | ExecutionCostProjection, SessionCostProjection | 2 |
| ? | artifact_created | ArtifactListProjection, DashboardMetricsProjection | 2 |
| ? | execution_tags_added | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |
| ? | execution_tags_removed | WorkflowExecutionDetailProjection, WorkflowExecutionListProjection | 2 |

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
just docs-regen
```
