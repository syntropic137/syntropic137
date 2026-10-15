# Mutation evidence for #1570

Each patch re-introduces one way a read by id can stop working while
`artifact_summaries` lags. Run with Docker, since the integration tests need the event store and MinIO; when no test-stack MinIO answers, the integration fixture starts a MinIO container itself, so the event-store-only CI environment is enough. "Lags" there is a held subscription checkpoint, not an unfed projection.

| Patch | Bug it re-introduces | Tests meant to kill it |
|---|---|---|
| `01-no-aggregate-fallback.patch` | a projection miss is "not found", which is the #1570 defect | `packages/syn-domain/src/syn_domain/contexts/artifacts/slices/get_artifact/test_get_artifact.py::test_an_artifact_the_projection_has_not_seen_is_found_with_its_storage_key`, `packages/syn-domain/src/syn_domain/contexts/artifacts/slices/get_artifact/test_get_artifact.py::test_the_fallback_is_the_row_the_projection_writes_once_it_catches_up`, `apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_text_artifact_reads_by_id_and_content_while_the_projection_lags`, `apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_binary_artifact_reads_raw_from_its_scoped_storage_key_while_the_projection_lags` |
| `02-fallback-drops-storage-uri.patch` | the fallback loses the storage key, so the download rebuilds an id-only key (#1652) | `packages/syn-domain/src/syn_domain/contexts/artifacts/slices/get_artifact/test_get_artifact.py::test_an_artifact_the_projection_has_not_seen_is_found_with_its_storage_key`, `packages/syn-domain/src/syn_domain/contexts/artifacts/slices/get_artifact/test_get_artifact.py::test_the_fallback_is_the_row_the_projection_writes_once_it_catches_up`, `apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_binary_artifact_reads_raw_from_its_scoped_storage_key_while_the_projection_lags` |
| `03-raw-route-404s-on-projection-miss.patch` | `/raw` goes back to `resolve_or_raise`, which 404s before the domain lookup runs | `apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_binary_artifact_reads_raw_from_its_scoped_storage_key_while_the_projection_lags` |
| `04-detail-route-404s-on-projection-miss.patch` | `GET /artifacts/{id}` goes back to `resolve_or_raise`, which 404s before the domain lookup runs | `apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_text_artifact_reads_by_id_and_content_while_the_projection_lags` |
| `05-content-route-404s-on-projection-miss.patch` | `/content` goes back to `resolve_or_raise`, which 404s before the domain lookup runs | `apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_text_artifact_reads_by_id_and_content_while_the_projection_lags` |

Dispatch:

```
just mutation-evidence 1981 "packages/syn-domain/src/syn_domain/contexts/artifacts/slices/get_artifact/test_get_artifact.py::test_an_artifact_the_projection_has_not_seen_is_found_with_its_storage_key packages/syn-domain/src/syn_domain/contexts/artifacts/slices/get_artifact/test_get_artifact.py::test_the_fallback_is_the_row_the_projection_writes_once_it_catches_up apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_text_artifact_reads_by_id_and_content_while_the_projection_lags apps/syn-api/tests/integration/test_1570_artifact_read_while_projection_lags.py::test_a_binary_artifact_reads_raw_from_its_scoped_storage_key_while_the_projection_lags"
```

Delete `.mutations/` before merge.
