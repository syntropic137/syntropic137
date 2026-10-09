# Skyline conventions

Skyline is the Svelte 5 UI for Syntropic137: four packages under `packages/syn-ui/` and the app in `apps/syn-ui/`. This file says where code goes, how to write it, who owns which files, and how to check it. Read it before you write code here.

The design source is the canvas (`*.dc.html` boards) and the Skyline spec. The React app `apps/syn-dashboard-ui` is the behavioural reference. It is frozen: read it, never edit it.

## Commands

Run from the repo root.

| What | Command |
|---|---|
| Install | `pnpm install` |
| Type-check everything (tsc, svelte-check, CSS token gate, theme parity, token usage, the published contracts gate) | `just skyline-check` |
| Plain type check (what `build` runs first) | `pnpm --filter syn-ui --filter './packages/syn-ui/*' run typecheck` |
| Published `@syntropic137/design-contracts` gate | `just skyline-verify-contracts` |
| Prove the gates catch drift (applies each mutation, expects failure, restores) | `just skyline-mutations` |
| Unit tests | `just skyline-test`, or `pnpm --filter syn-ui --filter './packages/syn-ui/*' run test` |
| Production build with the size budget | `just skyline-build`, or `pnpm --filter syn-ui run build` |
| All of the above | `just skyline-qa` |
| Dev server on the real API (proxied to `http://127.0.0.1:9137`) | `just skyline-dev` |
| Dev server with no backend (fixtures) | `just skyline-dev-fixtures`, or `pnpm --filter syn-ui run dev:fixtures` |
| One package | `pnpm --filter @syn137/skyline-core test`, `pnpm --filter syn-ui check`, and so on |

The dev server runs on port 5174, so it can run next to the React dashboard on 5173. `VITE_API_PROXY_TARGET` overrides the API address. `SYN_UI_PROXY_AUTH=user:password` (not `VITE_`-prefixed on purpose: Vite exposes `VITE_*` to the browser) adds Basic Auth to proxied requests only (for a remote gateway such as the VPS over Tailscale: target `http://100.114.86.77:8137/api/v1`, user `admin`, password from the login Keychain item `syn137-api-password-vps`); it never reaches the browser bundle. `SYN_UI_BASE=/next/` builds the app for `/next` (see Routing).

Before you hand work back, check, test and build must all pass with zero warnings. `svelte-check` runs with `--fail-on-warnings`, so accessibility warnings count as failures.

## Packages

| Package | Path | Holds | Depends on |
|---|---|---|---|
| `@syn137/skyline-themes` | `packages/syn-ui/themes` | CSS only: `tokens.css` (structure), `skyline.css` and `syn137.css` (colour), `all.css` (upstream `@syntropic137/design-tokens` CSS, then all three) | `@syntropic137/design-tokens` (pinned) |
| `@syn137/skyline-core` | `packages/syn-ui/skyline-core` | Plain TypeScript with no DOM and no Svelte. Holds the contract re-exports, formatters, chart geometry, state reducers and pattern prop types | `@syntropic137/design-contracts` (pinned, types only) |
| `@syn137/skyline-svelte-v5` | `packages/syn-ui/skyline-svelte-v5` | Svelte 5 components (`.`), patterns (`./patterns`) and `styles.css` | core, themes |
| `@syn137/syn-ui-data` | `packages/syn-ui/data` | Plain TypeScript: the typed API client, fixtures, live SSE stream, request coalescing and the query cache | nothing |
| `syn-ui` | `apps/syn-ui` | The Vite app: shell, router, route pages, data loading | all four |

All workspace packages export TypeScript and Svelte source directly, so they have no build step. Vite compiles them inside the app, and `check` is their build. Arrows only point down the table: core and data never import Svelte, and the component library never imports data.

### Which package does this code belong in?

1. It would read the same in React, Svelte or a CLI (maths, formatting, a state transition, a type): **skyline-core**. Write a Vitest test with it.
2. It talks to the API or the event stream: **syn-ui-data**.
3. It renders reusable UI with no knowledge of a route or of fetching: **skyline-svelte-v5**. Domain compositions such as Run Row or Skyline go under `patterns/`, and generic controls go under `components/`.
4. It knows about a route, fetches data or composes a screen: **apps/syn-ui**.

