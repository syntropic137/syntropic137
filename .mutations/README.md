# Mutation evidence for #2036 (LLM judge on agentic-workspace `ClaudeHeadless`)

Every patch mutates `scripts/eval_suite.py`. Each one names the tests in
`scripts/tests/test_eval_suite.py` that are meant to kill it.

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-transport-error-swallowed-into-verdict.patch` | `HeadlessJudgeClient` turns an AW `ClaudeHeadlessError` (or `OSError`) into a default `no_match` reply instead of raising | `test_every_transport_failure_is_a_judge_error_with_its_cause` |
| `02-alias-passed-through-unpinned.patch` | `HeadlessJudgeClient.complete` drops `require_judge_model`, so an alias or a pre-5 id reaches the transport | `test_a_pre5_model_passed_to_the_client_is_refused_before_any_call` |
| `03-wiring-builds-a-local-subprocess.patch` | the production default transport is a local `claude -p` subprocess, not AW's `ClaudeHeadless` | `test_score_llm_judge_runs_on_agentic_workspaces_claude_headless`, `test_calibration_wiring_runs_on_agentic_workspaces_claude_headless` |
| `04-failed-sample-ignored-in-vote.patch` | `LlmJudge.judge` skips a sample whose call failed and votes on the rest | `test_one_failed_sample_fails_the_judgement_rather_than_voting` |
| `05-score-main-discards-the-judge.patch` | `score --llm-judge` builds the judge but scores with `llm=None`, so LLM judging silently never runs (reverify finding B2) | `test_score_main_posts_the_llm_judges_majority_verdict`, `test_a_transport_failure_aborts_the_entry_point_without_a_verdict` |

Run on the orchestrator (none of these tests needs Docker):

```
just mutation-evidence 2036 "scripts/tests/test_eval_suite.py::test_every_transport_failure_is_a_judge_error_with_its_cause scripts/tests/test_eval_suite.py::test_a_pre5_model_passed_to_the_client_is_refused_before_any_call scripts/tests/test_eval_suite.py::test_score_llm_judge_runs_on_agentic_workspaces_claude_headless scripts/tests/test_eval_suite.py::test_calibration_wiring_runs_on_agentic_workspaces_claude_headless scripts/tests/test_eval_suite.py::test_one_failed_sample_fails_the_judgement_rather_than_voting scripts/tests/test_eval_suite.py::test_score_main_posts_the_llm_judges_majority_verdict scripts/tests/test_eval_suite.py::test_a_transport_failure_aborts_the_entry_point_without_a_verdict" false
```
