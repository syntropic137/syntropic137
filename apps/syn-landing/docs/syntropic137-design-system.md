# syntropic137.com design system: see Skyline

This page used to hold the landing page's own design system (mood 41A, March
2026). The site now takes its design from Skyline, the design system shared
with the dashboard (`apps/syn-ui`) and the docs:

- **Tokens and themes:** `packages/syn-ui/themes` (`@syn137/skyline-themes`:
  `syn137.css`, `motion.css`, the typed token list).
- **Spec:** `design/skyline-spec.md`.
- **Landing rebuild plan:** `design/landing-plan.md` (decisions, page map,
  phases, rules), with the boards in `design/canvas/`.

Until P5 of the plan swaps them, `src/globals.css` still defines the old
`--color-*`, `--glass-*` and `--grid-*` tokens. P5 replaces them with Skyline's
`--ds-*` and `--sky-*` tokens (via a short alias block, then deleted) and moves
UI text to Instrument Sans. Don't add new tokens of the old kind.

The previous document is in git history:
`git log -- apps/syn-landing/docs/syntropic137-design-system.md`.
