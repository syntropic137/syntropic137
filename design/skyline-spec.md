

# Skyline component library spec
 · 

## Decisions so far
Skyline is a component library built inside the Syntropic137 monorepo against the contracts of the cross-framework design system, with colour kept in themes so the look can change without touching components.

|Topic
 |Settled
 |Still open
 |
|Name
 |Skyline. Packages are `@syn137/skyline-*` under `packages/syn-ui/`
 |None
 |
|Where it lives
 |In the Syntropic137 monorepo, so every deployment gets the same update
 |Whether a neutral copy is mirrored into the design-system repo as a reference design
 |
|What it depends on
 |`@syntropic137/design-contracts` for the component API and `@syntropic137/design-tokens` for the `--ds-*` token layer
 |Published versions, with a git submodule bridging until the first publish
 |
|Components versus theme
 |Components contain no colour values. Skyline ships a neutral theme; Syntropic137 ships its blue theme on top
 |Final neutral palette
 |
|Framework
 |Svelte 5 for the components and the app. Everything that does not touch the DOM is plain TypeScript in `skyline-core` and `syn-ui-data`
 |None. A web-component build is added when a non-Svelte host needs one
 |
|How the app moves
 |A ground-up rebuild in `apps/syn-ui` beside the frozen React dashboard, taking over `/` once every screen has parity
 |None
 |
|Screen sizes
 |Mobile-first, growing up to desktop
 |None
 |
|Targets
 |Web and phone browser now, Tauri 2 desktop app around the same build later
 |Which Tauri app is first
 |
|This round
 |Spec and canvas only. No code yet
 |None
 |

## Architecture
Skyline is four workspace packages under `packages/syn-ui/` plus the new app. One rule decides where code goes: if it would read the same in Svelte, React or a plain script, it is plain TypeScript; if it touches the DOM or Svelte's reactivity, it is Svelte. Arrows point from a package to what it depends on.
Only `skyline-svelte-v5` and the app know Svelte exists. A framework move later rewrites those two and keeps everything beneath them, including every test of the chart maths.

|Package
 |Where
 |Holds
 |May contain colour values
 |
|`@syntropic137/design-contracts`
 |Upstream repo, npm
 |TypeScript types only: the prop contracts for 43 components
 |No
 |
|`@syntropic137/design-tokens`
 |Upstream repo, npm
 |The `--ds-*` roles as CSS custom properties, with default values and a typed name list
 |Defaults only
 |
|`@syn137/skyline-core`
 |`packages/syn-ui/skyline-core`
 |Plain TypeScript, no DOM: prop types for the 22 patterns, chart geometry (Skyline, Phase Blocks, Verdict Board, Usage Meter band, Outcome Ring), formatters (cost, tokens, durations, relative time) and small state machines (day stepper, selection, filters, copy feedback)
 |No
 |
|`@syn137/skyline-themes`
 |`packages/syn-ui/themes`
 |CSS: the `--sky-*` tokens, `skyline.css` and `syn137.css`, each a set of values under a `data-theme` selector
 |Yes, the only place
 |
|`@syn137/skyline-svelte-v5`
 |`packages/syn-ui/skyline-svelte-v5`
 |Svelte 5 components and patterns, `svelteV5ContractAdapter`, `styles.css`, and an optional custom-element build
 |No
 |
|`@syn137/syn-ui-data`
 |`packages/syn-ui/data`
 |Plain TypeScript: the typed API client, the live event stream and request batching
 |No
 |
|`syn-ui`
 |`apps/syn-ui`
 |The Svelte 5 and Vite app: routes, pages, shell and data loading
 |No
 |Four facts shape this layout:

- The upstream packages are not on npm yet. Until the first publish, a git submodule under `lib/` brings them in, like the monorepo's other shared code.

- Contracts are types, so they cost nothing at runtime. `skyline-svelte-v5` imports them with `import type`; the only code that ships is Skyline's own.

