# Mutation evidence: feedback screening (plan PR 6, synthetic part)

Each patch puts back the bug that the named tests exist to catch. Run with
`docker=false`, because none of these tests needs Docker.

| Patch | Bug it reintroduces | Test that must fail |
|---|---|---|
| `01-parse-error-defaults-to-clean.patch` | An unparseable model reply becomes `clean` (confidence 1.0) instead of quarantine | `packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_clean_verdict_carrying_an_extra_key_is_still_quarantine`, `packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_malformed_recorded_reply_is_quarantine`, `scripts/tests/test_feedback_screening_bench.py::test_holdout_recorded_scores_to_known_numbers` |
| `02-allow-straddling-group.patch` | `check` accepts a group whose variants sit in more than one split | `scripts/tests/test_feedback_screening_bench.py::test_check_refuses_a_group_that_straddles_splits` |
| `03-coerce-non-numeric-confidence.patch` | A tool input whose confidence is `"0.99"`, `true` or `false` is coerced into a clean number instead of quarantined | `packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_confidence_that_is_not_a_json_number_is_quarantine` |
| `04-discard-unexpected-tool-calls.patch` | A tool call under another name is dropped, so a valid call beside it is read as the reply | `packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_second_tool_call_of_any_name_is_quarantine` |
| `05-decoding-error-escapes.patch` | A reply body httpx cannot decode (corrupt gzip) escapes as a raw `httpx.DecodingError` instead of `ScreeningUnavailableError` | `packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_body_that_fails_decoding_raises_with_its_cause` |
| `06-false-quarantine-ignores-policy.patch` | The bench counts a clean verdict below `open_at` as opened, though `ScreeningPolicy` quarantines it | `scripts/tests/test_feedback_screening_bench.py::test_false_quarantine_counts_a_clean_verdict_the_policy_would_not_open` |

```
just mutation-evidence 2015 "packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_clean_verdict_carrying_an_extra_key_is_still_quarantine packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_malformed_recorded_reply_is_quarantine scripts/tests/test_feedback_screening_bench.py::test_holdout_recorded_scores_to_known_numbers scripts/tests/test_feedback_screening_bench.py::test_check_refuses_a_group_that_straddles_splits packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_confidence_that_is_not_a_json_number_is_quarantine packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_second_tool_call_of_any_name_is_quarantine packages/syn-adapters/src/syn_adapters/feedback_screening/test_anthropic_screener.py::test_a_body_that_fails_decoding_raises_with_its_cause scripts/tests/test_feedback_screening_bench.py::test_false_quarantine_counts_a_clean_verdict_the_policy_would_not_open" false
```

Delete `.mutations/` before merge (the `mutations-not-merged` CI job). Leave
that to the orchestrator: an implementing agent must not delete it (PC-204).
