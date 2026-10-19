# Mutation evidence for #1055

Run against `apps/syn-api/tests/test_export_round_trips.py` and
`apps/syn-api/tests/test_api_workflow_export.py` (no Docker needed).

| Patch | Bug it reintroduces | Killed by (verified locally) |
|---|---|---|
| 01-input-default-character-test-only | pre-#1054 emission: quote a default only on a special character, so `false` goes out bare | `TestExportedInputsReinstallAsTheSameStrings::test_a_default_reads_back_as_the_stored_string` (10 params), `test_every_declaration_survives_in_order`, `test_export_workflow_with_input_declarations` |
| 02-input-required-always-true | `required: false` lost on export | `test_an_optional_input_stays_optional`, `test_export_workflow_with_input_declarations` |
| 03-input-name-unquoted | input name emitted bare | `test_a_name_reads_back_as_the_stored_string` (13 params) |
| 04-detail-keeps-only-first-input | read model drops all but the first declaration before export | `test_export_workflow_with_input_declarations` |
| 05-input-description-unquoted | input description emitted bare | `test_a_description_reads_back_as_the_stored_string` (13 params) |