- `skyline-core` runs in Node under Vitest with no browser, so chart maths and formatters get fast unit tests and stay usable from a CLI, a Tauri command or a later framework.

- `packages/syn-tokens` is already taken by the Python token-vending package, so UI packages sit under `packages/syn-ui/` and use the `@syn137/` scope that `ui-feedback-react` already uses.
This replaces the package plan in issue #624: `syn-ui-components` becomes `skyline-core` plus `skyline-svelte-v5`, `syn-ui-tokens` becomes the themes package on top of the upstream roles, and `syn-ui-data` becomes the plain-TypeScript API client the new app uses.
Performance budget, checked in CI from phase 0: under 100 KB of compressed JavaScript on first load, one chunk per route, long lists draw only the rows on screen, live updates are batched per animation frame, and there are no chart libraries.

## Tokens and themes
A theme is one CSS file that assigns values to token names under a `data-theme` selector, and switching themes is one attribute change on the root element. Component CSS never contains a colour literal, which is the rule the upstream gate already enforces.
The design's palette fits the existing upstream roles, so both themes are plain overrides:

|Role
 |Token
 |`skyline` (neutral)
 |`syn137` (blue)
 |
|Page
 |`--ds-color-bg`
 |`#0B0B0C`
 |`#0A0C14`
 |
|Card
 |`--ds-color-surface`
 |`#111112`
 |`#0D101A`
 |
|Thing on a card
 |`--ds-color-surface-raised`
 |`#18181A`
 |`#111626`
 |
|Selected
 |`--ds-color-overlay`
 |`#222225`
 |`#1A2134`
 |
|Hairline
 |`--ds-color-border`
 |`#1F1F22`
 |`#1A2032`
 |
|Text
 |`--ds-color-fg`
 |`#EDEDEE`
 |`#E8EEFB`
 |
|Secondary text
 |`--ds-color-text-muted`
 |`#A6A6AB`
 |`#9AA8C7`
 |
|Labels
 |`--ds-color-text-subtle`
 |`#7C7C82`
 |`#6F7FA3`
 |
|Accent
 |`--ds-color-accent`
 |`#EDEDEE`
 |`#4D80FF`
 |
|Accent hover
 |`--ds-color-accent-hover`
 |`#FFFFFF`
 |`#6B95FF`
 |
|Ink on accent
 |`--ds-color-accent-contrast`
 |`#0B0B0C`
 |`#050A18`
 |
|Failure
 |`--ds-color-danger`
 |`#FF6F61`
 |`#FF6F61`
 |
|Warning
 |`--ds-color-warning`
 |`#E5B450`
 |`#E5B450`
 |
|Success
 |`--ds-color-success`
 |`#3FAF82`
 |`#3FAF82`
 |The neutral column is a first proposal; the blue column is what the canvas screens use.
Skyline needs tokens upstream does not have. They take a `--sky-` prefix so ownership is unambiguous: `--ds-*` names belong to the upstream contract, `--sky-*` names belong to Skyline, and a theme sets both.

|Token
 |`syn137` value
 |Used for
 |
|`--sky-color-border-strong`
 |`#283048`
 |Control borders
 |
|`--sky-color-border-hover`
 |`#34406A`
 |Card and control hover
 |
|`--sky-color-accent-solid`
 |`#3D66CC`
 |Primary button fill. White text reaches 5.3:1 here; on `#4D80FF` it is only 3.6:1
 |
|`--sky-color-accent-solid-contrast`
 |`#FFFFFF`
 |Text on the solid fill
 |
|`--sky-color-data-1` to `-4`
 |`#4C8DEA`, `#E0703A`, `#9085E9`, `#C98500`
 |Token series: cache read, cache write, output, input
 |
|`--sky-color-agent-claude`
 |`#D97757`
 |Claude agent marker (Codex uses the accent)
 |
|`--sky-radius-xl`, `--sky-radius-2xl`
 |`1.125rem`, `1.5rem`
 |Cards, header panels
 |
