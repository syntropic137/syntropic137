# Mutation evidence for #918 (cancel stops the agent)

Run with Docker, so the integration test runs too (docker=true, the default):

```
just mutation-evidence 1974 "packages/syn-adapters/tests/workspace_backends/agentic/test_918_cancel_stops_the_agent.py packages/syn-adapters/tests/test_918_cancel_stops_a_signal_ignoring_agent.py::test_a_cancel_stops_an_agent_that_ignores_its_signals"
```

| Patch | Bug it re-introduces | Meant to be killed by |
|---|---|---|
| `01-interrupt-never-reaches-the-operation.patch` | `ManagedWorkspace.interrupt()` returns without cancelling anything: the #918 behaviour, where the agent ran on | `test_918_cancel_stops_the_agent.py::test_a_cancel_stops_an_agent_that_ignores_its_signals`, `test_918_cancel_stops_a_signal_ignoring_agent.py::test_a_cancel_stops_an_agent_that_ignores_its_signals` |
| `02-running-operation-not-registered.patch` | the adapter never records the operation it started, so a cancel finds nothing to stop | `test_918_cancel_stops_the_agent.py::test_a_cancel_stops_an_agent_that_ignores_its_signals`, `test_918_cancel_stops_a_signal_ignoring_agent.py::test_a_cancel_stops_an_agent_that_ignores_its_signals` |
| `03-unconfirmed-stop-reported-as-stopped.patch` | a cancel the provider could not confirm is reported as a stop | `test_918_cancel_stops_the_agent.py::test_interrupt_reports_a_stop_the_provider_could_not_confirm` |
| `04-finished-stream-stays-registered.patch` | a finished stream stays registered, so a later cancel targets a dead operation | `test_918_cancel_stops_the_agent.py::test_a_finished_stream_leaves_nothing_to_cancel` |

Checked locally without Docker: each patch fails the unit test named for it.
Delete `.mutations/` before merge.
