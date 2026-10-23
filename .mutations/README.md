# Mutation evidence for #1605

Each patch puts back one bug. The test that should kill it is listed beside it. All tests are in
`packages/syn-domain/tests/contexts/workflows/execute_workflow/test_1605_harness_classified_upstream_failures.py`.

| Patch | Bug | Killing test |
|---|---|---|
| `1605-01-quota-retried.patch` | QUOTA counted as transient, so it is retried | `TestAClaudeWeeklyLimit::test_a_claude_weekly_limit_is_not_retried_and_says_when_it_resets` |
| `1605-02-resets-at-dropped.patch` | the adapter drops `resets_at`, so the error says "an unstated time" | `TestAClaudeWeeklyLimit::test_a_claude_weekly_limit_is_not_retried_and_says_when_it_resets`, `test_the_year_is_placed_by_the_reading` |
| `1605-03-quota-defaults-to-unknown.patch` | the QUOTA case is replaced by a default branch returning UNKNOWN | `TestAClaudeWeeklyLimit::test_a_claude_weekly_limit_runs_the_fallback`, `TestAClaudeWeeklyLimit::test_a_claude_weekly_limit_is_not_retried_and_says_when_it_resets` |
| `1605-04-429-message-dropped.patch` | a 429 body's message is dropped for its status again, so a weekly limit inside one reads as a retried rate limit | `TestAWeeklyLimitInsideA429::test_it_is_a_quota_not_retried_and_says_when_it_resets`, `TestAWeeklyLimitInsideA429::test_it_runs_the_fallback` |
