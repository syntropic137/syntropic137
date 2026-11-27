# Mutation patches for #1004 slice 2 (syn-ui execution commits)

vitest, not pytest: the `just mutation-evidence` runner names pytest ids, so these
were run locally by applying each patch and running both suites:

- core: `cd packages/syn-ui/skyline-core && pnpm exec vitest run src/screens/executions/commits.test.ts`
- page: `cd apps/syn-ui && pnpm exec vitest run src/routes/executions/detail.svelte.test.ts`

| Patch | Bug | Killed by |
|---|---|---|
| 01-null-commits-show-nothing | a `null` list renders no line instead of "commit not recorded (older run)" | commits.test.ts "says a run from before capture…"; detail.svelte.test.ts "says the commit was not recorded…" |
| 02-phase-diff-condition-inverted | a phase shows its commit when it matches the run and hides it when it differs | commits.test.ts phaseCommitsView cases; detail.svelte.test.ts "shows a phase checked out at another commit…" |
| 03-sha-truncated-wrongly | the short SHA is 8 characters, not 7 | commits.test.ts "shows the 7-character SHA…"; detail.svelte.test.ts run and phase commit lines |