A component never fetches data. A pattern takes plain props, typed in `skyline-core/src/patterns/`. A page fetches, then passes plain data down.

## Naming

- Files: Svelte components use `PascalCase.svelte`. TypeScript files use `camelCase.ts`. Runes modules end in `.svelte.ts`.
- Components: one folder per component, `components/Button/Button.svelte`, with a `types.ts` that holds `ButtonProps`. Patterns follow the same layout under `patterns/RunRow/`.
- CSS classes always carry the `sky-` prefix: `sky-button`, `sky-button__icon`. Variants and state are data attributes, not classes: `data-variant`, `data-size`, `data-tone`, `data-state`, plus `aria-*` where ARIA has the concept, such as `aria-pressed` and `aria-current`.
- Exports are named and come from the package index. Deep imports into another package's `src/` are not allowed. Subpath entries are the exception: `@syn137/skyline-core/format`, `/geometry`, `/state`, `/patterns`, `/contracts`, and `@syn137/syn-ui-data/types`, `/live`, `/invalidate`, `/fixtures`.
- A `TODO` or `FIXME` must reference an issue, for example `TODO(#624): ...`. Issue #624 is the Skyline epic.

## CSS rules

These rules are enforced by `packages/syn-ui/scripts/check-css.mjs`, which runs inside `check` for skyline-svelte-v5 and the app.

- **No colour literals** outside `packages/syn-ui/themes/src/{skyline,syn137}.css`. That covers hex values, `rgb()`/`hsl()`/`oklch()`, and named colours such as `white`. Use `var(--ds-*)` and `var(--sky-*)`. `transparent`, `currentColor` and `color-mix()` over tokens are fine.
- **No `var()` fallbacks.** Write `var(--ds-color-fg)`, never `var(--ds-color-fg, #fff)`. Every token is defined by the theme.
- Plain CSS in the component's `<style>` block. No Tailwind and no CSS-in-JS. Global rules live in `skyline-svelte-v5/src/styles.css` (shared helpers) or `apps/syn-ui/src/app.css` (page base).
- **Mobile first.** Base styles are the phone layout. Media queries use `min-width` only and are written in rem: `48rem` (capsule nav, list columns) and `64rem` (detail side column). Components prefer container queries. Page structure uses viewport queries.
- **Touch:** interactive targets reach `var(--sky-size-touch)` (44px) under `@media (pointer: coarse)`. Nothing is reachable by hover alone.
- **Focus:** every interactive element has its own `:focus-visible` rule: `outline: var(--sky-focus-ring-width) solid var(--sky-color-focus); outline-offset: var(--sky-focus-ring-offset);`.
- **Motion** goes inside `@media (prefers-reduced-motion: no-preference)`, or uses the `--sky-duration-*` tokens, which drop to 0 under reduced motion.
- Titles and figures size with the fluid tokens `--sky-text-page`, `--sky-text-hero` and `--sky-text-figure` (`clamp()`).
- No horizontal page scroll at 320px. Wide content scrolls inside its own box.
- 3D faces: use `extrudeColors(base)` from `@syn137/skyline-core/geometry`, or the `--sky-face-top`, `--sky-face-front` and `--sky-face-side` tokens for the accent. Never hand-mix toward white or black.

### Tokens

`--ds-*` names mirror the upstream `@syntropic137/design-tokens` roles: `--ds-color-bg`, `surface`, `surface-raised`, `overlay`, `border`, `fg`, `text-muted`, `text-subtle`, `accent`, `accent-hover`, `accent-contrast`, `danger`, `warning`, `success`, plus fonts, space, radius and type. `--sky-*` names belong to Skyline. Read `themes/src/tokens.css` and `themes/src/syn137.css` for the full list. Each value has a comment naming its canvas use. The ones you will reach for most:

| Need | Token |
|---|---|
| Page, card, raised, selected | `--ds-color-bg`, `--ds-color-surface`, `--ds-color-surface-raised`, `--ds-color-overlay` |
| Hairline, control border, hover border, row divider | `--ds-color-border`, `--sky-color-border-strong`, `--sky-color-border-hover`, `--sky-color-divider` |
| Text | `--ds-color-fg`, `--ds-color-text-muted`, `--ds-color-text-subtle` |
| Primary button | `--sky-color-accent-solid`, `--sky-color-accent-solid-contrast`, `--sky-shadow-glow` |
| Soft accent (Completed badge, halos) | `--sky-color-accent-soft`, `--sky-color-accent-soft-fg`, `--sky-color-accent-ring` |
| Failed, warning, neutral pills | `--sky-color-danger-soft` with `--sky-color-danger-soft-fg`, `--sky-color-warning-soft` with `--sky-color-warning-soft-fg`, `--sky-color-neutral-soft` |
| Token series (cache read, cache write, output, input) | `--sky-color-data-1` to `--sky-color-data-4` (skyline-core `TOKEN_SERIES` maps them) |
| Agents | `--sky-color-agent-claude`, `--sky-color-agent-codex` |
| Bars and empty blocks | `--sky-color-track`, `--sky-color-empty`, `--sky-color-running-block`, `--sky-color-unscored` |
| Raised surface highlight, overlays | `--sky-shadow-raised`, `--sky-shadow-overlay`, `--sky-color-scrim` |
| Radii | `--ds-radius-md` (10, nav items), `--ds-radius-lg` (11, buttons), `--sky-radius-control` (12), `--sky-radius-row` (14), `--sky-radius-xl` (18, cards), `--sky-radius-card-lg` (20), `--sky-radius-2xl` (24, header panels), `--ds-radius-full` |
| Control heights | `--sky-size-control-sm`, `-md`, `-lg` (32, 36, 44px) |
| Layout | `--sky-page-max` (1400px), `--sky-gutter` (16px phone, 40px from 48rem), `--sky-side-column` (340px) |

If you need a colour that has no token yet, add it to **both** theme files, since `check-themes.mjs` fails when they differ, and `check-token-usage.mjs` fails (with file:line) on any `var(--sky-*)` or `var(--ds-*)` that a theme, `tokens.css` or upstream design-tokens does not define. Say so in your result, because the themes are owned by the foundation.

## skyline-core

- `src/contracts/`: type-only re-exports of `@syntropic137/design-contracts` (pinned exactly), plus aliases for the older Skyline names. A component's props extend the contract, for example `interface ButtonProps extends Omit<ButtonContract, 'variant'>, ...`, and declare Skyline-only props themselves with a `Skyline:` doc comment. Never add Skyline-only props to `src/contracts/`.
- `src/format/`: `formatCost`, `formatCostPrecise`, `formatCostWithCoverage`, `formatTokens` (`261.7k`, `2.79M`), `formatTokenBreakdown`, `formatDuration` (`3m 47s`), `formatDurationPrecise` (`24.3s`), `formatRelativeTime` (`5d ago`), `formatDate`, `formatDateTime`, `formatClock`, `dayKey`, `formatBytes` (`19.8 KB`), `formatInteger`, `formatPercent` and `shortId`. Unknown values render as `UNKNOWN` (an em dash), never `NaN` or `0`. The API also sends `*_display` strings: render those verbatim where they exist, and format raw numbers only when you have to.
- `src/geometry/`: `obliqueBox` (Skyline bars, the usage band), `isoBox` (object icons, verdict blocks), `extrudeColors`, `polygonPath`, `scaleLinear` and `sqrtHeight`. Add each chart's layout here as a pure function, for example `skyline.ts` or `phaseBlocks.ts`, and test it in a matching `*.test.ts`.
- `src/state/`: reducers `(state, event) => state` with no timers. The component owns side effects. `copyFeedback` is the worked example.
- `src/patterns/`: prop types for the 22 patterns, plus `statusSemantics(status)`, which maps an API status to a badge variant, tone, glyph and label in one place. Screens never pick status colours.

