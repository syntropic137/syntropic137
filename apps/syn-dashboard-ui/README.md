# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

## Screenshots for UI verification

`scripts/screenshot.mjs` takes a full-page PNG of a URL with headless Chromium,
so a verify phase can look at a UI change instead of a human doing it:

```bash
pnpm install --frozen-lockfile && pnpm build
pnpm preview --port 4173 --strictPort &      # serves dist/
until curl -sf http://localhost:4173/ >/dev/null; do sleep 1; done
node scripts/screenshot.mjs http://localhost:4173/ /workspace/artifacts/output/landing.png
node scripts/screenshot.mjs http://localhost:4173/executions out.png --viewport 390x844
```

It prints the PNG's real dimensions and byte size, the HTTP status and the page
title. It exits 2 on bad arguments (including a zero viewport dimension) and 1
when the page answers with an HTTP error status (the PNG is still written, as a
diagnostic), so a verify phase can gate on the exit code.

- **No project dependency.** It loads the globally installed `playwright`. The
  agent workspace image (toolchain 1.5.0 and later, agentic-workspace #33)
  bakes Playwright 1.63.0 with its matching headless Chromium, offline, at
  `$PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright`; no `playwright install` is
  needed there. A Playwright pinned here at another version would look for a
  browser the image does not have. Elsewhere:
  `npm i -g playwright@1.63.0 && playwright install chromium`.
- **Never commit the PNG.** In an agent run, write it to
  `/workspace/artifacts/output/`, which is collected with the phase, and
  describe it (dimensions, size, what it shows) in the PR body.
- Without a reachable API the pages render their shell with loading or empty
  states. That still proves layout and routing, not data. To show data, pass
  `--fixtures <file.json>`: a JSON object mapping request pathnames
  (`"/api/v1/workflows/wf-1"`) to response bodies; any other `/api/` request
  answers 404. Add `--expand` to open every `<details>` first, so collapsed
  content is in the shot.

### Populated pages: the checked-in fixture world

`fixtures/screenshot.json` is one coherent API world, ready for `--fixtures`:
a workflow, three executions (completed with two priced models and one
unpriced, failed, running), their six sessions, a markdown and a PNG artifact,
dashboard metrics, and everything the app shell asks for. To screenshot a
populated page:

```bash
pnpm build
pnpm preview --port 4173 --strictPort &
until curl -sf http://localhost:4173/ >/dev/null; do sleep 1; done
node scripts/screenshot.mjs http://localhost:4173/executions/exec-0c5d1e7a out.png \
  --viewport 1280x800 --fixtures fixtures/screenshot.json
```

Build in the foreground and background only the preview: `pnpm build &&
pnpm preview &` backgrounds the build too, and the screenshot then races a
server that has not started. The `until` line waits for it to answer.

| Page | URL path |
| --- | --- |
| Dashboard | `/` |
| Executions | `/executions` |
| Execution: completed / failed / running | `/executions/exec-0c5d1e7a`, `/executions/exec-1f9b2c40`, `/executions/exec-2a7e4d93` |
| Sessions, and one session | `/sessions`, `/sessions/sess-plan-0c5d` |
| Workflows, and the workflow | `/workflows`, `/workflows/wf-sdlc-implement` |
| Artifacts: markdown / PNG | `/artifacts`, `/artifacts/art-plan-md`, `/artifacts/art-dashboard-png` |

- **Never edit the JSON.** Its source is `src/fixtures/screenshotFixtures.ts`,
  typed route by route from `src/generated/api-types.ts`, so a body that stops
  matching the API fails `tsc -b`. After changing it, or after `pnpm
  generate:types`, run `pnpm fixtures:screenshot`. `pnpm test` fails when the
  JSON is stale, or when a fixture answers a route `apps/syn-docs/openapi.json`
  does not serve.
- **What it cannot show.** `screenshot.mjs` matches the pathname only, so a
  list returns the same rows for every filter, time window and page. Event
  streams (`/sse/...`) and `/artifacts/{id}/raw` are not JSON and answer 404:
  pages show "offline" or "connecting", and the PNG artifact has no image.
  Timestamps are fixed (2026-11-26), so relative times ("10h ago") drift.
