# #2108 S2 mutation evidence

| Patch | Source | Test that kills it | Local |
|---|---|---|---|
| 01-facts-read-edited-tags.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 02-facts-drop-classification.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 03-facts-drop-checkout.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 04-facts-drop-baseline.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 05-facts-drop-own-models.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 06-facts-drop-images.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 07-projection-overwrites-checkout.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/projection.py` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_2108_trial_provenance_reaches_the_read_model.py` | killed |
| 08-projection-drops-image.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/projection.py` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_2108_trial_provenance_reaches_the_read_model.py` | killed |
| 09-projection-no-save-without-row.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/projection.py` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_2108_trial_provenance_reaches_the_read_model.py` | killed |
| 10-detail-drops-checkout.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/workflow_execution_detail.py` | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_2108_trial_provenance_reaches_the_read_model.py` | killed |
| 11-declared-conflict-picks-one.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_trials.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 12-roster-ignores-declared-tags.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_sets.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 13-images-count-excluded-runs.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_sets.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 14-pair-any-two-or-more.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_set_comparison.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 15-route-n-counts-infra.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 16-route-drops-comparison.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 18-detail-never-reports-cohorts.patch | `apps/syn-api/src/syn_api/routes/evals.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 19-run-row-no-trial-result.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 20-model-tag-split-on-equals.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_trials.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 21-models-digest-full-length.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_trials.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 22-read-scope-omits-eval-sets.patch | `packages/syn-adapters/src/syn_adapters/platform_access/__init__.py` | `apps/syn-api/tests/test_1744_workspace_platform_eval_scope.py` | killed |
| 23-set-case-limit-unchecked.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 24-set-run-limit-unchecked.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 25-eval-run-limit-unchecked.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 26-model-tag-not-encoded.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_trials.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 27-model-tag-not-decoded.patch | `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/read_models/eval_trials.py` | `packages/syn-domain/tests/contexts/orchestration/test_2108_declared_models_and_images.py` | killed |
| 28-eval-refuses-after-summary.patch | `apps/syn-api/src/syn_api/routes/evals.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 29-set-reads-every-score.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 30-summary-reads-every-score.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 31-split-not-in-roster-query.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |

Retired: 17-route-ignores-split (dropped `split` from the `roster_of` call). Equivalent since codex pass 2 moved `split:` into the roster tag query: the query already returns only that split, so the mutant survives every test (CI run 40455366408). 31-split-not-in-roster-query covers the split path.
