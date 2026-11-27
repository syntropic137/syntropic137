# Mutation patches for #1004 slice 2 (syn-ui execution commits)

vitest, not pytest: the `just mutation-evidence` runner names pytest ids, so these
were run locally by applying each patch and running both suites:

- core: `cd packages/syn-ui/skyline-core && pnpm exec vitest run src/screens/executions/commits.test.ts`
- page: `cd apps/syn-ui && pnpm exec vitest run src/routes/executions/detail.svelte.test.ts`

| Patch | Bug | Killed by |
|---|---|---|
| 01-null-commits-show-nothing | a `null` list renders no line instead of "commit not recorded (older run)" | commits.test.ts null run and ran-without-recording phase; detail.svelte.test.ts completed phase with null commits, and older run |
| 02-phase-diff-condition-inverted | a phase shows the repositories that match the run and hides the ones that differ | commits.test.ts phaseCommitsView cases, including the per-repository invariant; detail.svelte.test.ts "shows a phase checked out at another commit…" |
| 03-sha-truncated-wrongly | the SHA is cut to 7 characters in the frontend instead of shown raw until the API has a `sha_display` (#897) | commits.test.ts "shows the SHA raw…" and phase cases; detail.svelte.test.ts run and phase commit lines |
