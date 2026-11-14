# Mutation patches for #1948 (Claude credential at execute)

Tests: `apps/syn-api/tests/test_1948_a_claude_run_needs_a_credential.py` (no Docker needed).

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| 01-drop-execute-call-site | execute never checks the credential (the #1948 defect) | `test_a_claude_phase_with_no_credential_is_refused`, `test_an_unset_provider_is_claude_and_is_refused` |
| 02-predicate-always-true | predicate says a credential exists when none does | the two above, plus `test_a_codex_only_workflow_needs_no_anthropic_credential` (the /health half) |
| 04-command-phase-counted-as-claude | a COMMAND phase (no LLM) is counted as a Claude phase, so a command-only run is refused | `test_a_command_phase_needs_no_anthropic_credential` |
| 05-unset-agent-provider-not-claude | an agent phase with no provider (which runs on Claude) is not treated as Claude; replaces stale 03 | `test_an_unset_provider_is_claude_and_is_refused` |
