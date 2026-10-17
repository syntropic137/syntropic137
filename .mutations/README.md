# Mutation evidence: #1631 (PR #2016)

Patches mutate `scripts/ts_comments.py` only (the runner refuses `ci/`).
Run with no Docker needed:

```
just mutation-evidence 2016 "ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-url] ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-condition-regex] ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-jsx-url] scripts/tests/test_ts_comments.py::test_comments_are_blanked scripts/tests/test_ts_comments.py::test_literals_and_operators_are_code scripts/tests/test_ts_comments.py::test_division_after_a_postfix_operator_or_call_does_not_start_a_regex scripts/tests/test_ts_comments.py::test_jsx_text_is_prose_and_the_code_after_it_is_kept scripts/tests/test_ts_comments.py::test_comments_in_jsx_expressions_and_after_elements_are_blanked" false
```

| Patch | Bug re-introduced | Tests that must fail |
|---|---|---|
| `01-no-comment-stripping.patch` | `blank_ts_comments` returns the source unchanged (the pre-#1631 gate) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation[line-comment]`, `ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation[block-comment]`, `scripts/tests/test_ts_comments.py::test_comments_are_blanked` |
| `02-strings-not-tokenized.patch` | quotes are not tokenized, so `'https://x'` reads as a `//` comment (the naive strip) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-url]`, `scripts/tests/test_ts_comments.py::test_literals_and_operators_are_code[url-in-string]` |
| `03-condition-paren-is-an-operand.patch` | the `)` of an `if`/`while` condition is read as an operand, so the regex after it is division (verify R1) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-condition-regex]`, `scripts/tests/test_ts_comments.py::test_literals_and_operators_are_code[regex-after-if-condition]`, `scripts/tests/test_ts_comments.py::test_literals_and_operators_are_code[regex-after-condition-in-template-expression]` |
| `04-postfix-not-tracked.patch` | a postfix `++`/`--` is not an operand end, so the division after it opens a regex (verify R2) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation[after-postfix-division]`, `scripts/tests/test_ts_comments.py::test_division_after_a_postfix_operator_or_call_does_not_start_a_regex[postfix-increment]`, `scripts/tests/test_ts_comments.py::test_division_after_a_postfix_operator_or_call_does_not_start_a_regex[postfix-decrement]` |
| `05-jsx-not-recognised.patch` | JSX elements in `.tsx` are not recognised, so their text is read as code (verify R3) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-jsx-url]`, `ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation[after-jsx-apostrophe]`, `scripts/tests/test_ts_comments.py::test_jsx_text_is_prose_and_the_code_after_it_is_kept[url-text]` |

Verified locally (each patch applied one at a time on the fix head, the named tests went red).
Delete `.mutations/` only after the runner's evidence comment exists (PC-204).
