# Mutation evidence for #1502 (reject the retired can_open_pr key at authoring time)

Every patch is a unified diff against the fixed code. Node ids for
`just mutation-evidence`:

    packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/test_retired_phase_fields.py
    packages/syn-domain/src/syn_domain/contexts/orchestration/slices/create_workflow_template/test_retired_phase_field_reinstall.py
    apps/syn-api/tests/test_endpoint_workflows_validate.py
    apps/syn-api/tests/test_endpoint_workflows_from_yaml.py

| patch | bug it re-introduces | killing test |
|---|---|---|
| 01-validator-no-longer-rejects | `_reject_retired_fields` passes the phase through, so the key falls to the generic "Extra inputs are not permitted" with no reason | test_retired_phase_fields.py::TestARetiredKeyIsRefused::test_a_workflow_carrying_the_key_is_refused (+ validate/install endpoint tests) |
| 02-retired-key-dropped-not-refused | the key is silently dropped again (the pre-#1502 accept-and-ignore behaviour) | test_any_value_is_refused, test_validate_reports_it_as_an_error, test_package_still_carrying_the_key_is_refused, test_a_retired_key_is_invalid, test_install_refuses_a_retired_key |
| 03-message-omits-the-reason | the refusal names the key but not why it was retired | TestRejectRetiredFields::test_every_retired_key_is_named |
| 04-only-a-truthy-value-is-refused | `can_open_pr: false` / `null` slips past the check (and then fails generically) | test_any_value_is_refused[false], test_any_value_is_refused[null] |

Each was applied and run locally; each failed the named tests, and the tree
reverted clean. The trusted run is `mutation-evidence.yml`, not this note.