|`--sky-text-3xl`, `-4xl`, `-5xl`
 |`1.875rem`, `2.75rem`, `3.25rem`
 |Figures, page titles, the Overview headline
 |
|`--sky-size-control-sm`, `-md`, `-lg`
 |`2rem`, `2.25rem`, `2.75rem`
 |Control heights; `lg` is the 44px touch size
 |
|`--sky-font-brand`
 |Orbitron
 |Wordmark only
 |
|`--sky-shadow-raised`, `--sky-shadow-glow`
 |1px top highlight; soft accent glow
 |Raised surfaces; primary actions
 |The themes also set `--ds-font-sans` to Instrument Sans and `--ds-font-mono` to JetBrains Mono.
The 3D faces need no tokens of their own. The front face is the accent, the top face is `color-mix(in oklab, var(--ds-color-accent) 58%, var(--ds-color-fg))`, and the side face mixes the accent 50% toward `--ds-color-bg`, so the icons and charts recolour with any theme.

## Component inventory
The eight screens need 31 components: 3 implement contracts that are required upstream today, 20 implement contracts that exist upstream as planned, and 8 have no contract yet.
Components with an upstream contract, in build order:
Every component and pattern below is drawn with its states on the design canvas's System page: Foundations, Components · actions and inputs, Components · display, Components · navigation and overlays, Patterns · domain and data, Phase kit and Usage meter. Build each component from its sheet; the screens show it in context.

|Component
 |Contract
 |Upstream status
 |Where the screens use it
 |Replaces in the dashboard
 |
|Button
 |`ButtonContract`
 |required
 |Run workflow, View transcript, Copy, Pause, Edit, Next
 |Hand-rolled Tailwind buttons
 |
|Badge
 |`BadgeContract`
 |required
 |Completed, Failed and Active pills; type tags; agent chip
 |`StatusBadge`, `AgentBadge`, `PhaseModelBadge`
 |
|Toggle
 |`ToggleContract`
 |required
 |A lone pressed button such as Expand all
 |`FilterChip` used alone
 |
|Toggle Group
 |`ToggleGroupContract`
 |planned
 |Status and type filter chips, time window, year
 |`FilterChip`, `TimeWindowPicker`, `ResourceFilterBar`
 |
|Switch
 |`SwitchRootContract`
 |planned
 |Trigger active or paused
 |Trigger toggle
 |
|Tabs
 |`TabsRootContract`
 |planned
 |Rendered or Raw, Readable or JSON
 |Local buttons
 |
|Meter
 |`MeterContract`
 |planned
 |Most-run workflows, cost by model, usage bars
 |`ModelBreakdown` bars
 |
|Progress
 |`ProgressContract`
 |planned
 |A running execution
 |`Loader`
 |
|Checkbox
 |`CheckboxRootContract`
 |planned
 |Row selection, select all
 |`SelectionCheckbox`
 |
|Select
 |`SelectRootContract`
 |planned
 |Sort, Status, Phase, Attempt
 |Native selects
 |
|Pagination
 |`PaginationContract`
 |planned
 |Every list
 |`ListPagination`
 |
|Separator
 |`SeparatorContract`
 |planned
 |Group rules in lists
 |Borders
 |
|Label
 |`LabelContract`
 |planned
 |Task and Topic fields
 |Plain labels
 |
|Navigation Menu
 |`NavigationMenuRootContract`
 |planned
 |Top capsule on desktop, dock on phone
 |`Layout` sidebar
 |
|Scroll Area
 |`ScrollAreaContract`
 |planned
 |Chip rows that scroll sideways on a phone
 |None
 |
|Tooltip
 |`TooltipRootContract`
 |planned
 |Skyline days, shortened IDs
 |`ChartTooltip`
 |
|Collapsible
 |`CollapsibleRootContract`
 |planned
 |Operation output, phase prompt
 |Local state
 |
|Accordion
 |`AccordionContract`
 |planned
 |Trigger rules that open in place on a phone
 |None
 |
