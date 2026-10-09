# syntropic137-landing-page

Landing page for [Syntropic137](https://syntropic137.com), the agentic engineering platform.

## Stack

- **Vite** + **React 19** + **TypeScript**
- Plain CSS (no framework). Design tokens in `src/globals.css`
- Fonts: Orbitron (display), Inter (UI), JetBrains Mono (code)

## Local dev

```bash
npm install
npm run dev
```

## Build

```bash
npm run build   # outputs to dist/
npm run preview # serve the build locally
```

## Tests

```bash
npm test              # full Playwright suite
npm run test:energy   # energy/performance test only
```

CI runs a Lighthouse audit on every push and PR. Minimum thresholds: Performance 90, Accessibility 90, Best Practices 85, SEO 90.

## Deployment

Hosted on Vercel. Pushes to `main` deploy automatically.

## Design system

See [`docs/syntropic137-design-system.md`](docs/syntropic137-design-system.md).
