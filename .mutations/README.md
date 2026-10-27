# Mutation evidence, #2108 S5 (PR #2142)

One bug per patch, against scripts/eval_suite.py (PanelJudge, judge allow-lists).
Named tests: the panel and judge-construction tests in scripts/tests/test_eval_suite.py.

| Patch | Bug |
|---|---|
| 01 | a panel split is not `unclear` (one family alone credits) |
| 02 | an agreeing panel always says `match` |
| 03 | protocol identity omits the codex model |
| 04 | protocol identity omits the prompt version |
| 05 | panel accepts a non-codex second member |
| 06 | panel accepts a non-Claude first member |
| 07 | LlmJudge default allow-list admits codex ids (Claude transport) |
| 08 | require_judge_model ignores the caller's allow-list |
| 09 | a split quotes a member's finding |
