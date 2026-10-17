# Mutation evidence for #1637

| Patch | Bug it re-introduces | Tests meant to kill it (on the pinned Python 3.12) |
|---|---|---|
| `01-drop-hour-24-rule.patch` | Removes the explicit hour-24 refusal, leaving the decision to the interpreter's `fromisoformat` | `packages/syn-domain/tests/test_pagination.py::test_hour_24_names_no_instant_whatever_the_parser_accepts` |

Node ids for `just mutation-evidence` (no Docker needed, so `false`):

```
just mutation-evidence 2014 "packages/syn-domain/tests/test_pagination.py::test_hour_24_names_no_instant_whatever_the_parser_accepts" false
```

Observed locally on Python 3.12.13 with the patch applied: all 7 parametrised cases of that test fail.
Delete `.mutations/` before merge (`mutations-not-merged`).
