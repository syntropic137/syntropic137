# Upstream mutation for the grant on a real provider (#1927)

The real-provider contract test sees the grant only after agentic-workspace's
`OperationSpool` has redacted it, so the mutation that proves the test guards
the grant has to live in the `lib/agentic-workspace` submodule.
`scripts/mutation_evidence.py` refuses submodule paths, and it collects
`*.patch` only directly under the directory it is given, so it never picks up
this one. The patch is kept here so that the PR reviews it. Paths are relative
to the submodule root. It applies to the pinned `be32a683d2`.

| Patch | Bug it re-introduces | Expected failure in `packages/syn-adapters/tests/test_docker_operation_contract.py::test_bound_credentials_reach_the_workload_and_nothing_else` |
|---|---|---|
| `01-spool-forgets-resolved-bindings.patch` | `DockerOperations._start_locked` stops registering values resolved from `spec.credential_bindings` with the spool (`redact=(*redact, *resolved)` -> `redact=redact`) | `assert f"grant={PROVIDER_REDACTED.decode()}" in lines`: our scrubber catches the grant instead, so the line reads `grant=[REDACTED:credential]` |
| the same patch plus `../01-scrubber-forgets-launch-grant.patch` | Neither layer knows the grant | `assert not any(_TOKEN in line or _GRANT in line for line in lines)`: the raw grant reaches the line |

Run it in a Docker-capable checkout of the PR head with `SYN_CONTRACT_TEST_IMAGE` set, as `integration-evidence.yml` does:

```
git submodule update --init lib/agentic-workspace
git -C lib/agentic-workspace apply ../../.mutations/agentic-workspace/01-spool-forgets-resolved-bindings.patch
uv run pytest -m integration -q "packages/syn-adapters/tests/test_docker_operation_contract.py::test_bound_credentials_reach_the_workload_and_nothing_else"   # expect FAILED at the marker
git apply .mutations/01-scrubber-forgets-launch-grant.patch
uv run pytest -m integration -q "packages/syn-adapters/tests/test_docker_operation_contract.py::test_bound_credentials_reach_the_workload_and_nothing_else"   # expect FAILED at the raw-value check
git apply -R .mutations/01-scrubber-forgets-launch-grant.patch
git -C lib/agentic-workspace apply -R ../../.mutations/agentic-workspace/01-spool-forgets-resolved-bindings.patch
```

Neither result has been executed yet. No agent workspace has Docker.
