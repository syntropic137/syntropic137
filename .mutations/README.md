# Mutation evidence for #2021: the judge runs through Claude Code

All patches touch `scripts/eval_suite.py` (`ClaudeCode`). Tests that should kill them (all in `scripts/tests/test_eval_suite.py`):

| Patch | Killing test |
|---|---|
| 01-cli-gets-model-alias | `test_claude_code_runs_the_cli_headless_with_the_exact_pinned_model`, `test_the_llm_judge_end_to_end_runs_through_claude_code` |
| 02-stdin-left-open | `test_claude_code_closes_stdin_and_passes_its_timeout`, `test_the_llm_judge_end_to_end_runs_through_claude_code` |
| 03-nonzero-exit-swallowed | `test_every_claude_code_failure_raises_its_own_error[exit]`, `test_a_failed_claude_code_call_fails_the_judgement_rather_than_voting` |
| 04-is-error-swallowed | `test_every_claude_code_failure_raises_its_own_error[is-error]` |
