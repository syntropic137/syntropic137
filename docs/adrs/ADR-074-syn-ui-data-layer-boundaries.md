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
| View models | `packages/syn-ui/skyline-core/src/screens/<area>` | skyline-core; plain structural types it declares itself (never imports the data package, not even `import type`) | none |
| Binding | `apps/syn-ui/src/lib/{load,live,page}.svelte.ts` | data, view models | Svelte 5 runes |
| Routes | `apps/syn-ui/src/routes/<area>` | binding, view models, Skyline components | Svelte 5 |

Rules:

1. Routes and components never call `fetch`, never build URLs, never parse responses. They call a named resource in `packages/syn-ui/data/src/resources` through the binding.
2. Every resource has a fixture under `packages/syn-ui/data/src/fixtures`, so every screen runs offline (`VITE_SYN_FIXTURES=1`) and every e2e test runs without an API.
3. Types come from `packages/syn-ui/data/src/generated/api-types.ts`, regenerated from the API's OpenAPI spec by `just codegen`. A hand-written type in `data` is allowed only while the endpoint it describes is unmerged, and carries a `TODO(#issue)`.
4. The data package stays framework-agnostic so another UI stack (a React page, a CLI, a Tauri sidecar) can reuse the same resources and fixtures unchanged.
5. Backend formats, client renders: `*_display` strings and lower-bound flags are consumed, never recomputed.

Query cache: a small in-package cache in `packages/syn-ui/data/src/client` (keys derived from resource name plus parameters, staleness per resource, invalidation driven by the live SSE stream) rather than TanStack Query.

Cache semantics (revised after the codex review, 2026-10-08):

- Keys (`client/queryKey.ts`) encode params with type tags and pairs as tuples: `[undefined]` and `[null]`, `'1'` and `1`, URLSearchParams and a string array, `a=b,c` and `a,b=c` are different keys. Object key order and undefined object fields do not matter. Params are snapshotted (frozen copy) and data cloned when stored.
- A generation is part of every load's identity, including the transport's own GET coalescing (the cache stamps `key#generation` on the signal it hands a fetcher). Generations are cache-wide, so `clear()` starts fresh too. A load publishes only if its signal was not aborted, its generation is still current and its entry is still the cached one.
- Time staleness and invalidation are different. Time-stale data is served at once and refreshed in the background; a failed background refresh keeps serving the old value. Invalidated data (live event, mutation, `refresh()`) is not served as the answer: the next read waits for the refresh, so a failure rejects it. `settled()` offers the old value flagged `invalidated: true`, so a remount still paints it on the first frame.
- The binding keeps data and reports the error: after a failed refresh `resource()` has `data` (the last good value) AND `error`; the next success clears `error`. Screens choose how to show both.
- List time windows are bucketed to the minute in the data layer (`bucketTimeWindow`: lower bound down, upper bound up), so a window computed from `Date.now()` is one key within a minute.
- Live invalidation keys on the API's real `event_type` names (PascalCase domain events plus `git_commit`), checked in at `packages/syn-ui/data/src/live/events.ts` with a contract test that reads the Python source and fails on any new name. Teardown flushes invalidations the throttle was holding. Reasons: zero runtime dependencies in `data`, access patterns are list and detail with event-driven refresh, and the 100 KB first-load budget. TanStack Query core is the fallback if the cache outgrows roughly 200 lines or needs features such as optimistic mutation.

Enforcement, as fitness functions in `ci/fitness/` (not lint):

- `apps/syn-ui/src/**`, `packages/syn-ui/skyline-svelte-v5/**` and `skyline-core/**` never reference `fetch` (called, aliased, or as a computed member), never name `/api/` (even split across `+`), and outside the binding never touch the request layer (`request`, `fetchJSON`, URL builders, the cache, a namespace import of the package). `@syn137/syn-ui-data` is imported only from routes, the binding and the shell, counting dynamic `import()` with string or template literals and relative modules that re-export it.
- `packages/syn-ui/data` has zero runtime dependencies and imports nothing from Svelte, the UI packages, or a relative path outside itself.
- Every exported resource (functions, exported arrows, `export { x }` lists) has a fixture route composed into the router's `routes` table; the whole first argument of `request()` is the path.
- Sources are tokenized (strings, templates, comments, regex literals), so neither strings nor comments can hide code from these checks.
- Contract tests: each resource's response type is checked against the OpenAPI spec the API serves (`check:api-drift` already does this for the CLI; the data package joins it).

## Consequences

- A new screen is three files in three layers: a resource (or reuse), a view model with unit tests, a route that composes. No screen-specific fetching.
- Swapping fixtures for the live API is one `configureClient({ fixtures })` call, made by `startClient()` in `apps/syn-ui/src/lib/client.ts`; nothing in routes changes.
- The cache is ours to maintain. Kept deliberately small; the fallback is named.
- The fitness checks are the guard. Breaking the layering fails preflight, not review.

Measured when implemented (2026-10-08, feat/skyline-svelte):

- Cache: `packages/syn-ui/data/src/client/queryCache.ts`, 199 lines at first (under the 200-line TanStack trigger), 1.2 KB gzipped minified on its own. After the codex fixes: 203 lines plus `queryKey.ts` (62 lines, key encoding and param snapshots); the trigger counts the cache proper, so this is at the line, not over it. The live invalidation map (`src/live/invalidate.ts`, 0.9 KB gz) loads as a lazy chunk. Against the build before the cache: first-load JS 28.9 KB to 29.0 KB gzipped (+0.1 KB); first visit to a data route +1.6 KB (cache, `cached()` wrappers and the binding, in the shared route chunk).
- `resource()` reads through the cache. A fetcher that returns a resource call directly renders cached data on the first frame, so list -> detail -> back mounts no skeleton (e2e: `apps/syn-ui/e2e/navigation.spec.ts`, "back to a list renders cached data on the first frame").
- Client setup moved from `main.ts` to `apps/syn-ui/src/lib/client.ts`, so only routes, the binding and the shell import the data package.
- Unit tests: `packages/syn-ui/data/src/client/queryCache.test.ts` (keys, staleness, de-dupe, abort, invalidation, generations over the real transport, publish guards, refresh errors, fixtures mode, copies), `packages/syn-ui/data/src/live/invalidate.test.ts` (event-to-invalidation map, API-source contract, throttling, teardown flush) and `apps/syn-ui/src/lib/load.svelte.test.ts` (a failed refresh keeps data and sets error, under jsdom).
- Fitness functions in `ci/fitness/code_quality/`, zero exceptions: `test_syn_ui_no_fetch_outside_data.py`, `test_syn_ui_data_imports.py`, `test_syn_ui_data_is_framework_agnostic.py`, `test_syn_ui_every_resource_has_a_fixture.py` (shared scanning in `_syn_ui.py`). The fixture check found three resources with no fixture (session-inventory pages, node lookups, archived transcripts); they now 404 as the API does for a run with no snapshot.
- Not yet done: the contract test of each resource's response type against the served OpenAPI spec (`check:api-drift` for the data package).

## Rejected

- TanStack Query as the data layer (#624): adds a runtime dependency to a package that must stay stack-neutral; the Svelte binding would then own caching semantics the data package cannot test.
- Fetching inside components: convenient, untestable without a browser, and the first thing that made the React app hard to change.