Every new function gets a Vitest test in Node (`src/**/*.test.ts`).

## Adding a component (skyline-svelte-v5)

1. Create `src/components/Name/Name.svelte` and `src/components/Name/types.ts`. Props extend the contract from `@syn137/skyline-core/contracts` when one exists, plus the host element's native attributes, for example `HTMLButtonAttributes` from `svelte/elements`. Spread `...rest` **before** component-owned attributes, so callers cannot override `class`, `data-variant` or `role`.
2. Use runes (`$props`, `$state`, `$derived`). Content comes in as `Snippet` props (`children`, `icon`). Do not use slots or `createEventDispatcher`. Callbacks are props, for example `onPressedChange`.
3. Expose variants as `data-*` attributes on the host element with `sky-` classes, and give the component its own `:focus-visible` and coarse-pointer rules.
4. Export it: add one line to `src/index.ts`, alphabetical within its group:
   `export { default as Button } from './components/Button/Button.svelte'` and `export type { ButtonProps } from './components/Button/types'`.
   Patterns go in `src/patterns/index.ts` the same way.
5. Logic such as geometry, formatting or state goes in skyline-core with tests. The component only renders.
6. Component tests are welcome. They need `jsdom` and `@testing-library/svelte`, which are not installed yet, so whoever adds the first component test adds them as devDependencies of skyline-svelte-v5 and lists them in their result.

7. Every contract union the component renders (size, variant, tone, orientation) goes through an exhaustive lookup in `Name/variants.ts`, keyed by the Props type: `export const NAME_SIZE = { sm: 'sm', md: 'md', lg: 'lg' } as const satisfies Record<NonNullable<NameProps['size']>, string>`, used as `data-size={NAME_SIZE[size]}`. A member added upstream is then a missing-key compile error, not an unstyled value. Add an `Expect<Equal<...>>` line for each such prop to `src/contract-unions.ts`.

Required-contract conformance lives in `src/contract-adapter.ts` (the file name the published gate looks for), re-exported from `src/index.ts`.

Contract-only callers: Svelte's HTML attribute types carry a symbol index signature (attachments), so a plain `ButtonContract` value is not assignable to `ButtonProps`.
Spread it, `<Button {...props} />` or `consume({ ...props })`; that is expected, not a contract break.

## The data client (syn-ui-data)

```ts
import { configureClient, listExecutions, getExecution, ApiError, isAbortError } from '@syn137/syn-ui-data'
import type { ExecutionDetailResponse } from '@syn137/syn-ui-data/types'
import { subscribeActivity, subscribeExecution } from '@syn137/syn-ui-data/live'
```

- Every resource function takes an optional `AbortSignal` as its last argument and calls `request(path, { query, body, method, signal })`. Paths are relative to the base (`/api/v1`).
- Types: generated OpenAPI types live in `src/generated/api-types.ts` (regenerate with `pnpm --filter @syn137/syn-ui-data generate:types`). Hand-written types are ported in `src/types.ts`. Prefer aliasing the generated schema, `components['schemas']['X']`, to restating it.
- Concurrent identical GETs are coalesced into one request. Each caller's abort only cancels that caller.
- Every read goes through the query cache (`src/client/queryCache.ts`, ADR-074). Wrap a new read in `cached(name, params, (s) => request(path, { signal: s }), { signal, staleAfter })` from `src/keys.ts`, where `name` is the function's own name (add it to the `ResourceName` union) and `params` are its arguments minus the signal. `staleAfter` is `'list'` (15 s), `'detail'` (60 s, the default), `'metrics'` (5 s) or ms. Fresh data is served without a request, stale data is served and refreshed in the background, and fixtures mode never goes stale on its own.
- A mutation wraps its request in `thenInvalidate(request(...), [{ name: 'getX', id }, { name: 'listX' }])`. Live events invalidate through the pure map in `src/live/invalidate.ts` (`invalidationsFor`, subpath `/invalidate`, which the app loads lazily to keep it out of the first load); add a case there, with a test, when a new event should refresh a resource.
- Callers get a copy of cached data, so editing a response never edits the cache.
- Avoid N+1 fan-out. If you must fan out, use `mapLimit(items, 4, fn)` and record the API gap in your result.
- Errors are `ApiError` with `status`, `code` and `detail`. Ignore `isAbortError(e)`.
- Live: `subscribeActivity({ filter, onFrames, onState })` shares one EventSource per URL per tab and delivers frames batched per animation frame. Fixtures mode never connects and reports `'fixtures'`.

