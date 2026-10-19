# Mutation evidence for #2021

All patches touch `scripts/eval_suite.py`. Tests that should kill them (all in `scripts/tests/test_eval_suite.py`):

| Patch | Killing test |
|---|---|
| 01-no-majority-still-credits | `test_a_judge_that_disagrees_with_itself_is_unclear_and_not_caught` |
| 02-quote-check-after-vote-dropped | `test_a_sample_quoting_no_finding_votes_unclear_not_match`, `test_a_match_quoting_text_no_finding_holds_is_unclear` |
| 03-sends-temperature-zero | `test_anthropic_client_sends_the_pinned_5x_model_with_no_sampling_parameter`, `test_the_llm_judge_end_to_end_runs_on_the_5x_api` |
| 04-refusal-scored-as-verdict | `test_a_reply_that_did_not_finish_is_an_error_not_a_verdict` |
| 05-pre5-judge-model | `test_anthropic_client_sends_the_pinned_5x_model_with_no_sampling_parameter`, `test_the_llm_judge_end_to_end_runs_on_the_5x_api`, `test_llm_judged_score_is_recorded_under_the_judges_identity` |
