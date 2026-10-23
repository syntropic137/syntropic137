# Mutation evidence for #1913

Each patch re-introduces one defect into production source. Each one was applied locally and the named tests failed (run in an agent workspace, so this is not the trusted evidence `mutation-evidence.yml` produces).

| Patch | Defect | Killing test(s) |
|---|---|---|
| `01-manifest-read-falls-back-to-the-host-mount.patch` | Docker reads `/opt/agentic` from its `/workspace` bind mount (which ignores `base_path`) | `packages/syn-adapters/tests/workspace_backends/test_1913_image_manifest_through_file_transfer.py::test_docker_reads_the_manifest_through_the_provider_not_its_mount` |
| `02-remote-collection-falls-back-to-a-host-path.patch` | collection falls back to a host path on every backend, the remote one included | `test_1913_image_manifest_through_file_transfer.py::test_remote_artifacts_come_back_through_the_provider_byte_for_byte`, `::test_provisioning_records_the_manifest_read_through_the_provider`, `::test_docker_reads_the_manifest_through_the_provider_not_its_mount` |
| `03-absent-manifest-persisted-as-empty.patch` | no manifest file becomes a READ manifest of empty fields | `test_1913_image_manifest_through_file_transfer.py::test_an_image_with_no_manifest_is_recorded_absent`, `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_1913_image_manifest_reading.py::test_no_manifest_file_is_absent_not_a_manifest_of_empty_fields` |
| `04-file-transfer-errors-swallowed-as-absent.patch` | a file-transfer error is swallowed and recorded as "absent" | `test_1913_image_manifest_through_file_transfer.py::test_a_failed_transfer_is_recorded_unreadable_never_absent` |
| `05-event-drops-the-manifest.patch` | the command carries the reading but the event does not | `test_1913_image_manifest_reading.py::test_the_reading_survives_replay`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_967_the_checkout_is_verified_before_the_agent.py::test_the_image_manifest_travels_from_the_workspace_to_the_replayed_execution`, and (real store, Docker-backed) `packages/syn-domain/tests/integration/test_1913_the_image_manifest_survives_the_real_store.py::test_the_reading_is_found_on_the_execution_after_a_restart` |
| `06-handler-drops-the-manifest.patch` | `WorkspaceProvisionHandler` does not pass the workspace's reading onto the command | `test_967_the_checkout_is_verified_before_the_agent.py::test_the_image_manifest_travels_from_the_workspace_to_the_replayed_execution` |

The real-store test needs the event store (Docker), so run patch 05 with `docker=true`.

## Added in fix round 1

The VSA events-isolation rule (VSA028) lets an event import only a value-objects module, so `aggregate_execution/image_provenance.py` became `aggregate_execution/ImageManifestValueObjects.py`. Patch 03 targets the old path and no longer applies; it is left in place, unedited, and `07` is the same defect at the new path.

| Patch | Defect | Killing test(s) |
|---|---|---|
| `07-absent-manifest-persisted-as-empty-after-the-move.patch` | patch 03 at the moved path: no manifest file becomes a READ manifest of empty fields | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_1913_image_manifest_reading.py::test_no_manifest_file_is_absent_not_a_manifest_of_empty_fields`, `packages/syn-adapters/tests/workspace_backends/test_1913_image_manifest_through_file_transfer.py::test_an_image_with_no_manifest_is_recorded_absent` |
| `08-generic-event-reading-discarded.patch` | a reading on a generically deserialised event (ADR-023) is dropped on replay | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_1913_image_manifest_reading.py::test_a_generic_stored_reading_replays_typed` |