### Resources

`workflows`, `executions`, `sessions`, `sessionInventory`, `evals`, `artifacts`, `triggers`, `repos`, `costs`, `feedback` (`createFeedback` only), `observability` (metrics, tool timeline, tokens, conversation log, SSE URLs, features, version) and `insights` (`getContributionHeatmap` for the Overview Skyline). Each one ports `apps/syn-dashboard-ui/src/api/<name>.ts`. Function names match the React app except for the ones below, renamed for clarity:

| React | syn-ui-data |
|---|---|
| `listExecutions(workflowId)` | `listWorkflowRuns(workflowId)` |
| `listAllExecutions(query)` | `listExecutions(query)` |
| `listArtifactPage(query, scope)` | `listArtifacts(query, scope)` |
| `getExecutionSSEUrl(id)` | `executionStreamUrl(id)` |

### Fixtures: how to add one

Fixtures mode (`VITE_SYN_FIXTURES=1`, or `configureClient({ fixtures: true })`) answers every request from `src/fixtures/` with simulated latency. The router loads lazily, so it never ships in a production first load.

- `fixtures/catalog.ts`: the shared world, made of workflows and runs transcribed from the canvas boards. Sessions, artifacts and costs are derived from runs, so IDs agree across screens. Add rows here first.
- `fixtures/<resource>.ts`: builds the API shapes and declares the routes with `route('GET', '/executions/:executionId', ({ params, query, body }) => ...)` from `./define`. Throw `notFound('Execution')` for a 404. Responses are type-checked against the client types, so annotate the handler return type, for example `(): ExecutionListResponse =>`.
- `fixtures/routes.ts`: the single route table. Add new route arrays here.
- Use `ago(ms)` and `FIXTURE_NOW` for timestamps, `paginate`, `filterList` and `countBy` for list endpoints, and `fakeId(seed)` for stable IDs.
- Sample values come from the canvas board's `renderVals()` data: names, durations, tokens, costs. Keep them recognisable.
- Add a case to `fixtures/fixtures.test.ts` when you add an endpoint.

**The rule the fitness check enforces** (`ci/fitness/code_quality/test_syn_ui_every_resource_has_a_fixture.py`, ADR-074 rule 2): a resource is an exported function in `src/resources/*.ts` that sends a request. It calls `request(path, ...)` with the path written as a string or template literal, directly or through a non-exported helper in the same file. Every request it sends needs a `route(method, path, ...)` with the same method and path shape in a `fixtures/*.ts` file imported by `fixtures/routes.ts`: a template substitution such as `${seg(id)}` and a `:param` are the same segment, and the query string is ignored. Exported functions that send nothing (URL builders such as `executionStreamUrl`) are not resources. Resources never call `fetch` or `fetchJSON` themselves. An endpoint the fixtures world has no data for still gets a route: throw `notFound(...)`, as the session-inventory pages do.

## The app (apps/syn-ui)

### Routing

`src/lib/routes.ts` is the route table. Paths are identical to the React app. `/insights` and anything under it redirect to Overview. Each page is a lazily loaded chunk under `src/routes/<area>/`. `src/lib/router/` is a small history router written for this app:

- Use plain `<a href={href('/executions/' + id)}>` links. `href()` adds the deploy base. Clicks are intercepted, and hover or focus preloads the target route's chunk. To force a full reload, add `data-sky-reload`.
- `router.navigate(path)`, `router.path`, `router.query` (URLSearchParams) and `router.setQuery({ status: 'failed' })`. Filters live in the query string and replace history rather than push to it.
- A page component receives `{ params }: PageProps`, typed as `Record<string, string>`. A page is remounted when its params change.