|Dialog
 |`DialogRootContract`
 |planned
 |Transcript viewer
 |None
 |
|Alert Dialog
 |`AlertDialogRootContract`
 |planned
 |Confirm deleting a trigger
 |Browser confirm
 |
|Dropdown Menu
 |`DropdownMenuRootContract`
 |planned
 |More on the phone dock, row actions
 |None
 |
|Popover
 |`PopoverRootContract`
 |planned
 |Filter panels on a phone
 |None
 |
|Command
 |`CommandRootContract`
 |planned
 |Search and jump (⌘K)
 |None
 |Components with no upstream contract. Skyline exports them directly, outside the adapter, the way upstream already treats `Card`:

|Component
 |Where the screens use it
 |Replaces in the dashboard
 |
|Card
 |Every panel; `interactive` for clickable cards
 |`Card`
 |
|Tag
 |Small mono labels for slugs and IDs
 |Inline spans
 |
|Input
 |List search, Task and Topic fields
 |`ListToolbar` search
 |
|Breadcrumbs
 |Detail pages
 |`Breadcrumbs`
 |
|Stat
 |Label and figure pairs in headers
 |`MetricCard`
 |
|Callout
 |Coverage warning, empty-task warning
 |`CliDisclaimerBanner`, `StaleResults`
 |
|Empty State
 |Every list and chart
 |`EmptyState`
 |
|Skeleton
 |Loading placeholders
 |`Loader` text
 |Rules that hold for every component:

- Same public surface. Variants and state are data attributes (`data-variant`, `data-size`, `data-tone`, `data-state`), and classes carry a `sky-` prefix, so the Svelte components, the custom-element build and any later framework render identical markup.

- Contract props come from `@syntropic137/contracts`, never redeclared, and the host element's native attributes pass through.

- Variants map to meaning once. Completed is Badge `soft` + `accent`, Failed is `soft` + `danger`, Cancelled is `outline` + `neutral`. Screens never pick colours.

- Three sizes. `sm`, `md` and `lg` are the control heights above; `lg` becomes the default on touch pointers.

## Patterns outside the contracts
Twenty-two compositions give the screens their character and are specific to Syntropic137's objects, so they are not candidates for upstream contracts. Their prop types and any geometry live in `skyline-core`; the Svelte versions ship from a separate patterns entry point of `skyline-svelte-v5`, take plain props, and do no data fetching, so the web app and a Tauri app render them identically.

|Pattern
 |Built from
 |What it shows
 |On a phone
 |
|App Shell
 |Navigation Menu, Button, Badge
 |Wordmark, live state, search, Run, and the eight sections
 |Top bar plus a floating dock with five destinations
 |
|Breadcrumb Trail
 |Breadcrumbs, Button
 |Home, then each parent, then the current page as a pill
 |Home, an ellipsis button for the hidden middle, the parent and the current page
 |
|Page Header
 |Card, Object Icon, Breadcrumbs, Stat
 |The section's 3D icon, title, one line of context, figures or actions
 |Stacks; figures become a two-column grid
 |
|Object Icon
 |Its own SVG
 |Trigger, workflow, execution, session, artifact and eval as three-face isometric icons
 |Same, at 48px
 |
|Status Badge
 |Badge plus a glyph
 |Completed, failed, cancelled, running, pending
 |Same
 |
|Run Row
 |Status Badge, Meter semantics
 |Name, a bar whose length is duration and whose blocks are phases, tokens, cost, age
 |Bar moves under the name at full width
 |
|Skyline
 |SVG
 |A year of days as extruded bars, taller for more sessions
 |Last 16 weeks, with a toggle for the year
 |
|Day Readout
 |Tooltip semantics, Stat, Usage Meter parts
 |The pointed or stepped day: sessions, executions, commits, tokens by type, spend; a leader line ties it to its bar
 |Sits under the chart with 44px previous and next buttons
 |
