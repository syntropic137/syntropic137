# Mutation evidence: PR 4 (agent token cap, 429 mapping)

Each patch re-introduces one bug in production source. All were killed
locally (`git apply` + the named tests) before pushing; the orchestrator
runs the authoritative check. No test needs Docker, so `docker=false`.

| Patch | Bug | Killing test |
|---|---|---|
| 01-actions-not-capped | `actions` passes through at `write` | `packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_a_phase_token_caps_actions_at_read` |
| 02-no-permission-map-full-grant | token minted with no map (the pre-PR full grant) | `packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_a_phase_token_caps_actions_at_read` |
| 03-cap-every-write-like-1197 | every `write` lowered, as #1197 did to `pull_requests` | `packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_every_other_permission_passes_through_unchanged` |
| 04-actions-added-when-not-granted | `actions: read` asked for when the grant lacks it | `packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_actions_is_never_added_when_the_installation_lacks_it` |
| 05-lookup-failure-mints-uncapped | a failed grant lookup falls back to an uncapped token | `packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_no_token_is_minted_when_the_grant_cannot_be_read` |
| 06-429-not-a-rate-limit | 429 stays a generic `GitHubAppError` | `packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_without_any_header_it_is_still_a_rate_limit` |
| 07-retry-after-ignored | `Retry-After` not read | `packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_retry_after_in_seconds_sets_the_reset`, `packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_retry_after_as_an_http_date_sets_the_reset` |
| 08-primary-reset-wins-over-retry-after | `X-RateLimit-Reset` read before `Retry-After` | `packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_retry_after_wins_over_the_primary_limit_reset` |

Node ids for `just mutation-evidence 1998 "<ids>" false`:

```
packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_a_phase_token_caps_actions_at_read packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_every_other_permission_passes_through_unchanged packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_actions_is_never_added_when_the_installation_lacks_it packages/syn-adapters/src/syn_adapters/github/test_agent_token.py::test_no_token_is_minted_when_the_grant_cannot_be_read packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_without_any_header_it_is_still_a_rate_limit packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_retry_after_in_seconds_sets_the_reset packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_retry_after_as_an_http_date_sets_the_reset packages/syn-adapters/tests/github/test_client_api.py::TestA429IsARateLimit::test_retry_after_wins_over_the_primary_limit_reset
```

Delete `.mutations/` before merge (`mutations-not-merged`).
