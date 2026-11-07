# Mutation patches for #580 (contributor guard)

| Patch | Bug it re-introduces | Tests meant to kill it |
|---|---|---|
| 01-drop-contributor-guard.patch | handler never consults the policy | `test_contributor_guard.py::test_untrusted_contributor_does_not_fire_and_block_is_recorded`, `::test_guard_runs_before_per_trigger_conditions`, `::test_allowlisted_login_fires_and_others_do_not` |
| 02-pipeline-drops-policy.patch | event pipeline (polling path) builds its handler without the policy | `apps/syn-api/tests/test_contributor_guard_wiring.py::test_event_pipeline_applies_configured_mode` |
| 03-webhook-route-drops-policy.patch | webhook route builds its handler without the policy | `apps/syn-api/tests/test_contributor_guard_wiring.py::test_webhook_route_applies_configured_mode` |
| 04-judge-sender-not-author.patch | the sender is judged instead of the content author | `test_contributor_guard.py::test_pr_author_is_judged_not_the_sender`, `::test_comment_author_is_judged_on_an_issue_comment`, `::test_trusted_contributor_fires` |
