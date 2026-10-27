# Mutation evidence for #2124

Each patch is a mutation of non-test source on the PR head. The runner reads
only `*.patch`; this file maps each one to the tests meant to kill it. Delete
`.mutations/` after the evidence comment reports PASS for the head SHA.

Docker: `false`. Both tests are unit tests on the in-memory store.

| Patch | Mutates | Killed by |
|---|---|---|
| `01-get-returns-live-record.patch` | memory store: `get` returns the stored dict | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory]` |
| `02-get-many-returns-live-records.patch` | memory store: `get_many` returns the stored dicts | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory]` |
| `03-get-all-returns-live-records.patch` | memory store: `get_all` returns the stored dicts | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory]` |
| `04-query-returns-live-records.patch` | memory store: `query` returns the stored dicts | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory]` |
| `05-prefix-returns-shallow-copy.patch` | memory store: `get_by_prefix` back to a shallow copy | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory]` |
| `06-newest-returns-live-values.patch` | memory store: `newest_per_group` returns stored field values | `packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory]` |
| `07-provisioning-forgets-save.patch` | execution detail projection: provisioning handler drops its final `save` (the #2123 mutant, now killed on the plain in-memory store) | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_2108_trial_provenance_reaches_the_read_model.py::test_each_phase_carries_its_latest_image_manifest` |

Dispatch:

```
just mutation-evidence <PR> "packages/syn-adapters/tests/contract/test_projection_store_contract.py::test_an_edit_to_a_record_read_back_is_lost_unless_it_is_saved[memory] packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_2108_trial_provenance_reaches_the_read_model.py::test_each_phase_carries_its_latest_image_manifest" false
```
