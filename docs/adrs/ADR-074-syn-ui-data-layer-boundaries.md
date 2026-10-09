# ADR-074: syn-ui data-layer boundaries

Status: Accepted (2026-10-08)

## Context

syn-ui (ADR-073) is built from a published component standard: `@syntropic137/design-contracts` and `@syntropic137/design-tokens`, pinned exactly, so a contract mismatch is a compile error. The owner wants the same discipline on the data side (carried from #624): data access separated from presentation, queries reusable across UI stacks, testable in isolation, with boundaries a tool can check.

Measured on feat/skyline-svelte at 47198ec01: 24 route files import from the data package, zero raw `fetch` calls exist outside it, and one Svelte binding (`resource()` in `apps/syn-ui/src/lib/load.svelte.ts`) is the only place Svelte reactivity meets the data layer. The structure is already right; this ADR names it so it stays right.

## Decision

Four layers, each importing only downward:

| Layer | Where | May depend on | Framework |
|---|---|---|---|
| Data | `packages/syn-ui/data` | generated OpenAPI types, nothing else | none (plain TypeScript, zero runtime deps) |
| View models | `packages/syn-ui/skyline-core/src/screens/<area>` | data types, skyline-core | none |
| Binding | `apps/syn-ui/src/lib/{load,live,page}.svelte.ts` | data, view models | Svelte 5 runes |
| Routes | `apps/syn-ui/src/routes/<area>` | binding, view models, Skyline components | Svelte 5 |

Rules:

1. Routes and components never call `fetch`, never build URLs, never parse responses. They call a named resource in `packages/syn-ui/data/src/resources` through the binding.
2. Every resource has a fixture under `packages/syn-ui/data/src/fixtures`, so every screen runs offline (`VITE_SYN_FIXTURES=1`) and every e2e test runs without an API.
3. Types come from `packages/syn-ui/data/src/generated/api-types.ts`, regenerated from the API's OpenAPI spec by `just codegen`. A hand-written type in `data` is allowed only while the endpoint it describes is unmerged, and carries a `TODO(#issue)`.
4. The data package stays framework-agnostic so another UI stack (a React page, a CLI, a Tauri sidecar) can reuse the same resources and fixtures unchanged.
5. Backend formats, client renders: `*_display` strings and lower-bound flags are consumed, never recomputed.

Query cache: a small in-package cache in `packages/syn-ui/data/src/client` (keys derived from resource name plus parameters, staleness per resource, invalidation driven by the live SSE stream) rather than TanStack Query. Reasons: zero runtime dependencies in `data`, access patterns are list and detail with event-driven refresh, and the 100 KB first-load budget. TanStack Query core is the fallback if the cache outgrows roughly 200 lines or needs features such as optimistic mutation.

Enforcement, as fitness functions in `ci/fitness/` (not lint):

- `apps/syn-ui/src/routes/**` and `packages/syn-ui/skyline-svelte-v5/**` contain no `fetch(`, no `/api/v1` string, and import `@syn137/syn-ui-data` only from routes or the binding.
- `packages/syn-ui/data` has zero runtime dependencies and imports nothing from Svelte.
- Every exported resource has a fixture route registered.
- Contract tests: each resource's response type is checked against the OpenAPI spec the API serves (`check:api-drift` already does this for the CLI; the data package joins it).

## Consequences

- A new screen is three files in three layers: a resource (or reuse), a view model with unit tests, a route that composes. No screen-specific fetching.
- Swapping fixtures for the live API is one `configureClient({ fixtures })` call in `main.ts`; nothing in routes changes.
- The cache is ours to maintain. Kept deliberately small; the fallback is named.
- The fitness checks are the guard. Breaking the layering fails preflight, not review.

## Rejected

- TanStack Query as the data layer (#624): adds a runtime dependency to a package that must stay stack-neutral; the Svelte binding would then own caching semantics the data package cannot test.
- Fetching inside components: convenient, untestable without a browser, and the first thing that made the React app hard to change.
