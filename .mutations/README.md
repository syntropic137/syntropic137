# Mutation evidence for #1914 (BackendKit + WorkspaceCredentialPolicy)

Each patch re-introduces one bypass of a credential guard. All eight were killed locally (2026-10-17) by the node ids below.
Delete this directory before merge (CI `mutations-not-merged`).

| Patch | Guard it removes | Test that must kill it |
|---|---|---|
| 01-agent-env-bypasses-policy | `_build_agent_env` ignores the policy (the issue's negative control) | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_no_credentials_scan_finds_none` |
| 02-repos-not-refused | handler no longer refuses a phase with repos before `create_workspace` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_a_phase_with_repos_is_refused_before_create_workspace` |
| 03-setup-secrets-ignore-policy | handler calls `SetupPhaseSecrets.create` (GitHub/Claude/Codex) under NoCredentials | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_no_credentials_scan_finds_none` |
| 04-kit-admits-any-image | NoCredentials kit starts with any image (claude-cli included) | `packages/syn-adapters/tests/workspace_backends/test_1914_backend_kit.py::TestCredentialFreeKitRefusesToStart::test_with_the_claude_cli_digest` |
| 05-session-store-token-kept | Docker adapter keeps the session-store write token under NoCredentials | `packages/syn-adapters/tests/workspace_backends/test_1914_backend_kit.py::TestNoCredentialsDropsTheSessionStoreToken::test_no_binding_and_no_store_env` |
| 06-platform-grant-ignores-policy | platform grant (ADR-072) issued to a NoCredentials workspace | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_no_credentials_scan_finds_none` |
| 07-sidecar-requested-regardless | handler hard-codes `with_sidecar=True, inject_tokens=True` again | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_no_credentials_scan_finds_none` |
| 08-renewal-ignores-policy | `ManagedWorkspace.renew_git_credential` renews (rewrites the gh credential file) under NoCredentials | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_no_credentials_scan_finds_none` |

How the scan kills them: the scan node first runs the same repo-less phase under HostCredentials and
asserts every invented value (Claude OAuth, API key, Codex auth, GitHub token, platform grant, session-store
token) is found, then scans every channel under NoCredentials. 01, 03, 05, 06 and 08 each fail on the scan
assertion naming the leaked credential and its channel (01 in `stream_envs`: the fixture gives a workspace
with no sidecar an inert proxy URL, so a bypassed `build_agent_env` gets past its proxy check). 07 is killed
by the service's own refusal of a sidecar for a credential-free workspace.

Run (no Docker needed):

    just mutation-evidence 2006 "packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_no_credentials_scan_finds_none packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/test_1914_no_credentials_leaks_nothing.py::TestNoCredentialsLeaksNothing::test_a_phase_with_repos_is_refused_before_create_workspace packages/syn-adapters/tests/workspace_backends/test_1914_backend_kit.py::TestCredentialFreeKitRefusesToStart::test_with_the_claude_cli_digest packages/syn-adapters/tests/workspace_backends/test_1914_backend_kit.py::TestNoCredentialsDropsTheSessionStoreToken::test_no_binding_and_no_store_env" false
