# #2108 S3 mutation evidence

Each patch re-introduces one bug; the named tests must kill it.

| Patch | Bug | Killed by (scripts/tests/test_eval_suite.py unless noted) |
|---|---|---|
| 32 | register tags despite a split/polarity conflict | test_register_refuses_a_split_or_polarity_the_case_file_disagrees_with |
| 33 | roster omits `split:` | test_register_writes_the_roster_onto_every_case_eval_once |
| 34 | register re-posts tags already present | test_register_writes_the_roster_onto_every_case_eval_once |
| 35 | top-up launches while trials are pending | test_top_up_is_refused_while_the_cohort_has_a_pending_trial |
| 36 | top-up ignores `trials_short` | test_top_up_launches_exactly_the_servers_trials_short |
| 37 | top-up of a never-launched cohort launches | test_top_up_of_a_cohort_that_launched_nothing_is_refused |
| 38 | cohort tags omit `scorer:` | test_launch_trials_starts_k_tagged_trials_per_case_with_one_ledger_line_each |
| 39 | every trial tagged `/1` | test_launch_trials_starts_k_tagged_trials_per_case_with_one_ledger_line_each |
| 40 | score accepts another scorer protocol | test_a_trial_is_scored_under_the_protocol_it_launched_with_and_no_other |
| 41 | pin safety misses `git pull` | test_a_prompt_that_integrates_the_default_branch_is_refused |
| 42 | `--trials` admits model aliases | test_a_model_alias_is_refused_in_a_trials_suite |
| 43 | LLM scorer protocol not tag-safe | test_the_llm_scoring_protocol_is_a_tag_the_server_can_compare |
| 44 | top-up continues a cohort of another scorer protocol | test_top_up_never_continues_a_cohort_scored_under_another_protocol |
| 46 | tagging an unknown eval returns 200 | apps/syn-api/tests/test_2108_eval_tags_over_http.py::test_an_unknown_eval_is_404 |

Retired as equivalent: 45 (route skips `sync_published_events_to_projections`).
The eval read model is not fed by that in-memory dispatch (the tag-filter test
replays the store into `eval_list` explicitly), and in production the call is a
no-op, so removing it changes nothing observable for an eval.
