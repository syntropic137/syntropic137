# Mutation evidence: #897 slice I (dashboard aggregate cost cards)

Each patch re-introduces one bug on one surface. Every one must make the
vitest command below fail.

| Patch | Bug re-introduced | Test file meant to kill it |
|---|---|---|
| 01-dashboard-formats-usd | Dashboard Total Tokens card formats `total_cost_usd` again | `pages/Dashboard/__tests__/DashboardCost.test.tsx` |
| 02-dashboard-drops-note | Dashboard drops the unpriced note (count forced to 0) | `pages/Dashboard/__tests__/DashboardCost.test.tsx` |
| 03-workflow-metrics-formats-usd | WorkflowMetrics formats `total_cost_usd` again | `pages/WorkflowDetail/__tests__/WorkflowMetrics.test.tsx` |
| 04-workflow-metrics-drops-note | WorkflowMetrics drops the unpriced note | `pages/WorkflowDetail/__tests__/WorkflowMetrics.test.tsx` |
| 05-workflow-runs-formats-usd | Workflow Runs row formats `total_cost_usd` again | `pages/__tests__/WorkflowRunsCost.test.tsx` |
| 06-workflow-runs-drops-note | Workflow Runs row drops the unpriced note | `pages/__tests__/WorkflowRunsCost.test.tsx` |

## The trusted runner cannot run these

`mutation-evidence.yml` takes pytest node IDs only, and these are vitest tests.
The exact command, from the repository root:

```
pnpm --dir apps/syn-dashboard-ui exec vitest run \
  src/pages/Dashboard/__tests__/DashboardCost.test.tsx \
  src/pages/WorkflowDetail/__tests__/WorkflowMetrics.test.tsx \
  src/pages/__tests__/WorkflowRunsCost.test.tsx
```

Per patch: `git apply .mutations/NN-*.patch`, run the command, expect failures,
`git apply -R .mutations/NN-*.patch`.

## Local result (2026-11-21, head 8d0ed907)

| Patch | Result of the command above |
|---|---|
| 01-dashboard-formats-usd | 3 failed: DashboardCost partial, unpriced, fully priced |
| 02-dashboard-drops-note | 2 failed: DashboardCost partial, unpriced |
| 03-workflow-metrics-formats-usd | 3 failed: WorkflowMetrics partial, unpriced, fully priced |
| 04-workflow-metrics-drops-note | 2 failed: WorkflowMetrics partial, unpriced |
| 05-workflow-runs-formats-usd | 3 failed: WorkflowRunsCost partial, unpriced, fully priced |
| 06-workflow-runs-drops-note | 2 failed: WorkflowRunsCost partial, unpriced |

Unmutated: 10 passed. A dropped note leaves the fully priced case green by
design: that case asserts there is no note.
