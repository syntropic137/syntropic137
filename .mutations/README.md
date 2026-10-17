# Mutation evidence: #1631 (PR #2016)

Patches mutate `scripts/ts_comments.py` only (the runner refuses `ci/`).
Run with no Docker needed:

```
just mutation-evidence 2016 "ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-url] scripts/tests/test_ts_comments.py::test_comments_are_blanked scripts/tests/test_ts_comments.py::test_literals_and_operators_are_code[url-in-string]" false
```

| Patch | Bug re-introduced | Tests that must fail |
|---|---|---|
| `01-no-comment-stripping.patch` | `blank_ts_comments` returns the source unchanged (the pre-#1631 gate) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation[line-comment]`, `ci/fitness/code_quality/test_harness_format_boundary.py::test_marker_in_a_comment_is_not_a_violation[block-comment]`, `scripts/tests/test_ts_comments.py::test_comments_are_blanked` |
| `02-strings-not-tokenized.patch` | quotes are not tokenized, so `'https://x'` reads as a `//` comment (the naive strip) | `ci/fitness/code_quality/test_harness_format_boundary.py::test_planted_violation_is_caught[vendor-parsing-client-after-url]`, `scripts/tests/test_ts_comments.py::test_literals_and_operators_are_code[url-in-string]` |

Verified locally (both patches applied one at a time, the named tests went red).
Delete `.mutations/` only after the runner's evidence comment exists (PC-204).
