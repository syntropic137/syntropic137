# Mutation evidence: OTLP envelope (#673, syn-collector)

Each patch mutates `packages/syn-collector/src/syn_collector/collector/otlp_envelope.py`.
Run every patch against `packages/syn-collector/tests/test_otlp_envelope.py`
(no Docker needed). Local results in a workspace, before the trusted run:

| Patch | Bug it re-introduces | Killed locally by |
|---|---|---|
| `01-rename-int-value-alias.patch` | wire-name rename: `intValue` read as `int_value`, so int attributes become `""` | `test_datapoint_event_shape`, `test_known_event_shape`, `test_logs_row` |
| `02-camel-case-timestamp-wins.patch` | data point `timeUnixNano` beats `time_unix_nano` (precedence flipped) | `test_snake_case_key_wins_over_camel_case` |
| `03-empty-section-not-absent.patch` | `"gauge": {}` no longer falls through to `sum` | `test_empty_section_falls_through_to_next` |
| `04-rename-severity-field.patch` | field rename `severity_text` -> `severity` | the three `TestLogsEnvelope` tests, `test_logs_row` |
