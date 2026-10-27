# Mutation evidence for #2154 (PR #2156)

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-any-value-counts-as-null.patch` | any value is accepted as a `KEY: null` passthrough | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `02-changed-lines-are-not-refused.patch` | a removed or changed line is let through | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `03-no-environment-ancestry-check.patch` | a null line is added wherever it appears: labels, a block scalar, beside a duplicate | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `04-not-bare-keys-allowed.patch` | a quoted, tagged or merge key beside the new line is not refused | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `05-duplicates-allowed.patch` | a null that duplicates (overrides) an existing key is accepted | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `06-crlf-rewritten.patch` | a CRLF compose is silently rewritten | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `07-stage-skips-null-keys.patch` | the stage-time re-check no longer applies null keys | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `08-no-backup.patch` | the live compose is replaced without a backup | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
| `09-mode-not-kept.patch` | the rewritten compose loses its file mode | `scripts/tests/test_pit_stop_repoint.py::TestAddNullKeys`, `scripts/tests/test_pit_stop_stage_write.py::test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup` |
