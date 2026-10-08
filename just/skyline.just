# Skyline: the Svelte 5 UI (apps/syn-ui + packages/syn-ui/*).
# Conventions and file ownership: packages/syn-ui/CONVENTIONS.md

_skyline := "pnpm --filter syn-ui --filter './packages/syn-ui/*'"

# Install workspace dependencies (shared pnpm workspace)
skyline-install:
    pnpm install

# Type-check every Skyline package and the app (tsc / svelte-check, CSS token gate,
# theme parity, token usage), then the plain typecheck the build runs first
skyline-check:
    {{_skyline}} --workspace-concurrency=1 run check
    {{_skyline}} run typecheck
    just skyline-verify-contracts

# The published @syntropic137/design-contracts gate against skyline-svelte-v5:
# A tokens present, B no colour literals in src CSS, C contract conformance
# (the package typecheck), D src/contract-adapter.ts exports the adapter
skyline-verify-contracts:
    pnpm --filter @syn137/skyline-core exec design-system-verify \
      --root "{{justfile_directory()}}" \
      --package packages/syn-ui/skyline-svelte-v5 \
      --tokens packages/syn-ui/themes/node_modules/@syntropic137/design-tokens/generated/design-tokens.css \
      --typecheck "pnpm --filter @syn137/skyline-svelte-v5 run typecheck"

# Run Skyline unit tests (skyline-core, syn-ui-data, app router)
skyline-test:
    {{_skyline}} run test

# Production build of apps/syn-ui with the 100 KB first-load size budget
skyline-build:
    pnpm --filter syn-ui run build

# Everything CI should run for Skyline
skyline-qa: skyline-check skyline-test skyline-build

# Dev server against the API proxy (http://127.0.0.1:9137)
skyline-dev:
    pnpm --filter syn-ui run dev

# Dev server with fixtures: every screen renders with no backend
skyline-dev-fixtures:
    pnpm --filter syn-ui run dev:fixtures