### Layer checks (ADR-074)

Fitness functions in `ci/fitness/code_quality/` keep the layers apart, with no exceptions:

| Check | Rule |
|---|---|
| `test_syn_ui_no_fetch_outside_data.py` | No `fetch(` call and no `/api/v1` string in `apps/syn-ui/src`, `skyline-svelte-v5/src` or `skyline-core/src`. |
| `test_syn_ui_data_imports.py` | `@syn137/syn-ui-data` is imported only from `apps/syn-ui/src/{routes,lib,shell}` and tests. `main.ts` calls `startClient()` from `lib/client.ts`. |
| `test_syn_ui_data_is_framework_agnostic.py` | `packages/syn-ui/data` has no runtime dependencies and imports nothing from Svelte. |
| `test_syn_ui_every_resource_has_a_fixture.py` | Every resource request has a fixture route (see Fixtures above). |

Run them with `uv run pytest ci/fitness/code_quality/test_syn_ui_*.py -q`.

### How pages fetch data

Use `resource()` from `src/lib/load.svelte.ts`. Do not fetch in `onMount` and do not write your own effects.

```svelte
<script lang="ts">
  import { getExecution } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'

  let { params }: PageProps = $props()
  const exec = resource((signal) => getExecution(params.executionId ?? '', signal), {
    live: (type) => type.startsWith('phase_') || type.startsWith('workflow_'),
  })

  $effect(() => {
    if (exec.data) setPage({ title: exec.data.workflow_name, crumbs: [
      { label: 'Workflows', href: '/workflows' },
      { label: exec.data.workflow_name, href: `/workflows/${exec.data.workflow_id}` },
      { label: 'Execution', id: shortId(exec.data.workflow_execution_id) },
    ] })
  })
</script>

{#if exec.error}…{:else if exec.data}…{:else}…{/if}
```

- Reactive values that the fetcher reads **before its first `await`**, such as params, `router.query` or a `$state` filter, are tracked. Changing one aborts the old request and refetches.
- `data` keeps its previous value while a refetch runs. `loading` and `error` describe the latest request.
- `live` refetches, throttled to once every 2 seconds, on matching activity events.
- Reads go through the query cache. A fetcher that returns a resource call directly, `(signal) => getX(id, signal)`, renders cached data on the first frame, so coming back to a page shows no skeleton. A fetcher that awaits or combines several calls still uses the cache but resolves a microtask later. Any invalidation of a key the fetcher read (live event, mutation, `refresh()`) re-runs it.
- Breadcrumbs and the document title: the route table supplies defaults, and the page refines them with `setPage()`. Overview has no breadcrumbs. Crumb hrefs are app paths, and the trail adds the base itself.
- Loading, empty and error states are part of every screen. For now, use the `Skeleton`, `EmptyState` and `Callout` components once they exist.

### Shell

`src/shell/` holds the App Shell from the TopNav, PhoneTop and PhoneDock boards. That means the capsule nav from 48rem up, and the top bar plus floating dock below it. The dock holds Overview, Executions, Evals, Workflows (the fourth slot, provisional) and More, which opens a sheet with Sessions, Artifacts, Triggers and Repos. The shell also holds the Breadcrumb Trail, which collapses to Home, the ellipsis button, the parent and the current page on phones. `StubPage.svelte` is the placeholder that the route stubs use. Delete its import when you build your screen.

The search buttons, the More sheet's Search entry, ⌘K and the desktop shortcut all dispatch one `sky:command` window event (`requestPalette()` in `shell/overlays.svelte.ts`); AppShell lazily mounts `CommandPalette.svelte` on it.

Every keyboard shortcut lives in skyline-core's `KEYMAP` (`state/keymap.ts`), and `shell/keyboard.ts` is the only window keydown handler that acts on it; the `?` overlay lists the same table. To add a shortcut, add a binding and an action type there and a handler in `keyboard.ts`; never add another window keydown listener. A list row opts into `j`/`k` and Enter with `data-sky-row` on the element holding its primary link. A component that consumes Escape (a sheet, a menu) calls `preventDefault()` so the keymap does not also go back.

