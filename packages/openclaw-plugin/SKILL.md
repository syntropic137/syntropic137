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


## Find sessions for a workflow run

Use `syn_get_session_inventory` with `execution_id` to read reconstruction status
and the latest committed snapshot. If `snapshot` is null, report that no revision
has been published yet. Do not describe this as a run with no sessions.

Pass the returned `snapshot_id` to read a bounded page. `kind` selects `node`,
`membership`, `edge`, `capture`, `gap`, `binding`, or `retraction`. Keep the same
snapshot ID and pass each `next_cursor` unchanged as `cursor` until it is null. Never combine
pages from different revisions. Read memberships for phase/attempt attribution,
edges for parentage, and captures for body availability. Preserve full IDs and
confidence; do not infer verified relationships from names or timestamps.

Reconstruction being `current` does not mean coverage is complete. Report the
snapshot coverage and any pending evidence or gaps. These reads use Syntropic137
and do not require SeshMagic. They do not start workflows or refresh jobs.

For the whole run in one call, pass `all: true`: it pins the current revision
(or `snapshot_id`), reads every section and page (or only `kind`), and returns
`summary`, `revision`, `coverage`, `counts`, `sections` and `gaps`. A section
with `truncated: true` hit the page budget; resume it with its `next_cursor`,
the same `snapshot_id` and `kind`. Use `phase_id`/`attempt_id` to narrow to one
phase or attempt, and `node_key` (from `item_keys`) with `snapshot_id` to
resolve a lineage endpoint that lives on another page.

Report `summary.counts_display` and `summary.coverage_display` verbatim; they
are the same text the CLI and dashboard show. `summary.complete` is the server's
coverage verdict only. An `all` result also reports `traversal_complete` (every
section read from its first page, unfiltered, nothing truncated) and `complete`
(both). Only say the inventory is complete when `complete` is true; otherwise
report `pending_sections` and `note`, and treat gaps and lineage as provisional.
A single page never proves completeness. Native transcript IDs are scoped to their harness; never
pass one where a platform session ID is expected (e.g. `syn_get_session`).