|Phase Blocks
 |SVG
 |Phases back to back; length is time, height is tokens
 |Same drawing, phase details listed beneath
 |
|Phase Kit
 |Card, Tag, Skill Ref
 |What a phase gets: model, tools, skills, declared or pinned at start
 |Label and value rows
 |
|Skill Ref
 |Tag, Link
 |A skill's name, source and version, and its content digest once pinned
 |Same
 |
|Run Tiles
 |Link, Object Icon
 |A phase's session (Ran in) and its artifact (Produced), side by side
 |Two stacked 44px tiles
 |
|Provenance Strip
 |Callout, Button
 |Session counts, the coverage warning, revision and replication facts
 |Same, with a full-width button
 |
|Outcome Ring
 |SVG
 |Share completed, failed, cancelled
 |Same
 |
|Usage Meter
 |SVG band, Meter
 |Total cost and tokens, an extruded band of tokens by type, cost by model or by phase
 |Zones stack in one column
 |
|Verdict Block
 |SVG
 |One run's verdict as a block: tall pass, short fail or scorer error, flat unscored
 |Same, 50px
 |
|Verdict Board
 |Verdict Block, Day Readout pattern
 |Cases down the side, verifiers across, bugs caught and average cost per verifier
 |Column heads abbreviate; the readout sits under the board
 |
|Operation Timeline
 |Badge, Collapsible, Callout, Copy Button
 |One row per tool call, start and finish merged, errors in coral
 |Time moves above each row; commands wrap
 |
|Copy Button
 |Button
 |Copies a part (input, output) or the whole list; flips to a check for a moment
 |44px target
 |
|Agent Prompt Button
 |Button
 |Copies a ready prompt that starts a workflow from an agent
 |Full width
 |
|Lineage Trail
 |Tag links
 |Workflow to execution to phase to session
 |Scrolls sideways
 |
|Rule Sentence
 |Tag, Card
 |A trigger as When, If, Then, Cap, Log
 |Opens in place under its rule
 |The charts are hand-drawn SVG driven by arrays, so they need neither `recharts` nor `@nivo/calendar`.

## Responsive rules
Every component and pattern is written for a phone first and gains layout at two widths: 48rem (768px), where the dock gives way to the top capsule, and 64rem (1024px), where detail pages gain a second column. Both match the breakpoints ADR-064 already set for the dashboard.

|Area
 |Phone (base)
 |From 48rem
 |From 64rem
 |
|Navigation
 |Top bar with wordmark, live state, search and Run; floating dock with Overview, Workflows, Executions, Artifacts, More
 |Capsule with all eight sections in the top bar; dock removed
 |Same
 |
|Page header
 |Icon 48px, title 30px, figures in two columns below
 |Icon 84px, title 44px, figures to the right
 |Same
 |
|Lists
 |One stacked row per item: name, bar, then a line of meta
 |Columns: badge, name, bar, tokens, cost, age
 |Same, full density
 |
|Filters
 |One row of chips that scrolls sideways; search full width
 |Chips wrap; search and time window on the right
 |Same
 |
|Detail pages
 |One column; side cards follow the main content
 |One column
 |Main column plus a 340px side column
 |
|Card grids
 |One column
 |Two or three columns by available width
 |Four columns
 |
|Skyline
 |Last 16 weeks
 |Full year
 |Full year
 |Rules for the CSS itself, taken from the upstream conventions:

- Base styles are the phone layout. Media queries are `min-width` only and written in rem.

- A component adapts to its own container with container queries; viewport queries are for page structure.

- Try `auto-fit` grids and wrapping flex rows before adding a breakpoint.

- Interactive targets are at least 44px on touch pointers, and nothing is reachable by hover alone.

- Titles and figures use `clamp()` so they scale between the phone and desktop sizes.

- No horizontal page scroll at 320px wide. Wide content such as mapping tables scrolls inside its own box.

- Motion is wrapped in `prefers-reduced-motion`.
The phone screens on the canvas are the visual reference for the base column of this table.

