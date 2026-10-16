# Mutation evidence for the setup-env redaction fix

All tests are in `packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_env_redaction_policy.py`. They need no Docker, so use `docker=false`:

```
just mutation-evidence <PR> "packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_env_redaction_policy.py::test_setup_environment_with_a_github_app_identity_registers packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_env_redaction_policy.py::test_the_real_secret_is_still_redacted_and_the_empty_key_ignored packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_env_redaction_policy.py::test_a_configured_api_key_is_still_registered packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_env_redaction_policy.py::test_the_bot_identity_still_reaches_git" false
```

| patch | bug it re-introduces | killed by (seen locally) |
|---|---|---|
| 01-identity-back-in-redacted-env | `<app>[bot]` registered for redaction again (the 1.0.4-beta.1 failure) | `::test_setup_environment_with_a_github_app_identity_registers`, `::test_the_real_secret_is_still_redacted_and_the_empty_key_ignored`, `::test_a_configured_api_key_is_still_registered` |
| 02-empty-api-key-registered | the empty-value skip removed, so an empty `ANTHROPIC_API_KEY` is delivered | `::test_the_real_secret_is_still_redacted_and_the_empty_key_ignored` |
| 03-identity-dropped-from-script | the identity is dropped and not moved | `::test_the_bot_identity_still_reaches_git` |
| 04-oauth-token-not-delivered | the scrub is weakened: the real token is no longer delivered or registered | `::test_the_real_secret_is_still_redacted_and_the_empty_key_ignored`, `::test_a_configured_api_key_is_still_registered` |

Patch 02 is the "empty-value skip removed" mutation the task asked for. It was NOT the deploy's cause: AW skips empty values on its own. That is why only the env-shape assertion kills it, and the registry does not.