### Feedback bubble

A floating bubble, bottom right (above the dock on phones), is the React widget (`lib/ui-feedback`) ported: `src/shell/FeedbackBubble.svelte`, `FeedbackDialog.svelte` and `src/shell/feedback/`. Its menu has Quick note, Pin to element and Recent feedback (the last 8 from `syn-ui`, with the open count as a badge). A Recent item opens a detail view in the panel (`feedback/FeedbackDetail.svelte`): full comment, type, priority, status with Mark resolved / Reopen (`PATCH /feedback/{id}`), `created_at` as the API sends it (FeedbackItem has no display field), route, URL, pinned element and screenshots (`feedbackMediaSrc()`). Arrows move between items, Enter opens, Esc steps back. Shortcut hints render as separate caps with the `Keycaps` pattern via `shell/keycaps.ts` (`⌃ ⇧ F` on Apple, `Ctrl Shift F` elsewhere; plain Mod chords stay `⌘ K`), and the `?` overlay uses the same. The dialog files one item through `createFeedback()` (`POST /feedback`, #1385), then uploads each screenshot with `uploadFeedbackMedia()` (multipart `POST /feedback/{id}/media` through `requestForm()` in the data client).

What it records: coloured type and priority (`--sky-feedback-type-*`, `--sky-feedback-priority-*` in tokens.css; React defaults bug and low), title plus description (the API has no title field, so the title is the comment's first line), the page (url, route, viewport, user agent, hostname, `app_version` and `git_commit` from `GET /version`, `subject_kind`/`subject_id` on detail routes), an optional pinned element (`css_selector` preferring data-testid, then aria-label, then a short CSS path; `xpath`; click point), and screenshots. Element text, box and theme have no API field and are appended to the comment under `---`.

Screenshots: Take screenshot (visible viewport) and Capture area render the DOM with `html2canvas-pro` (the maintained html2canvas fork: html2canvas 1.4.1 throws on the oklab values our color-mix tokens compute to), imported dynamically from `feedback/capture.ts` only, so no byte of it is in a production build. Upload image, paste and drop take PNG, JPEG or WebP up to 10 MB, resized to fit 1920x1080.

Shortcuts:

| Where | Key | Does |
|---|---|---|
| Page | `F` | Open a quick note |
| Page | `Ctrl+Shift+Q` / `Ctrl+Shift+F` / `Ctrl+Shift+T` | Quick note / pin to element / recent (React widget bindings) |
| Dialog, focus not in a text field | `B F U P Q O` | Type: bug, feature, UI/UX, perf, question, other |
| Dialog, focus not in a text field | `1`-`4` | Priority: low, medium, high, critical |
| Dialog, focus not in a text field | `E` / `S` / `A` / `T` | Pick element / take screenshot / capture area / focus title |
| Dialog | `Shift+Enter` or `Mod+Enter` | Send |
| Picker | Tab, arrows / Enter / Esc | Cycle candidates / pin / cancel |

`F` is handled by the bubble, not KEYMAP: a KEYMAP entry needs a new `KeyAction` and a case in `keyboard.ts`, which the shell owner adds.

The bubble shows only when both hold (`src/shell/feedback.svelte.ts`):

- `GET /features` answers `ui_feedback: true`, which the API does when `SYN_UI_FEEDBACK_ENABLED=true` and it is built with the `feedback` extra. Off by default for open-source installs.
- The app runs on a developer machine: the Vite dev server (`import.meta.env.DEV`) or a fixtures build (`VITE_SYN_FIXTURES=1`). A deployed production build never shows it, whatever the flag says.

To enable locally: `just skyline-dev-fixtures` (the fixture answers `ui_feedback: true` and accepts create, list, stats and media), or `just skyline-dev` against an API started with `SYN_UI_FEEDBACK_ENABLED=true`. AppShell mounts the bubble and the dialog as lazy chunks behind `FEEDBACK_LOCAL_ONLY`, so neither joins the first load.

### Size budget

`pnpm --filter syn-ui run build` runs `scripts/size-budget.mjs`. Gzipped JS on first load (the entry chunk and its static imports) must stay under **100 KB**, and so must the first load plus the largest route chunk. The baseline is about 22 KB first load and about 4 KB per stub route. No chart libraries, no markdown or highlight libraries in the entry chunk, and import lucide icons one at a time (`import Copy from '@lucide/svelte/icons/copy'`).

## File ownership (next phases)

Several agents work in this tree at once. Edit only what your task owns. If you need something from another area, build a local version in your own area and say so in your result. The lead merges between phases.

| Owner | Files |
|---|---|
| **Foundation (lead)** | `packages/syn-ui/themes/**`, `packages/syn-ui/scripts/**`, `packages/syn-ui/tsconfig.base.json`, `skyline-core/src/{contracts,format}/**`, `skyline-core/src/index.ts`, `data/src/client/**`, `data/src/live/**`, `data/src/fixtures/{define,router,routes,seed,catalog}.ts`, `data/src/index.ts`, `apps/syn-ui/{index.html,vite.config.ts,package.json,scripts/**}`, `apps/syn-ui/src/{main.ts,App.svelte,app.css,env.d.ts}`, `apps/syn-ui/src/lib/**`, `apps/syn-ui/src/shell/**`, this file, `just/skyline.just`, `pnpm-workspace.yaml` |
| **Components agent** (waves 1 to 5) | `skyline-svelte-v5/src/components/<Name>/**`, `skyline-svelte-v5/src/styles.css` (append), append-only lines in `skyline-svelte-v5/src/index.ts`, `skyline-core/src/state/<machine>.ts` for component state |
| **Patterns agent** (wave 6) | `skyline-svelte-v5/src/patterns/<Name>/**`, append-only lines in `skyline-svelte-v5/src/patterns/index.ts`, `skyline-core/src/patterns/<pattern>.ts`, `skyline-core/src/geometry/<chart>.ts`, `skyline-core/src/state/<machine>.ts` |
| **Overview screen** | `apps/syn-ui/src/routes/overview/**`, `data/src/fixtures/insights.ts`, `data/src/resources/insights.ts` |
| **Workflows screens** (list, detail, runs) | `apps/syn-ui/src/routes/workflows/**`, `data/src/fixtures/workflows.ts`, `data/src/resources/workflows.ts` |
| **Executions screens** | `apps/syn-ui/src/routes/executions/**`, `data/src/fixtures/executions.ts`, `data/src/resources/executions.ts` |
| **Sessions screens** | `apps/syn-ui/src/routes/sessions/**`, `data/src/fixtures/sessions.ts`, `data/src/fixtures/observability.ts`, `data/src/resources/{sessions,sessionInventory,observability,costs}.ts` |
| **Evals screens** | `apps/syn-ui/src/routes/evals/**`, `data/src/fixtures/evals.ts`, `data/src/resources/evals.ts` |
| **Artifacts screens** | `apps/syn-ui/src/routes/artifacts/**`, `data/src/fixtures/artifacts.ts`, `data/src/resources/artifacts.ts` |
| **Triggers screens** | `apps/syn-ui/src/routes/triggers/**`, `data/src/fixtures/triggers.ts`, `data/src/resources/triggers.ts` |
| **Repos screen** | `apps/syn-ui/src/routes/repos/**`, `data/src/fixtures/repos.ts`, `data/src/resources/repos.ts` |

Rules that come with the table:

- A screen's page-only parts go in `apps/syn-ui/src/routes/<area>/parts/`. If a part turns out to be reusable, propose it as a pattern rather than importing it across areas.
- Shared index files (`skyline-svelte-v5/src/index.ts`, `patterns/index.ts`, `data/src/fixtures/routes.ts`) are append-only: one export per line, and never reorder or reformat other lines.
- Do not add dependencies without listing them in your result. Never edit `apps/syn-dashboard-ui`. Do not commit, because the lead commits between phases.
