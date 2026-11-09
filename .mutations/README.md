# Mutation evidence for #980

| Patch | Re-introduces | Killed by |
|---|---|---|
| `01-one-outcome-for-every-workspace.patch` | one adapter-wide outcome shared by every workspace (main's behaviour) | every test in `packages/syn-adapters/tests/workspace_backends/agentic/test_980_a_stream_outcome_belongs_to_its_workspace.py` |

Run without Docker: `just mutation-evidence 2220 "packages/syn-adapters/tests/workspace_backends/agentic/test_980_a_stream_outcome_belongs_to_its_workspace.py" false`
