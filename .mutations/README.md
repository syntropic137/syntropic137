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
