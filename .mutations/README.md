# Mutation evidence for #897 slice F

Each patch is against the fix commit and puts back a defect the slice removes.
The killers are vitest tests, so the pytest-only trusted runner cannot run them.
Run them locally like this, from `apps/syn-cli-node` (after `pnpm install`):

```
git apply ../../.mutations/<patch>
npx vitest run tests/commands/costs.test.ts tests/commands/events.test.ts
git apply -R ../../.mutations/<patch>
```

| Patch | Bug it puts back | Killed by |
|---|---|---|
| `01-summary-formats-total-cost-usd.patch` | `syn costs summary` formats `total_cost_usd` itself, so partial work reads `$1.25` and unpriced work reads `$0.00` (the bug on main) | `costs.test.ts` > summary total > partial, unpriced |
| `02-summary-drops-unpriced-note.patch` | `syn costs summary` prints the honest total but does not say how many observations had no rate | `costs.test.ts` > summary total > partial, unpriced |
| `03-events-costs-formats-estimated-cost-usd.patch` | `syn events costs` formats `estimated_cost_usd` itself (the bug on main) | `events.test.ts` > costs > partial, unpriced |
| `04-events-costs-drops-unpriced-note.patch` | `syn events costs` drops the unpriced note | `events.test.ts` > costs > partial, unpriced |

Local result, 2026-11-20. Each mutant gives `Tests  2 failed | 26 passed (28)`:

```
== 01-summary-formats-total-cost-usd.patch
       × prints a partial total as partial and names the unpriced count
       × prints an unpriced total as unpriced and names the unpriced count
      Tests  2 failed | 26 passed (28)
== 02-summary-drops-unpriced-note.patch
       × prints a partial total as partial and names the unpriced count
       × prints an unpriced total as unpriced and names the unpriced count
      Tests  2 failed | 26 passed (28)
== 03-events-costs-formats-estimated-cost-usd.patch
       × prints a partial total as partial and names the unpriced count
       × prints an unpriced total as unpriced and names the unpriced count
      Tests  2 failed | 26 passed (28)
== 04-events-costs-drops-unpriced-note.patch
       × prints a partial total as partial and names the unpriced count
       × prints an unpriced total as unpriced and names the unpriced count
      Tests  2 failed | 26 passed (28)
```

The fully priced cases are not meant to kill these patches. They guard the
other direction: no note on a fully priced total.
