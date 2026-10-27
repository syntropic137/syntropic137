# Mutation evidence, #2108 dry-run `--case` (PR #2147)

One bug per patch, against scripts/eval_suite.py (`select_cases`, `--case` in `main`).
Named tests: the dry-run and case-flag tests in scripts/tests/test_eval_suite.py.

| Patch | Bug |
|---|---|
| 01 | an unknown case id is skipped, not refused |
| 02 | narrowing keeps every case |
| 03 | the roster is narrowed too (other cases left unregistered) |
| 04 | `--case` accepted on score and register |
| 05 | `--case` ignored |
| 06 | narrowing ignores `--split` (other split's case accepted) |
