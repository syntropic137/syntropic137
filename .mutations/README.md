# Mutation patches for #1661 slice 4 (ntfy lifecycle sink)

Tests: `packages/syn-adapters/src/syn_adapters/execution_lifecycle/test_ntfy_sink.py`

| Patch | Bug | Killed by |
|---|---|---|
| `01-failed-priority-dropped.patch` | a failed notice publishes at default priority | `test_publishes_one_line_shaped_by_the_outcome[failed]` |
| `02-non-2xx-treated-as-delivered.patch` | a non-2xx is treated as delivered | `test_a_non_2xx_leaves_the_notice_owed` |
| `03-token-sent-when-none.patch` | an `Authorization` header is sent with no token | `test_the_token_is_sent_as_a_bearer_only_when_given` |
