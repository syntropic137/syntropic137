# Mutation evidence for #1661 slice 2b-i (WebhookExecutionLifecycleSink)

Test file: `packages/syn-adapters/src/syn_adapters/execution_lifecycle/test_webhook_sink.py`
(no Docker needed, so dispatch with `docker=false`).

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| `01-sign-other-bytes.patch` | signs a re-serialisation of the notice (`indent=1`), not the bytes that were sent | `test_posts_the_notice_keyed_and_signed_over_the_received_bytes` |
| `02-non-2xx-delivered.patch` | treats any status below 500 (so a 404) as delivered | `test_a_non_2xx_leaves_the_notice_owed[404]` |

Both were killed in a local workspace run. That is not trusted evidence: the
trusted run is `just mutation-evidence <pr> "<ids>" false`.
