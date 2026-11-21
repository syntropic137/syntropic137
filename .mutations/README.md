# Mutation evidence for #2342 (PR #2343)

Each patch re-introduces one bug in production source. The named test must fail with it applied, and it passes on the clean head.

| Patch | Bug | Killed by |
|---|---|---|
| `01-tool-timeline-clear-no-op.patch` | `ToolTimelineProjection.clear_all_data` reverts to a no-op, so a version rebuild keeps the `tool_timelines` rows | `packages/syn-adapters/tests/test_2342_observation_adapters_clear_on_rebuild.py::test_version_rebuild_clears_only_the_rebuilt_adapters_namespace[tool_timeline]` (`tool_timelines kept its rows through a version rebuild`) |
| `02-tool-timeline-clear-deletes-session-cost.patch` | The tool-timeline clear also deletes another adapter's namespace (`session_cost`) | same test (`rebuilding tool_timeline deleted session_cost`) |

Both are docker-free: `just mutation-evidence 2343 "packages/syn-adapters/tests/test_2342_observation_adapters_clear_on_rebuild.py" false`.

The class-level regression (an adapter that inherits ESP's no-op) is guarded by the architecture fitness test `ci/fitness/event_sourcing/test_rebuild_clears_read_models.py`. It is not a mutation target here because the runner refuses patches whose named test lives under `ci/`. On `main` it fails with `['ToolTimelineAdapter (tool_timeline)']`.
