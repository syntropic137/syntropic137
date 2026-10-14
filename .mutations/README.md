# Mutation evidence inputs (#1735 S2)

`mutation-evidence.yml` reads these files. Each `*.patch` is a unified diff
against the PR head. It changes exactly one behavioural SOURCE line, the one a
finding named, and never a test file. A patch is "killed" only if at least one
of its expected node ids fails with the patch applied, and all of them pass
without it.

What counts as source:

- `packages/syn-adapters/src/syn_adapters/workspace_backends/service/github_presentation.py`
  is production. It is the only thing that provisions the sandbox.
- `packages/syn-adapters/tests/integration/github_broker/authorizer.py` is
  harness source. It stands in for docker/token-injector, which PR 4 builds.
  It is not a `test_*.py` module.

## `tests` input

```
packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_clone_fetch_push_via_insteadof_carry_the_repos_real_token packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_unauthenticated_git_request_gets_the_basic_challenge packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_submodules_with_and_without_dot_git_get_their_own_tokens packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_an_ungranted_repository_is_offered_nothing packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_a_valid_capability_opens_only_the_repositories_it_was_granted packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_gh_reaches_github_with_the_real_gh_token packages/syn-adapters/tests/integration/github_broker/test_git_gh_through_broker.py::test_sandbox_files_and_env_hold_capabilities_never_real_tokens packages/syn-adapters/tests/workspace_backends/service/test_github_presentation.py::test_git_offers_nothing_for_a_repo_outside_the_grant
```

A bare function id selects every parametrization:
`[granted]`/`[ungranted]`, and the five gh cases `[pr_create_no_git_tree]`,
`[repo_less_issue_list]`, `[explicit_github_url]`, `[api_graphql]` and
`[api_rest]`. The integration module is skipped without Docker, so it only
produces evidence in CI.

## Patch -> node ids expected to fail

Below, `I::` is `.../integration/github_broker/test_git_gh_through_broker.py::`
and `U::` is `.../workspace_backends/service/test_github_presentation.py::`.

"Unit, observed" means the failure was seen locally with the patch applied, and
the clean head passed. "Integration, expected" is the claim CI tests: none of
those were run locally.

| Patch | Line it changes | Integration, expected (in `tests`) | Unit, observed |
|---|---|---|---|
| `insteadof-removed.patch` | `provisioned_remote_settings`: the `url.<broker>.insteadOf` settings | `I::test_clone_fetch_push_via_insteadof_carry_the_repos_real_token`, `I::test_submodules_with_and_without_dot_git_get_their_own_tokens` | `U::test_every_github_remote_spelling_resolves_to_the_broker[*]` (3), `U::test_hardened_git_settings_are_the_ones_the_setup_writes` |
| `git-credentials-removed.patch` | `present_github`: the `.git-credentials` file | `I::test_clone_fetch_push_via_insteadof_carry_the_repos_real_token`, `I::test_submodules_with_and_without_dot_git_get_their_own_tokens`, `I::test_sandbox_files_and_env_hold_capabilities_never_real_tokens` (no `.git-credentials` in CAPS) | `U::test_git_offers_the_capability_for_granted_repos_in_both_spellings[*]` (4) |
| `git-challenge-401-becomes-403.patch` | `authorizer._git`: the challenge status | `I::test_unauthenticated_git_request_gets_the_basic_challenge`, `I::test_clone_fetch_push_via_insteadof_carry_the_repos_real_token`, `I::test_submodules_with_and_without_dot_git_get_their_own_tokens` | none (the broker is not under unit test) |
| `git-challenge-www-authenticate-removed.patch` | `authorizer._git`: the `WWW-Authenticate: Basic` header | `I::test_unauthenticated_git_request_gets_the_basic_challenge` (prints `401 None`). Clone and submodules are expected to fail as well, because git offers the credential only after the challenge (`github_presentation` docstring). That second claim is the one this patch tests. | none |
| `submodule-sub-b-given-sub-a-token.patch` | `authorizer._git`: the per-repo token lookup, keyed so `o/sub-b` gets `o/sub-a`'s token | `I::test_submodules_with_and_without_dot_git_get_their_own_tokens` | none |
| `gh-capability-corrupted.patch` | `present_github`: `oauth_token` in `hosts.yml` (reversed) | `I::test_gh_reaches_github_with_the_real_gh_token[*]` (5), `I::test_sandbox_files_and_env_hold_capabilities_never_real_tokens` (no `hosts.yml` in CAPS) | `U::test_gh_is_given_the_capability_on_github_com_and_no_host_override` |
| `broker-ca-corrupted.patch` | `present_github`: the broker CA file's contents (no longer PEM) | `I::test_gh_reaches_github_with_the_real_gh_token[*]` (5) | `U::test_the_broker_ca_lands_in_the_directory_ssl_cert_dir_names` |
| `ssl-cert-dir-removed.patch` | `present_github`: the `SSL_CERT_DIR` env | `I::test_gh_reaches_github_with_the_real_gh_token[*]` (5) | `U::test_gh_is_given_the_capability_on_github_com_and_no_host_override`, `U::test_the_broker_ca_lands_in_the_directory_ssl_cert_dir_names` |
| `broker-git-grants-any-repo.patch` | `authorizer._git`: the `token is None` deny (the round-3 broker-deny gap) | `I::test_a_valid_capability_opens_only_the_repositories_it_was_granted[ungranted]` | none |
| `hosts-yml-plants-ghs-token.patch` | `present_github`: `hosts.yml` gains an invented `ghs_` value | `I::test_sandbox_files_and_env_hold_capabilities_never_real_tokens` (caught only by the shape regex, because the value is in no `REAL_TOKENS`) | none |
| `credential-use-http-path-removed.patch` | `provisioned_remote_settings`: `credential.<broker>.useHttpPath` | none expected. The broker still denies `o/unlisted`, so `I::test_an_ungranted_repository_is_offered_nothing` should still pass. | `U::test_git_offers_nothing_for_a_repo_outside_the_grant`, `U::test_hardened_git_settings_are_the_ones_the_setup_writes` |

Mutation 7 in the brief named two alternatives, so it is two patches here. The
last patch was not in the brief. It exists because
`U::test_git_offers_nothing_for_a_repo_outside_the_grant` is in `tests`, and
none of the other ten patches fails it. Without the extra patch, that id would
be listed but would never kill anything.

`I::test_an_ungranted_repository_is_offered_nothing` is not expected to fail
under any patch. Under `credential-use-http-path-removed` the client offers the
capability for `o/unlisted`, but the broker refuses it, so nothing reaches
GitHub. The test asserts on what reaches GitHub, so it cannot tell the client
side's scoping from the broker's.

## Verifying a patch by hand

```
git apply --check .mutations/<name>.patch
git apply .mutations/<name>.patch && uv run pytest <node ids>; git apply -R .mutations/<name>.patch
```