## Build order and acceptance
Six waves. Each lands its logic in `skyline-core` and its components in `skyline-svelte-v5` before the next starts; screens move into `apps/syn-ui` as their components arrive (see Migration plan).

- Foundation. Create `skyline-core`, `skyline-svelte-v5`, the themes package and `syn-ui-data`, both theme files and the `--sky-*` tokens. Wire Storybook, the upstream gate and the size budget into the monorepo's checks.

- Required surface. Button, Badge, Toggle, plus Card, Tag, Stat and Input. Both adapters export and pass the conformance type.

- Selection and filtering. Toggle Group, Switch, Tabs, Checkbox, Select, Pagination, Meter, Progress, Separator, Label.

- Shell and structure. Navigation Menu in both forms, Breadcrumbs, Scroll Area, Tooltip, Collapsible, Accordion, Callout, Empty State, Skeleton.

- Overlays. Dialog, Alert Dialog, Dropdown Menu, Popover, Command.

- Patterns. App Shell, Page Header, Object Icon, Status Badge, Run Row, Breadcrumb Trail, the charts (Skyline with Day Readout, Phase Blocks, Outcome Ring, Usage Meter, Verdict Board), Phase Kit, Skill Ref, Run Tiles, Provenance Strip, Operation Timeline with Copy Buttons, Agent Prompt Button, Lineage Trail, Rule Sentence.
A component is done when all of these hold:

- Props extend the upstream contract type; the adapter entry type-checks

- Native attributes pass through to the host element; component-owned attributes cannot be overridden

- CSS uses only `var(--ds-*)` and `var(--sky-*)`, with no colour literals and no `var()` fallbacks

- It has its own `:focus-visible` rule

- Base styles are the phone layout; it holds at 320px and at 200% zoom

- Touch targets reach 44px on coarse pointers

- Vitest and Testing Library tests cover every contract prop

- A Storybook story shows every variant in both themes and at phone width

- Geometry, formatting and state logic live in `skyline-core` with unit tests; the component only renders them

## Migration plan
The new UI is a new app, `apps/syn-ui`, built from the ground up in Svelte 5 beside the current dashboard. `apps/syn-dashboard-ui` is frozen: fixes only, no new features. Both apps talk to the same API, so nothing on the server changes, and the new app runs at `/next` until every route has passed its parity check.
Phase 4 is the switch that matters: until then the React dashboard stays at `/` and the new app is opt-in at `/next`.
How each screen moves:

- Put the screen's chart maths, formatting and state in `skyline-core` with unit tests, then build its missing components in `skyline-svelte-v5` with stories.

- Write the page in `apps/syn-ui` against `syn-ui-data`. Port what the React hooks fetch (`useEvalList`, `useEvalDetail` and the rest), not the hooks themselves, and remove N+1 calls on the way.

- Keep the route path identical, so swapping `/next` for `/` is the only change a link or bookmark needs.

- Tick the parity checklist: every field, action and state the old page has, or a recorded decision to drop it (the table below).

- Run the same Playwright suite against both apps by switching the base URL, then move to the next screen.

## Screen map
Every route in `apps/syn-dashboard-ui/src/App.tsx` has a home in the new UI. Eleven are designed on the canvas; four still need a board before they can move.

|Route
 |Canvas boards (desktop · phone)
 |Components and patterns it needs
 |Data or API gap
 |Phase
 |
|`/`
 |Overview · Phone Overview
 |App Shell, Page Header, Skyline with Day Readout, Run Row, Outcome Ring, Usage Meter
 |None: the contribution heatmap already returns each day's breakdown
 |2
 |
|`/executions`
 |Executions · Phone Executions
 |Run Row, Toggle Group, Checkbox, Pagination
 |None
 |2
 |
|`/executions/:id`
 |Execution detail · Phone Execution
 |Phase Blocks, Phase Row with Run Tiles, Provenance Strip, Usage Meter by phase
 |None for this design; start pins are missing on older runs and are shown as not recorded
 |2
 |
