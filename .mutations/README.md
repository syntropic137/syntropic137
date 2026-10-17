# Mutation evidence for #1637

Each patch applies to the PR head and re-introduces one way the hour-24 rule
can be wrong. The tests use a parser double that accepts every string, so they
fail on the pinned Python 3.12 as well as on 3.14.

| Patch | Bug it re-introduces | Tests meant to kill it |
|---|---|---|
| `01-drop-hour-24-rule.patch` | Removes the explicit hour-24 refusal, leaving the decision to the interpreter's `fromisoformat` | `test_hour_24_names_no_instant_whatever_the_parser_accepts` (all 15 cases) |
| `02-ignore-digit-run-parity.patch` | Locates the time in a basic week date (`YYYYWww…`) without CPython's digit-run parity rule | `test_hour_24_names_no_instant_whatever_the_parser_accepts[2026W40124:00]`, `test_the_hour_24_rule_leaves_other_24s_to_the_parser[2026W0151240]`, `test_a_digit_separator_is_not_mistaken_for_the_hour` |
| `03-digit-separator-exempts-hour-24.patch` | The verified defect: a digit separator (`2026-10-01224:00`) slips past the rule | `test_hour_24_names_no_instant_whatever_the_parser_accepts` (the five digit-separator cases) |

All tests are in `packages/syn-domain/tests/test_pagination.py`. Node ids for
`just mutation-evidence` (no Docker needed, so `false`):

```
just mutation-evidence 2014 "packages/syn-domain/tests/test_pagination.py::test_hour_24_names_no_instant_whatever_the_parser_accepts packages/syn-domain/tests/test_pagination.py::test_the_hour_24_rule_leaves_other_24s_to_the_parser packages/syn-domain/tests/test_pagination.py::test_a_digit_separator_is_not_mistaken_for_the_hour" false
```

Observed locally on Python 3.12.13: patch 01 fails 15 cases, patch 02 fails 3,
patch 03 fails 5. Delete `.mutations/` before merge (`mutations-not-merged`).
