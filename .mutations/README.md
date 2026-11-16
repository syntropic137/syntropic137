# Mutation evidence for #2303

Tests: `packages/syn-adapters/tests/test_2303_deregistered_repo_leaves_its_organization.py`
(both tests, docker not needed: `just mutation-evidence <pr> "<ids>" false`).

| Patch | Bug re-introduced | Expected |
|---|---|---|
| `01-org-list-drops-repo-deregistered-subscription.patch` | `OrganizationListAdapter` no longer subscribes to `organization.RepoDeregistered` | killed (both tests: `(2, 1) == (1, 1)`) |
| `02-org-projection-drops-repo-deregistered-alias.patch` | `OrganizationProjection.on_repo_deregistered` alias removed, so dispatch finds no handler | killed (both tests: `(2, 1) == (1, 1)`) |

Both were run locally in the agent workspace and killed both tests. Trusted
evidence is the `mutation-evidence.yml` run on the PR head.