|`/sessions/:id`
 |Session detail · Phone Session
 |Operation Timeline with Copy Buttons, Usage Meter by model, Dialog for the transcript
 |Cost by token type is not in the API, so the meter splits cost by model only
 |2
 |
|`/workflows`
 |Workflows · Phone Workflows
 |Workflow Card, Skill Chip, Toggle Group, Pagination
 |`GET /workflows` does not return each workflow's skills; the cards need them without one request per workflow
 |3
 |
|`/workflows/:id`
 |Workflow detail · Phone Workflow
 |Phase Card with Phase Kit, Agent Prompt Button, Run Row
 |Each phase's latest output needs a query by workflow and phase
 |3
 |
|`/workflows/:id/runs`
 |Reuses Executions, filtered
 |Same as Executions
 |None
 |3
 |
|`/artifacts/:id`
 |Artifact viewer · Phone Artifact
 |Lineage Trail, Tabs, Collapsible outline
 |None
 |3
 |
|`/triggers`, `/triggers/:id`
 |Triggers · Phone Triggers
 |Switch, Rule Sentence, Tabs, Alert Dialog
 |None
 |3
 |
|`/evals`, `/evals/:id`
 |Evals, Eval detail · Phone Evals, Phone Eval
 |Verdict Board, Verdict Block, Day Readout pattern, Tag filter, Same-case strip
 |The board pivots evals by their `case:` and `workflow:` tags; a server-side pivot would save a request per eval. Real verdicts still to be read from the VPS
 |3
 |
|`/sessions`
 |Not designed yet
 |Run Row, Toggle Group, Pagination
 |None known
 |4
 |
|`/artifacts`
 |Not designed yet
 |Card grid, Tag filter
 |None known
 |4
 |
|`/repos`
 |Not designed yet
 |Card list, Status Badge
 |None known
 |4
 |
|`/insights`
 |Removed from the nav
 |None
 |Decide: redirect to Overview or keep as a hidden route
 |4
 |Loading, empty and error states are not drawn for any screen yet; they belong to phase 4 and gate the default switch.

## Platforms
One web build serves all three platforms; only the shell around it changes. The components never know which platform they run on: they read tokens and respond to their container's width.

|Platform
 |Shell
 |Ships in
 |What is different
 |
|Web, desktop browser
 |Top capsule nav, breadcrumb row, page max width 1400px
 |Phases 1 to 4
 |Nothing: this is the reference
 |
|Phone browser
 |Top bar, floating dock, collapsed breadcrumbs
 |Phases 1 to 4, same build
 |44px touch targets, chips scroll sideways, readouts sit under charts instead of floating. Installable as a PWA once phase 4 lands
 |
|Desktop app
 |Tauri 2 window (`apps/syn-desktop`) loading the `apps/syn-ui` build
 |Phase 5
 |Native menu bar, global ⌘K for the Command palette, tray dot for the Live state, deep links into executions
 |
|Non-Svelte hosts
 |Skyline as `<sky-*>` custom elements
 |When one is needed
 |`skyline-svelte-v5` also emits a custom-element build; core and themes import as they are
 |The phone dock is being redrawn: Overview and Executions keep their slots, Evals likely joins them, the fourth slot is still to be named, and More holds the rest.

## Design review decisions
The canvas review settled these; the migration builds them as decided, not as the current dashboard does them.

|Date
 |Decision
 |Where
 |
|Oct 8, 2026
 |Evals joins the nav; Insights leaves it
 |Top nav, every screen
 |
|Oct 8, 2026
 |Token usage and cost by model merge into one Usage Meter, reused on every screen that spends
 |Session, Execution, Usage meter sheet
 |
|Oct 8, 2026
 |Session Details card removed; usage sits above the operations list
 |Session
 |
|Oct 8, 2026
 |Every operation gets copy buttons for its input and output, plus Copy all
 |Session
 |
