# ADR-073: Svelte 5 for the syn-ui dashboard

Status: Accepted (2026-10-08)

## Context

Issue #624 planned a redesign of the React dashboard as a refactor in place: React DOM, Tailwind, TanStack Query, with a second component set for native targets. The dashboard must also ship as a desktop app and later on mobile, and the north star is a UI that stays fast while the platform runs 1,000 concurrent executions.

## Decision

The new dashboard is a parallel app, `apps/syn-ui`, written in Svelte 5 with plain CSS. It is built on the Skyline component library under `packages/syn-ui/`: `skyline-core` (TypeScript, no DOM: geometry, formatters, state machines), `skyline-svelte-v5` (components and patterns, plus a custom-element build), `themes` (the only place colour literals live) and `data` (typed API client, live stream, fixtures).

Skyline names the design style and the component library. The app is syn-ui. `apps/syn-dashboard-ui` is frozen as the parity reference and is deleted after cutover.

One component library serves every shell: the web app, the Tauri desktop shell in `apps/syn-desktop`, and later Tauri mobile. There are no native component sets.

Constraints the build enforces: first-load JS under 100 KB gzipped (CI check), no Tailwind, no chart libraries (Skyline draws its own geometry), dark only for now, Lucide icons.

## Consequences

- Two UIs run in parallel during the transition. The gateway serves syn-ui at `/next` and React at `/`, then flips.
- Cost is one more framework in the repo until React is deleted. The React app receives no new features.
- The custom-element build lets Skyline components embed in pages outside the app.
- Measured at milestone 1: 29.4 KB gzipped first load, against a React bundle several times that size.

## Rejected

- Refactoring the React app in place (#624): keeps Tailwind and a charting dependency, and gives no path to a sub-100 KB first load.
- React Native Web for mobile: 40 to 60 KB of runtime for a web-first product. Tauri mobile reuses the web build instead.
