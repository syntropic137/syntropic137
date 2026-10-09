# syn-landing

Landing page for [Syntropic137](https://syntropic137.com), the agentic engineering platform.

Moved into the monorepo from `syntropic137/syntropic137-landing-page` with `git subtree` (history kept). The rebuild plan is `design/landing-plan.md`.

## Stack

- **Vite** + **React 19** + **TypeScript**
- Plain CSS (no framework). Design tokens in `src/globals.css` until they move to Skyline (P5 of the plan)
- Fonts: Orbitron (display), Inter (UI), JetBrains Mono (code)

## Local dev (from the repo root)

```bash
pnpm install
just landing-dev
```

## Build

```bash
just landing-build     # outputs to apps/syn-landing/dist/
just landing-preview   # serve the build locally
```

## Tests

```bash
just landing-qa           # copy lint, typecheck, build
just landing-energy       # energy/performance test
just landing-lighthouse   # Lighthouse with the CI minimums
```

CI (`.github/workflows/syn-landing.yml`) runs the copy lint, a Lighthouse audit, the energy test, CodeQL and gitleaks on every PR that touches this app or `packages/syn-ui`. Minimum Lighthouse scores: Performance 90, Accessibility 90, Best Practices 85, SEO 90.

## Deployment

Hosted on Vercel, root directory `apps/syn-landing`. Only the `release` branch deploys; there are no preview deployments.

## Design system

See [`docs/syntropic137-design-system.md`](docs/syntropic137-design-system.md) (points at Skyline).