|Oct 8, 2026
 |Sessions and artifacts sit on the phase that owns them (Ran in, Produced); the inventory shrinks to a Provenance strip
 |Execution
 |
|Oct 8, 2026
 |The run box becomes one Copy agent prompt button; agents start runs, people copy the prompt
 |Workflow
 |
|Oct 8, 2026
 |Each phase shows what it gets: model, tools, skills
 |Workflow, Execution, Phase kit sheet
 |
|Oct 8, 2026
 |Breadcrumbs at the top of every screen except Overview
 |All detail and list screens
 |
|Oct 8, 2026
 |Skyline days are pointed at or stepped through, with a fixed readout
 |Overview
 |
|Oct 7, 2026
 |Phone first; the dock replaces the capsule under 48rem
 |All screens
 |
|Oct 7, 2026
 |Blue `#4D80FF` on a dark ground, top capsule nav, 3D object icons, one look on every screen
 |All screens
 |

## Changes needed upstream
Three upstream gaps block Skyline's first wave; the other five can follow.

|Change in the design-system repo
 |Why
 |Blocks Skyline
 |
|Publish `contracts` and `design-tokens`, or agree a submodule link
 |The registry returns 404 for both
 |Yes, wave 1
 |
|Decide the root font size for consumers
 |Upstream guidance sets the root to 62.5% so 1rem is 10px. The dashboard's Tailwind assumes 16px, so mixing the two shrinks one side by 37% during a gradual migration
 |Yes, before any CSS
 |
|Make the gate runnable from another repo
 |`verify-design-system.mjs` resolves `designs/` and the tokens file from its own repo root
 |Yes for enforcement; copying the script is a stopgap
 |
|Type-check planned contracts without promoting them
 |`RequiredComponentAdapter` covers 3 components. Promoting the 20 Skyline implements would force `default` and `brutalist` to implement them first
 |No
 |
|Add contracts for Card, Input, Tag and Breadcrumbs
 |Used on every screen with no neutral definition
 |No
 |
|Adopt the generic `--sky-*` tokens
 |Larger radii, type steps, control sizes, strong border, solid accent pair and data series are not Skyline-specific
 |No
 |
|Clarify Toggle
 |The `default` design draws Toggle as a switch; the contract describes a pressed button. Skyline draws a pressed chip and uses Switch for on and off
 |No
 |

## Open questions
The first four change what gets built in wave 1; the rest can wait.

- Upstream packages. Decided: publish them to npm under clearer names, `@syntropic137/design-contracts` and `@syntropic137/design-tokens`, so the design system is usable outside Syn137. A git submodule under `lib/` can bridge until the first publish.

- Root font size. Decided: keep the 16px browser default; components size in rem against it.

- React lane. Dropped: with Svelte 5 chosen, Skyline builds no React cell, so it no longer needs an upstream react-v19 lane.

- Names. Decided: Skyline is final, packages `@syn137/skyline-*` under `packages/syn-ui/`.

- Tailwind. Decided: Tailwind goes. Plain CSS with Skyline tokens everywhere, pages included.

- Completed colour. Blue as drawn on the canvas, or green from `--ds-color-success`?

- Light themes. Decided: the first release is dark only. The design system already supports light themes, so they follow later.

- Line icons. Decided: stay on Lucide for line icons; the 3D object icons are already Skyline's own SVG. A full custom icon set can come later.

- Reference copy. Mirror the neutral Skyline cells into the design-system repo as a third design, or keep them only in the monorepo?

- Phone dock. Not the current five. Overview and Executions stay, Evals likely joins, Workflows and Artifacts move behind More. The fourth slot is still to be named.

- Framework. Decided: Svelte 5 for the components and the app, rebuilt from the ground up in `apps/syn-ui` beside the frozen React dashboard. Contracts, tokens, chart geometry, formatting and the API client stay plain TypeScript (see Architecture).
Sources: cross-framework-ui-design-system at commit `e0db9ee`, issue #624, and the local Syntropic137 monorepo at commit `b969beaee`.
