# Mutation evidence: OTLP envelope (#673, syn-collector)

Each patch mutates `packages/syn-collector/src/syn_collector/collector/otlp_envelope.py`.
Run every patch against `packages/syn-collector/tests/test_otlp_envelope.py`
(no Docker needed). Local results in a workspace, before the trusted run:

| Patch | Bug it re-introduces | Killed locally by |
|---|---|---|
| `01-rename-int-value-alias.patch` | wire-name rename: `intValue` read as `int_value`, so int attributes become `""` | `test_datapoint_event_shape`, `test_known_event_shape`, `test_logs_row`, `test_log_attribute_value[present-null-is-null]`, `[present-null-beats-later-kind]` |
| `02-camel-case-timestamp-wins.patch` | data point `timeUnixNano` beats `time_unix_nano` (precedence flipped) | `test_snake_case_key_wins_over_camel_case` |
| `03-empty-section-not-absent.patch` | `"gauge": {}` no longer falls through to `sum` (`if section is not None`) | `test_empty_section_falls_through_to_next` |
| `04-rename-severity-field.patch` | accessor rename `severity_text` -> `severity` | the three `TestLogsEnvelope` tests, `test_logs_row`, every log case in `TestAcceptanceMatchesDictParser` |

## Round 1 fix: lazy read-only views (`aa2371067`)

Verification found the Pydantic envelope above changed accepted input, so
`otlp_envelope.py` is now frozen dataclass views that read the raw JSON
lazily. Round 2 regenerated patches 01-04 against the views, keeping the
attack each one documents above, so all eight patches apply to this head. Run
05-08 against the same test file too:

| Patch | Bug it re-introduces | Killed locally by |
|---|---|---|
| `05-rename-severity-text-field.patch` | field rename `severity_text` -> `severity` | the three `TestLogsEnvelope` tests, `test_logs_row`, every log case in `TestAcceptanceMatchesDictParser` |
| `06-scalar-selects-non-null.patch` | AnyValue kind chosen by non-null, not presence | `test_log_attribute_value[present-null-is-null]`, `[present-null-beats-later-kind]` |
| `07-null-session-becomes-unknown.patch` | `"stringValue": null` session read as `"unknown"` (new event ID) | `test_null_session_string_is_stringified` |
| `08-datapoint-value-coerced-to-float.patch` | data point value converted instead of stored as sent | `test_datapoint_event_shape`, three `test_value_precedence` cases, `test_metrics_row`, four `test_metrics` acceptance cases |
