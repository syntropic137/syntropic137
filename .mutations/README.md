# Mutation evidence for #1920

Dispatch with docker=true (the integration test needs the ESP event store):

```
just mutation-evidence 1976 "packages/syn-domain/src/syn_domain/contexts/orchestration/slices/create_eval/test_1920_concurrent_keyed_creates_make_one_eval.py::test_two_concurrent_creates_of_one_key_store_one_eval_and_both_get_it packages/syn-domain/src/syn_domain/contexts/orchestration/slices/create_eval/test_1920_concurrent_keyed_creates_make_one_eval.py::test_a_key_names_one_id_and_another_key_another packages/syn-domain/tests/integration/test_1920_keyed_eval_create_real_store.py::test_two_concurrent_launches_store_one_eval_per_case apps/syn-api/tests/test_1920_keyed_eval_create_over_http.py::test_two_creates_with_one_stable_key_answer_with_one_eval" true
```

| Patch | Bug | Meant to kill it |
|---|---|---|
| `01-no-stream-guard-removed.patch` | the create writes with `save` and no longer treats the store's no-stream refusal as "read the winner" | both test_1920 race tests (unit + real store): the losing launch fails instead of getting the eval |
| `02-stream-key-not-derived-from-stable-key.patch` | `EvalId.for_key` mints a random id, so racers write different streams | both race tests and `test_a_key_names_one_id_and_another_key_another`, plus the HTTP test |
| `03-route-ignores-stable-key.patch` | `POST /evals` mints a random id even when `stable_key` is sent | `test_two_creates_with_one_stable_key_answer_with_one_eval` |

Equivalent mutant, deliberately not listed: swapping `save_new` for `save` alone. The SDK's `save`
of a fresh aggregate sends expected version 0, which both the gRPC store and
`MemoryEventStoreClient` treat as "no stream yet", so it survives every test by construction (checked
locally: the unit race test passes with it). The guard is the store's; what this repo owns is the
stream key and the collision branch, which 01 and 02 remove.
