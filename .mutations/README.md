# Mutation evidence for #1915 (E2B shipped dark)

Each patch re-introduces one bug; the named test in
`packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/test_e2b_backend.py` must fail.

| Patch | Bug | Killing test |
|---|---|---|
| 01-selection-ignores-flag | `WorkspaceBackend.selected` always Docker | `test_flag_on_with_key_selects_e2b`, `test_production_wiring_selects_from_settings` |
| 02-e2b-reads-host-mount | E2B kit reads files from a host mount it does not have | `test_conformance_suite_over_the_double` |
| 03-enabled-without-key-loads | enabled without key/template loads (silent fallback) | `test_enabled_without_key_or_template_refuses_to_load` |
| 04-wiring-drops-selection | syn-api wiring hard-codes Docker | `test_production_wiring_selects_from_settings` |
| 05-timeout-dropped | `SYN_E2B_TIMEOUT_SECONDS` dropped at the provider constructor | `test_service_wires_the_e2b_provider_through_the_agentic_adapter` |
