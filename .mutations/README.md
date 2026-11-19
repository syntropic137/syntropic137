# Mutation evidence: #897 slice B (`syn insights cost`)

Both patches mutate `apps/syn-cli-node/src/commands/insights.ts`. The killing
tests are vitest tests, and the trusted runner (`mutation-evidence.yml`) is
pytest-only, so it cannot run them. The local evidence is below.

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-bare-formatcost-total.patch` | prints `formatCost(d.total_cost_usd)` again | `cost prints a partial total as partial ...` and `cost prints an unpriced total as unpriced ...` |
| `02-drop-unpriced-count-line.patch` | drops the unpriced-count line | the same two tests (the `had no rate` assertions) |

The fully-priced case does not kill patch 01. It can't: for a fully priced
total, `formatCost("1.25")` and the API's `"$1.25"` are the same string.

## Exact command

From the repo root, apply one patch at a time:

```
git apply .mutations/01-bare-formatcost-total.patch
(cd apps/syn-cli-node && pnpm exec vitest run tests/commands/insights.test.ts)
git checkout -- apps/syn-cli-node/src/commands/insights.ts
```

## Observed locally (2026-11-19, branch feat/897-cli-insights-cost-display)

Unmutated: `Tests  7 passed (7)`

Patch 01:
```
     × cost prints a partial total as partial and names the unpriced count 10ms
     × cost prints an unpriced total as unpriced and names the unpriced count 4ms
      Tests  2 failed | 5 passed (7)
```

Patch 02:
```
     × cost prints a partial total as partial and names the unpriced count 13ms
     × cost prints an unpriced total as unpriced and names the unpriced count 4ms
      Tests  2 failed | 5 passed (7)
```
