# Mutation evidence for #1675 batch 1 (PR #1990)

Each patch makes an in-memory adapter diverge from its contract. Every one was
checked locally on the unit (memory) leg; the integration (Postgres) leg of the
same test is what the orchestrator's runner adds.

| Patch | Bug it re-introduces | Test meant to kill it |
|---|---|---|
| 01-save-if-ignores-expected.patch | `InMemoryProjectionStore.save_if` writes over a row that no longer equals `expected` (the lost update) | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_save_if_refuses_a_stale_expected_row` |
| 02-save-if-insert-overwrites.patch | `save_if(expected=None)` overwrites an existing row instead of insert-only | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_save_if_with_no_expected_row_inserts_only_once` |
| 03-cursor-fake-keeps-what-postgres-drops.patch | `InMemoryPollerCursorStore.save` hands back metadata Postgres does not keep (the pre-fix behaviour) | `packages/syn-adapters/tests/contract/test_poller_cursor_contract.py::test_metadata_other_than_last_event_id_is_not_kept` |
| 04-ledger-mark-can-fall.patch | `InMemoryImportLedger.record_billed` lets the uncached-input mark fall (no GREATEST) | `packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_mark_only_rises_per_bucket` |
| 05-ledger-guard-admits-everyone.patch | `InMemoryImportLedger.guard` takes no lock | `packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_guard_admits_one_importer_per_session_at_a_time` |
| 06-ledger-cache-read-can-fall.patch | `InMemoryImportLedger.record_billed` lets the cache-read mark fall | `packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_mark_only_rises_per_bucket` |
| 07-ledger-output-can-fall.patch | `InMemoryImportLedger.record_billed` lets the output mark fall | `packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_mark_only_rises_per_bucket` |
| 08-ledger-keys-raw-session-ids.patch | `InMemoryImportLedger` keys a session by its raw id, so a raw id and its `pg_safe` spelling are two sessions | `packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_a_raw_session_id_and_its_stored_spelling_are_one_session` |
| 09-projection-keys-raw.patch | `InMemoryProjectionStore` keys records by the raw key, never `pg_safe(key)` | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_a_raw_key_and_its_stored_spelling_address_one_record` |
| 10-filter-compares-python-values.patch | `InMemoryProjectionStore` filters compare Python values instead of the `->>` text Postgres compares | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_query_and_count_compare_the_json_text_of_a_field` |
| 11-ledger-cache-creation-can-fall.patch | `InMemoryImportLedger.record_billed` lets the cache-creation mark fall | `packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_mark_only_rises_per_bucket` |

Node ids for `just mutation-evidence 1990 "<ids>"` (all eleven patches, space-separated):

```
packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_save_if_refuses_a_stale_expected_row packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_save_if_with_no_expected_row_inserts_only_once packages/syn-adapters/tests/contract/test_poller_cursor_contract.py::test_metadata_other_than_last_event_id_is_not_kept packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_mark_only_rises_per_bucket packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_the_guard_admits_one_importer_per_session_at_a_time packages/syn-adapters/tests/contract/test_import_ledger_contract.py::test_a_raw_session_id_and_its_stored_spelling_are_one_session packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_a_raw_key_and_its_stored_spelling_address_one_record packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_query_and_count_compare_the_json_text_of_a_field
```

Those select a subset of the Postgres legs. To execute EVERY contract case on
both legs (the baseline verification asked for), pass the three files:

```
packages/syn-adapters/tests/contract/test_projection_store_contract.py packages/syn-adapters/tests/contract/test_poller_cursor_contract.py packages/syn-adapters/tests/contract/test_import_ledger_contract.py
```

Run with the default `docker=true`, so the `[postgres]` legs run too and do not skip.
Delete `.mutations/` before merge.
