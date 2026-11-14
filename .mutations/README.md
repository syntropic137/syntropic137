# Mutation patches for #1948 (Claude credential at execute)

Tests: `apps/syn-api/tests/test_1948_a_claude_run_needs_a_credential.py` (no Docker needed).

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| 01-drop-execute-call-site | execute never checks the credential (the #1948 defect) | `test_a_claude_phase_with_no_credential_is_refused`, `test_an_unset_provider_is_claude_and_is_refused` |
| 02-predicate-always-true | predicate says a credential exists when none does | the two above, plus `test_a_codex_only_workflow_needs_no_anthropic_credential` (the /health half) |
| 03-unset-provider-not-claude | a phase with no provider (which runs on Claude) is not treated as Claude | `test_an_unset_provider_is_claude_and_is_refused` |
