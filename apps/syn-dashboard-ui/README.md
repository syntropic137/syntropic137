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
node scripts/screenshot.mjs http://localhost:4173/ /workspace/artifacts/output/landing.png
node scripts/screenshot.mjs http://localhost:4173/executions out.png --viewport 390x844
```

It prints the PNG's real dimensions and byte size, the HTTP status and the page
title, and exits non-zero on bad arguments or a failed navigation.

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
  states. That still proves layout and routing, not data.
