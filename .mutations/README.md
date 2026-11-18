# Mutation evidence for #693 (PR #2316)

Each patch re-introduces one bug in production source. The test named beside it must fail with the patch applied.

| Patch | Bug | Killed by |
|---|---|---|
| `01-banner-when-healthy.patch` | The banner shows for any /health answer, including `mode: "full"` | `apps/syn-ui/src/shell/DegradedBanner.svelte.test.ts` > "shows nothing while the instance is fully serving" |
| `02-drop-a-reason.patch` | The banner drops one of the `degraded_reasons` | `apps/syn-ui/src/shell/DegradedBanner.svelte.test.ts` > "lists every reason the API gives, once, as the API names it" |
| `03-shell-drops-banner.patch` | AppShell no longer renders the banner | `apps/syn-ui/src/shell/DegradedBanner.svelte.test.ts` > every case that expects a read or a banner (3 of 4) |

These are vitest tests, and `just mutation-evidence` runs pytest ids. So run them by hand, from the repo root:

```
for p in .mutations/*.patch; do
  git apply "$p" && (cd apps/syn-ui && pnpm vitest run src/shell/DegradedBanner.svelte.test.ts); git checkout -- apps/syn-ui
done
```

Each run must report at least one failed test.
