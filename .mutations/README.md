# Mutation patches for #1743

Every patch is meant to be killed by
`apps/syn-api/tests/test_1743_unpriced_delegate_model_is_observed.py`.

| Patch | Bug re-introduced | Local result (no Docker) |
|---|---|---|
| 01-drop-model-when-unpriced | unpriced row loses its model again | 4/4 tests fail |
| 02-eval-runs-ignore-observed | eval runs read observed models from the cost split only | 2/4 fail |
| 03-page-omits-unpriced | execution page never sets `unpriced_models` | 1/4 fail |
| 04-read-model-drops-on-store | `ExecutionCost.to_dict` omits `observed_models_by_phase` | 3/4 fail |
| 05-observed-only-when-priced | model recorded after the unpriced `continue` (the original #1743 defect) | 4/4 fail |
