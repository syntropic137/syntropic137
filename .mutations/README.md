# Mutation evidence for #1912 (E2B agent launch through the BackendKit)

Every patch is killed by the tests in `packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/test_1912_an_agent_launches_on_e2b.py`.
Node ids for `just mutation-evidence`:

    packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/test_1912_an_agent_launches_on_e2b.py::test_the_agent_launches_through_the_e2b_provider
    packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/test_1912_an_agent_launches_on_e2b.py::test_cancelling_the_agent_cancels_the_e2b_operation

| patch | bug it re-introduces | killing test |
|---|---|---|
| 01-e2b-launch-falls-back-to-docker-exec | the stream prefixes the agent argv with `docker exec <id>` | test_the_agent_launches_through_the_e2b_provider |
| 02-exit-code-from-docker-only-diagnosis | the exit code is not taken from the provider's OperationStatus (left to a docker-only diagnosis, which yields nothing on E2B) | test_the_agent_launches_through_the_e2b_provider, test_cancelling_the_agent_cancels_the_e2b_operation |
| 03-cancel-not-forwarded-to-provider | `cancel_running` reports success without calling `provider.cancel` | test_cancelling_the_agent_cancels_the_e2b_operation |
| 04-e2b-provider-built-without-resolver | the production E2B factory builds the provider without the adapter's credential resolver, so `start` refuses the launch credential (the defect this PR fixes) | test_the_agent_launches_through_the_e2b_provider |
| 05-isolation-type-not-from-kit | the handle's isolation_type is hard-coded `docker` instead of read from the kit | test_the_agent_launches_through_the_e2b_provider |

Each was applied and run locally in the agent workspace; each failed the
named test. The trusted run is `mutation-evidence.yml`, not this note.

## Added in fix round 1 (verification findings B1 and B2)

Node ids for `just mutation-evidence`, in addition to the two above:

    packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/test_1912_an_agent_launches_on_e2b.py::test_a_remote_signal_death_is_never_explained_by_this_host
    packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/test_1912_the_engine_launches_on_e2b.py::test_the_engine_launches_an_agent_on_e2b
    packages/syn-adapters/tests/workspace_backends/agentic/test_stream_on_operations.py::test_a_remote_signal_death_never_reads_this_hosts_kernel

| patch | bug it re-introduces | killing test |
|---|---|---|
| 06-remote-signal-reads-host-kernel | stream settlement reads this host's kernel ring buffer for a remote (E2B) signal death | test_a_remote_signal_death_is_never_explained_by_this_host, test_a_remote_signal_death_never_reads_this_hosts_kernel |
| 07-signal-capture-ignores-remote-kernel | `capture_signal_death` reads the host kernel even when told the process ran remotely | test_a_remote_signal_death_is_never_explained_by_this_host, test_a_remote_signal_death_never_reads_this_hosts_kernel |
| 08-launch-marker-corrupted | the launch announces a marker line other than `announce_as(wrapper)` | test_the_engine_launches_an_agent_on_e2b, test_the_agent_launches_through_the_e2b_provider |
| 09-e2b-kit-shares-host-kernel | the E2B kit claims its sandbox shares this host's kernel | test_a_remote_signal_death_is_never_explained_by_this_host |

Patches 01, 04, 05 and 08 also fail test_the_engine_launches_an_agent_on_e2b
(the engine path: `AgentExecutionHandler` over the real E2B operations).
