---
name: design-handoff
description: Use when building or changing Skyline UI (apps/syn-ui, packages/syn-ui/*) from a design - "build this screen from the board", "implement the design", "match the canvas", "new board landed", "build the Eval trend panel", "port this screen to Skyline", "does this match the design", "update the Shipped table", "snapshot the boards". Covers reading a `*.dc.html` board and the Skyline spec, building from them, comparing 1440px and 390px screenshots against the board, and recording the shipped screen. Do NOT use for small tweaks to a screen that has already shipped (change the code directly, no board needed), for the frozen React app apps/syn-dashboard-ui (never edit it), or for refreshing the CI screenshot baselines alone (see design/README.md).
---

# Design handoff: board to Skyline code

## Overview

Designs are made on the Claude Design canvas and snapshotted into `design/canvas/`.
A board is an interactive spec, not code: it only runs inside the canvas. Once a
screen ships, the code is the source of truth and its board is frozen history.
The process lives in [design/README.md](../../../design/README.md); this skill is
the agent's checklist for it.

## Rules

- Boards are a spec, not code. Never copy board markup or its JS class into the app.
- Build only from boards for screens NOT in the Shipped table of `design/README.md`.
  A shipped screen changes in code; a redesign starts from a screenshot of the live app.
- Never sync a screen back from code to the canvas.
- No Storybook. Component states are shown in `/dev/components` and `/dev/patterns`.
- Never edit `apps/syn-dashboard-ui` (frozen React reference: read it for behaviour only).
- Skyline conventions: Svelte 5 runes, plain CSS with `--sky-*` tokens, no colour
  literals, no chart libraries, first-load JS under 100 KB gzipped, strict TS, no `any`.

## Steps

### 1. Read the board and the spec

1. Read `design/README.md`, then `packages/syn-ui/CONVENTIONS.md`.
2. Find the boards: `design/canvas/<Screen>.dc.html` and `design/canvas/Phone<Screen>.dc.html`.
   `design/canvas/canvas.json` maps each file to its title and page.
3. Read each board as text. What to take from it:
   - layout and copy: the HTML and CSS;
   - repeats and conditions: `<sc-for>` and `<sc-if>`;
   - shared pieces: `<dc-import>` (TopNav, PhoneDock, PhaseKit ...), already components;
   - sample data and behaviour: the JS class at the bottom, `renderVals()` and `setState()`.
4. Read the matching sections of `design/skyline-spec.md` (tokens, components, patterns,
   responsive rules, screen map).
5. To see a board rendered, open the live canvas (link in `design/README.md`).

### 2. Build

- Maths, formatting, geometry and state logic go in `packages/syn-ui/skyline-core`
  with Vitest unit tests; components only render them.
- Reusable components go in `packages/syn-ui/skyline-svelte-v5` and get an example
  on `/dev/components` or `/dev/patterns`, with their example states in a data file
  next to the component.
- Screens go in `apps/syn-ui/src/routes`. Data comes from `packages/syn-ui/data`;
  where the API lacks a field, add a fixture matching the board's sample data and
  flag the backend gap in the PR.
- Check: `cd apps/syn-ui && pnpm exec svelte-check --threshold error`, plus the
  package tests and `pnpm --filter syn-ui run build` (size budget).

### 3. Compare screenshots with the board

Run the app in fixtures mode and capture the screen at both widths:

```bash
cd apps/syn-ui
VITE_SYN_FIXTURES=1 pnpm exec vite --port 5174 --strictPort --host 127.0.0.1 &
pw=node_modules/@playwright/test/cli.js
node "$pw" screenshot --full-page --viewport-size=1440,900 http://127.0.0.1:5174/<route> /tmp/<screen>-1440.png
node "$pw" screenshot --full-page --viewport-size=390,844  http://127.0.0.1:5174/<route> /tmp/<screen>-390.png
```

Look at both images next to the board (desktop board at 1440, `Phone*` board at 390).
Check layout, copy, hierarchy, spacing and states (empty, loading, error) one by one.
Fix what differs, or write down why it differs in the PR. No horizontal scroll at 390.

Run the suite before the PR: `just skyline-e2e`. If you changed a component on the
dev pages, the CI `screenshots` job will fail on purpose: refresh the baselines as
`design/README.md` describes. Never commit baselines made on macOS.

### 4. Update the Shipped table

When the screen ships, add a row to the Shipped table in `design/README.md`:
screen, board files, route, PR number, date. From then on the board is frozen.

In the PR, post the 1440px and 390px screenshots next to the board name.

## Anti-patterns

- Editing an old board to start a redesign. Screenshot the live app instead.
- Redrawing a small code change on the canvas.
- Pasting board CSS with colour literals instead of mapping to `--sky-*` tokens.
- Claiming "matches the design" without screenshots at both widths.
