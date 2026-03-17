# Syntropic137 — AI Workflow Execution Platform

You have access to `syn_*` tools that let you interact with Syntropic137, a platform for orchestrating AI agent workflows in isolated Docker workspaces.

## When to Use

Use these tools when the user wants to:
- Run an automated workflow (e.g., "run the issue workflow for this GitHub issue")
- Check on running or past executions
- Review costs and token usage
- Get workflow outputs (artifacts)
- Set up GitHub automation triggers

## Key Concepts

- **Workflow** — A reusable template defining phases of agent work (e.g., "Issue Resolution", "Code Review")
- **Execution** — A single run of a workflow, progressing through phases
- **Phase** — A step within an execution (e.g., "analyze", "implement", "test")
- **Session** — An agent session within a phase, with full observability (tool calls, tokens, git ops)
- **Artifact** — An output produced by a phase (code, reports, analysis)
- **Trigger** — A rule that automatically starts a workflow on GitHub events

## Typical Flow

1. **Browse workflows:** `syn_list_workflows` to see what's available
2. **Start execution:** `syn_execute_workflow` with the workflow ID and inputs
3. **Monitor progress:** `syn_get_execution` to check status and phase progress
4. **Review details:** `syn_get_session` for tool-level observability, `syn_get_execution_cost` for cost breakdown
5. **Get results:** `syn_list_artifacts` and `syn_get_artifact` for outputs
6. **Automate:** `syn_create_trigger` to run workflows automatically on GitHub events

## Important Notes

- **Executions are async** — after starting one, poll with `syn_get_execution` to check progress
- **Resolve names to IDs** — use `syn_list_workflows` to find the workflow ID before executing
- **Mid-run corrections** — use `syn_inject_context` to send messages to a running agent
- **Cost awareness** — use `syn_get_execution_cost` to check spend, especially for multi-phase workflows
- **Metrics** — `syn_get_metrics` gives a platform-wide overview of usage and costs
