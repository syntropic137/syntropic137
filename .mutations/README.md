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
| 17-route-ignores-split.patch | `apps/syn-api/src/syn_api/routes/eval_sets.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 18-detail-never-reports-cohorts.patch | `apps/syn-api/src/syn_api/routes/evals.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
| 19-run-row-no-trial-result.patch | `apps/syn-api/src/syn_api/routes/eval_runs.py` | `apps/syn-api/tests/test_2108_eval_set_metrics_over_http.py` | killed |
