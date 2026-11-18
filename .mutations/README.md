# Mutation evidence for #1003

Tests: `apps/syn-api/tests/test_1003_a_trigger_with_an_unresolvable_skill_fails.py`

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-trigger-path-skips-skill-preflight.patch` | `BackgroundWorkflowDispatcher._accept` no longer runs the skill preflight, so the trigger is handed to a task as before | `test_fails_with_the_resolvers_message_and_starts_nothing` |
| `02-refused-trigger-marked-dispatched.patch` | `_dispatch_record` catches the refusal but records the trigger `dispatched` and counts it processed | `test_fails_with_the_resolvers_message_and_starts_nothing` |

Both were killed in a local run before pushing (no Docker needed: `docker=false`).
In both, the test fails first on the status (`'dispatched' == 'failed'`). For
`01`, the handler double's `handle()` returns normally, so the record reaches
`dispatched` and the execution service is called (`handled == 1`).
