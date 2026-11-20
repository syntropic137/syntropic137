# Mutation evidence: #897 slice D (PR #2332)

Each patch puts back one bug that the new tests should catch. The trusted runner (`mutation-evidence.yml`) runs pytest only, so it cannot run these vitest tests. The command and the local results are recorded below instead.

| Patch | Bug it reintroduces | Killed by |
|---|---|---|
| `01-repo-cost-formats-usd.patch` | `syn repo cost` formats `total_cost_usd` again | `tests/commands/repo.test.ts` > cost > partial, unpriced |
| `02-system-cost-formats-usd.patch` | `syn system cost` formats `total_cost_usd` again | `tests/commands/system.test.ts` > cost > partial, unpriced |
| `03-drop-unpriced-note.patch` | `printUnpricedNote` never prints the incomplete-total line | repo, system and insights `cost` partial and unpriced tests |

## Command (run from the repo root)

```
cd apps/syn-cli-node && pnpm install --frozen-lockfile
for p in ../../.mutations/*.patch; do git apply "$p"; \
  pnpm exec vitest run tests/commands/repo.test.ts tests/commands/system.test.ts tests/commands/insights.test.ts tests/commands/costs.test.ts; \
  git apply -R "$p"; done
```

## Local result (2026-11-20, head 932e308)

- Baseline: `Tests  38 passed (38)`
- 01: `Tests  2 failed | 36 passed (38)`. The failures are the repo `cost` partial and unpriced tests.
- 02: `Tests  2 failed | 36 passed (38)`. The failures are the system `cost` partial and unpriced tests.
- 03: `Tests  6 failed | 32 passed (38)`. The failures are the insights, repo and system `cost` partial and unpriced tests.

The fully-priced test is not expected to kill 01 or 02. On a fully-priced response, `formatCost("1.25")` and `total_cost_display` are both `$1.25`. That test guards the other direction: no note on a complete total.
