# Mutation patches for #1569 part 2

| Patch | Bug it re-introduces | Tests meant to kill it |
|---|---|---|
| `01-drop-streak-comparison.patch` | `should_refuse` drops `streak.length < threshold`, so every streak is refused | `test_refusal.py::TestShouldRefuse::test_below_the_threshold_is_not_refused`, `test_1569_a_failure_streak_refuses_trigger_dispatch.py::test_below_the_threshold_a_trigger_dispatches`, `::test_a_completion_lets_triggers_dispatch_again` |
| `02-ignore-dispatch-refusal.patch` | the trigger dispatcher reads the refusal and dispatches anyway | `test_1569_a_failure_streak_refuses_trigger_dispatch.py::test_at_the_threshold_a_trigger_is_refused_with_the_reason`, `::test_a_refused_trigger_is_not_offered_again`, `::test_a_completion_lets_triggers_dispatch_again` |
