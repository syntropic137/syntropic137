# syntropic137.com design system: see Skyline

This page used to hold the landing page's own design system (mood 41A, March
2026). The site now takes its design from Skyline, the design system shared
with the dashboard (`apps/syn-ui`) and the docs:

- **Tokens and themes:** `packages/syn-ui/themes` (`@syn137/skyline-themes`).
  `src/main.tsx` imports `all.css` (the `--ds-*` / `--sky-*` tokens) and
  `motion.css` (the opt-in landing keyframes); `index.html` sets
  `<html data-theme="syn137">`.
- **Shared visuals:** the `<sky-*>` custom elements from
  `@syn137/skyline-svelte-v5` (built into `dist-elements/` by `build` /
  `dev` first). See "Landing elements" in `packages/syn-ui/CONVENTIONS.md`.
  `src/components/SMark.tsx` shows the pattern: the element plus a static
  light-DOM fallback.
- **Type:** Instrument Sans for UI text (`--ds-font-sans`), JetBrains Mono for
  code (`--ds-font-mono`), Orbitron for the wordmark (`--sky-font-wordmark`).
- **Harness colours:** `src/data/harnesses.ts` names each harness's
  `--sky-harness-<id>` token and gradient.
- **Spec:** `design/skyline-spec.md`. **Plan:** `design/landing-plan.md`, with
  the boards in `design/canvas/`.

Rules for `src/`:

- Colours only from `var(--ds-*)` / `var(--sky-*)` (or `color-mix()` over
  them): no hex, `rgb()`, `hsl()` or named colours in CSS or TSX.
  `scripts/check-colours.sh` (`just landing-colour-lint`) enforces it and, with
  `--tokens`, that every token used exists in the themes.
- A colour with no token is added to both Skyline themes, not here.
- `--landing-*` custom properties are this page's own layout sizes only.

The previous document is in git history:
`git log -- apps/syn-landing/docs/syntropic137-design-system.md`.
