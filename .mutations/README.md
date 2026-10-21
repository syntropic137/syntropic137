# Mutation evidence for PR #1928 (#1927)

| Patch | Bug it re-introduces | Tests meant to kill it |
|---|---|---|
| `01-scrubber-forgets-launch-grant.patch` | `WorkspaceCredentials.withheld` stops returning launch values, so the stream scrubber never learns the grant | `packages/syn-adapters/tests/workspace_backends/agentic/test_1927_canary_never_reaches_a_sink.py::test_a_printed_canary_reaches_no_sink_in_any_form` (unit, `docker=false`) |

Run: `just mutation-evidence 1928 "packages/syn-adapters/tests/workspace_backends/agentic/test_1927_canary_never_reaches_a_sink.py::test_a_printed_canary_reaches_no_sink_in_any_form" false`

## The real-provider contract test and the grant

`test_docker_operation_contract.py::test_bound_credentials_reach_the_workload_and_nothing_else`
does NOT kill patch 01. On a real provider the grant is a launch
`CredentialBinding`, and agentic-workspace's `OperationSpool` replaces it with
`[REDACTED]` before our scrubber sees the line. That is the provider's documented
contract (`SupportsOperations.start`), so patch 01 leaves `grant=[REDACTED]`.

The layer that test observes for the grant lives in the `lib/agentic-workspace`
submodule, and this runner refuses submodule patches. The matching patch
(`redact=(*redact, *resolved)` -> `redact=redact` in
`providers/docker_operations.py`) is kept with the phase report, not here. With
it applied, our scrubber catches the grant as `grant=[REDACTED:credential]`, and
the exact-marker assertion fails. With both it and patch 01 applied, the raw
value reaches the line, and `assert not any(... _GRANT in line ...)` fails.
