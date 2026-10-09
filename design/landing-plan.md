# Plan: rebuild syntropic137.com on the Skyline component system

Hand this whole file to an agent. Everything ends up in **one repo**, the monorepo `syntropic137/syntropic137` (local: `~/Code/Syntropic137/syntropic137`):

| Where | What changes | Deploys |
|---|---|---|
| `packages/syn-ui/*` | Skyline gets the new shared pieces | none (workspace packages) |
| `apps/syn-landing` (new: **moved in** from `syntropic137/syntropic137-landing-page`, local `~/Code/Syntropic137/syntropic137-landing-page`) | The landing page, rebuilt on Skyline | Vercel → syntropic137.com |
| `apps/syn-docs` (the documentation package, already here) | Same theme (section 4e, P9) | Vercel → docs.syntropic137.com |
| `apps/syn-ui` | Dashboard picks up the S logo and harness chips (4d) | self-hosted |

All the apps use Skyline straight from the pnpm workspace (`workspace:*`), so a single PR can change a component and every place that uses it. Nothing is published to npm for now. Don't build the landing page inside `apps/syn-docs`.

The upstream design system stays its own repo (`~/Code/Syntropic137/cross-framework-ui-design-system`, see 2b).

Open small draft PRs, one per phase. Never edit `apps/syn-dashboard-ui`.

## 1. What we're building and why

The new landing page sells one idea: **agent work that compounds.**

> Syntropic137 turns your coding agents into repeatable workflows. Run them on any harness, see every step, and make every run better than the last.

The four pillars, always in this order:
1. Repeatable workflows
2. Any harness (Claude Code or Codex, per phase)
3. Fully observable
4. Compounding improvement (evals)

The landing page, the dashboard and later the docs share one component system, so a visual change happens once.

## 2. Assets

**Everything lives in one folder:** `~/Code/Syntropic137/handoffs/20261009_syntropic137_skyline-redesign/`. Paths below are relative to it. (A packed copy is also in the monorepo's untracked `.skyline-handoff/`.)

```
~/Code/Syntropic137/handoffs/20261009_syntropic137_skyline-redesign/
├── README.md                   ← start here
├── LANDING-MIGRATION-PLAN.md   ← this plan
├── DESIGN-PROCESS-PROMPT.md    ← how designs flow into the repo
├── skyline-spec.md             ← component library spec (snapshot)
├── design/canvas/*.dc.html     ← every design board, unpacked, plus canvas.json
├── design/reference/*.py       ← generator source: geometry for the S, the city, the explorer and the trends
├── brand/s-mark.svg            ← S logo (fixed colours) and s-mark.themable.svg
└── bundles/                    ← git bundles, PR descriptions and push-prs.sh (branch delivery)
```

| Asset | Path | Use |
|---|---|---|
| Design boards, latest | `design/canvas/Landing.dc.html` (desktop), `design/canvas/PhoneLanding.dc.html` (phone) | The v4 landing page: layout, copy, motion, sample data. |
| Older landing versions | `design/canvas/LandingV1` to `LandingV3` | History only. |
| Dashboard boards | everything else in `design/canvas/` | Source of the shared visuals: Skyline chart, verdict blocks, usage band, trend charts. |
| Generator source | `design/reference/gen_landing*.py`, `design/reference/gen_trends.py` | Exact geometry for the S mark, the isometric city, the eval explorer and the trend lines. Port the maths to TypeScript; don't run them. |
| S mark, fixed colours | `brand/s-mark.svg` | Favicon, social image, README, anywhere CSS variables don't work. |
| S mark, themable | `brand/s-mark.themable.svg` | Reads `--ac`. Reference for the component. |
| Original raster logos | landing page (`apps/syn-landing` after P4): `public/assets/logo_syntropic137.png`, `logo_syntropic137_blue.png` | The original S built from cubes. The vector S is traced from it: blue top row, one glass cube, dark lower cubes. |
| Spec | `skyline-spec.md` | Tokens, components, patterns, rules. |
| Live canvas (view and comments) | https://claude.ai/artifact/M1bgLdL1fgrkwnPQZj32H9, "Landing" page | Look at the motion here. |

In the monorepo, copy `design/canvas/` and `design/reference/` from the folder above into the repo's `design/`. Add to it if the design-process PR already created `design/`. The landing page, the docs and the dashboard all read from that same `design/` folder.

### 2a. Design links (open these first)

| What | Link | Notes |
|---|---|---|
| Design canvas (all boards, comments) | https://claude.ai/artifact/M1bgLdL1fgrkwnPQZj32H9 | Four pages: **Desktop** and **Phone** (dashboard screens), **System** (components and patterns), **Landing** (website). Interactive: hover, click, switch tabs. |
| Skyline component library spec (living doc) | https://claude.ai/code/artifact/f33e0d42-6f88-43e4-a0d8-c7a8a937dee6 | Architecture, tokens, component inventory, patterns, migration plan, open questions. `skyline-spec.md` is a snapshot of it; the link is newer if they differ. |
| Upstream design system repo | https://github.com/syntropic137/cross-framework-ui-design-system (local: `~/Code/Syntropic137/cross-framework-ui-design-system`) | Source of the component contracts and the `--ds-*` token roles Skyline builds on (see 2b). |

These links open for the owner. If the agent can't sign in to claude.ai, use the boards in `design/canvas/` and `skyline-spec.md`: the same content, as files.

Which board to open for each piece of work (in the canvas or in `design/canvas/`):

| Work | Desktop board | Phone board | Canvas page |
|---|---|---|---|
| Landing page (build from this) | `Landing.dc.html` (v4) | `PhoneLanding.dc.html` | Landing |
| Landing page, previous version (comparison only) | `LandingV3.dc.html` | `PhoneLandingV3.dc.html` | Landing |
| Eval explorer, trend charts, quality score and judge | `Eval.dc.html` (Trend panel), `Landing.dc.html` (section 04) | `PhoneEval.dc.html` | Desktop, Phone |
| Workflow performance, duration graphs | `Workflow.dc.html`, `Workflows.dc.html` | `PhoneWorkflow.dc.html`, `PhoneWorkflows.dc.html` | Desktop, Phone |
| Verdict blocks, Skyline chart, usage band, phase kit | `CompPatterns.dc.html`, `UsageMeter.dc.html`, `PhaseKit.dc.html`, `Main.dc.html` | `PhoneOverview.dc.html` | System, Desktop |
| Base components and tokens | `Foundations.dc.html`, `CompActions.dc.html`, `CompDisplay.dc.html`, `CompNav.dc.html` | none | System |
| App shell (nav, dock) | `TopNav.dc.html` | `PhoneTop.dc.html`, `PhoneDock.dc.html` | System |

### 2b. The upstream design system (`cross-framework-ui-design-system`)

Skyline is built on the upstream design system, not beside it:
- **Contracts:** `@syntropic137/design-contracts` holds framework-neutral TypeScript types (prop contracts) for 43 components. Skyline's Svelte components implement them, and `skyline-core/src/contracts/` is a temporary copy of them until the package is published.
- **Tokens:** `@syntropic137/design-tokens` defines the `--ds-*` token roles (colour, surface, border, font, radius). `skyline-themes` sets their values for the Syntropic137 theme and adds Skyline-only `--sky-*` tokens. Never redefine a `--ds-*` role under a new name.
- **Pending upstream work:** branch `feat/publish-design-contracts`, 6 commits, delivered as `bundles/design-system.bundle` and pushed by `push-prs.sh`. It renames the contracts package to `design-contracts` (ADR-0010), makes both packages publishable, ships a typed token-name list, and lets the design-system gate run from another repo. Its PR description is `bundles/pr-design-system.md`.
- **Order of work:**
  1. Land and publish the upstream packages before (or together with) P4.
  2. Replace Skyline's temporary contracts copy with `@syntropic137/design-contracts`, as type-only imports.
  3. Make the Skyline workspace packages depend on `@syntropic137/design-tokens`.

  Until the upstream publish happens, bridge with a git submodule under `lib/`.
- **New components:** when 4c adds a component that upstream could also use (`HarnessChip`, `CodeWindow`, `CommandCopy`), check whether it fits an existing upstream contract first. If none fits, ship it as Skyline-only and note in the PR that it's a candidate for upstream. Domain-specific ones (`SMark`, `IsoCity`, `EvalExplorer`) stay Skyline-only.
- **The upstream gate:** run the upstream design-system gate (made runnable from another repo by that branch) in the monorepo's CI for `packages/syn-ui/**`.

## 3. Decisions (already made, don't reopen)

- **The landing page moves into the monorepo as `apps/syn-landing`, keeping its stack:** Vite + React 19, plain CSS, Vercel. No framework change.
  - Bring its history with `git subtree add --prefix=apps/syn-landing <landing-repo> main`, and add it to `pnpm-workspace.yaml`. Its npm lockfile goes away in favour of pnpm.
  - **Vercel:** point the existing syntropic137.com project at the monorepo with root directory `apps/syn-landing`. The SPA rewrite in `vercel.json` moves along with it.
    - **Turn preview deployments off;** the owner keeps hitting Vercel's limits. Build only production from `main`: set `"git": {"deploymentEnabled": {"main": true, "*": false}}` in `apps/syn-landing/vercel.json` and in `apps/syn-docs/vercel.json`, or the equivalent project setting.
    - Also add an "Ignored Build Step" so `main` only deploys when something under that app or `packages/syn-ui/**` changed.
    - PRs are checked by CI (Lighthouse, screenshots) instead of preview deploys.
  - **CI:** the landing repo's gates move into `.github/workflows/syn-landing.yml`, path-filtered to `apps/syn-landing/**` and `packages/syn-ui/**`, with the same pinned action SHAs. The gates are the Lighthouse thresholds, `tests/energy.spec.ts`, the em-dash copy lint and `security.yml`. Lighthouse runs against a local `vite preview` build, not a Vercel preview.
  - Its `CLAUDE.md` merges into `apps/syn-landing/CLAUDE.md`, and `docs/syntropic137-design-system.md` is replaced by a pointer to Skyline.
  - Once syntropic137.com deploys from the monorepo, archive the old repo with a README pointing at `apps/syn-landing`. Archiving is the human's call; ask first.
- **How the apps use Skyline (workspace, no npm):**

  | Package (workspace name) | What the landing page and docs take from it |
  |---|---|
  | `@syn137/skyline-core` | Geometry, formatters, ranking (plain TypeScript, usable from React directly) |
  | `@syn137/skyline-themes` | `syn137.css`, `motion.css`, the typed token list |
  | `@syn137/skyline-svelte-v5` (its custom-element build) | `<sky-*>` web components for the React apps. React can't render Svelte components, so the landing page and docs use the elements, while `apps/syn-ui` (Svelte) uses the components directly. |

  - Publishing to npm under `@syntropic137/skyline-*` is a later step, for when someone outside the monorepo needs them. Don't build it now.
- **Who owns what:**
  - **Product visuals live in Skyline and are shared:** the S mark, the run city, the eval explorer, harness chips and lanes, the tool-log ticker, the usage band. The landing page uses them as `<sky-*>` elements; React 19 passes props to custom elements as properties.
  - **Marketing layout lives in `apps/syn-landing` as React:** the nav, hero layout, section headers, pillar layout, use-case cards, comparison table, footer. It's styled only with Skyline tokens, because nothing else needs it.
- **Tokens:** the landing page's `--color-*` / `--glass-*` / `--grid-*` tokens in `src/globals.css` and `docs/syntropic137-design-system.md` are replaced by Skyline's `--ds-*` and `--sky-*` tokens from `@syn137/skyline-themes`.
  - Keep a short alias block while migrating, then delete it.
  - Update the design-system doc to point at Skyline.
- **Fonts:** UI text moves from Inter to Instrument Sans so the site matches the app; Orbitron stays for the wordmark, JetBrains Mono for code. If you'd rather keep Inter everywhere, that's a one-token change in the theme.
- **Keep from the current site:**
  - `src/data/harnesses.ts`, the single source for harness names and colours (wire its colours to `--sky-harness-*`);
  - `GitHubStars` (live star count, behind `VITE_GITHUB_STARS`);
  - `InstallCmd` and `InstallTerminal`, restyled as the copy-command box;
  - `pages/Links.tsx`, skip link, `robots.txt`, `sitemap.xml`, meta tags.
- **Remove:**
  - the hero video (`hero_syntropic137.mp4/.webm` from `public/` and `assets/`, plus `ide_reveal_v15_bloom_v2.mp4`);
  - `EntropyAnimation`;
  - any section the new page map doesn't use.

  The run city and the S replace them, at a fraction of the weight.
- **The numbers in the product previews are sample data.** Keep them in `src/data/sample.ts`, commented as samples.

## 4. Component changes (monorepo)

### 4a. `skyline-core` (plain TypeScript, unit-tested)
| Add or change | What it does | Notes |
|---|---|---|
| `geometry/isoCube.ts` (new, shared primitive) | `isoCube({x, y, size, height, tone}) → {top, left, right}` polygon point strings | Refactor the verdict blocks, object icons, phase blocks and `extrude` onto it, so one cube shape serves the whole brand. |
| `geometry/sMark.ts` (new) | `sMark(cubeSize) → cubes[]` with tone `blue`/`dark`/`glass` and a draw order | Grid `BBG / B.. / DDD / ..D / DDD`, cubes in one vertical plane running down-right. Port `s_mark()` from `design/reference/gen_landing3.py`. |
| `geometry/isoCity.ts` (new) | `isoCity(days[], {cols, rows, cell}) → blocks[]`: height from activity, tone from status, draw order, viewBox | Port `city()` from `design/reference/gen_landing2.py`. Driven by the same per-day series as the Overview skyline. |
| `screens/evals/ranking.ts` (new) | Ranks verifiers by quality per dollar and writes the one-line verdict ("Up 15 points… and $0.17 cheaper per run") | Port `EXPLORER_JS` from `design/reference/gen_landing3.py`. Reused by the app's Evals list. |
| `format/` | Add `pointsPerDollar` and signed deltas ("+24 pts", "−$0.11") | Extend; don't duplicate. |

### 4b. `skyline-themes`
These are tokens only (`--sky-*`). No colour literals anywhere else.
- **Display type:** `--sky-font-display` (Instrument Sans 600) at sizes `-xl` 112px, `-l` 84px, `-m` 64px, `-s` 44px; phone sizes 52, 44 and 36. Tracking −0.045em, line-height 0.95. `--sky-font-wordmark` is Orbitron.
- **Light and depth:** `--sky-glow-accent`, `--sky-gradient-text`, `--sky-surface-glass`, `--sky-border-gradient`.
- **Texture:** `--sky-texture-grain` (the noise data-URI) and `--sky-texture-dots` (the 28px dot grid).
- **Motion:**
  - `--sky-ease-out-back`, `--sky-ease-out`, and durations `--sky-dur-1` to `--sky-dur-4`.
  - `motion.css` holds the keyframes: rise, sdrop, pulse, flash, drift, bob, type, blink, draw, scroll.
  - Every keyframe sits under `@media (prefers-reduced-motion: no-preference)`, and the default is the static end state.
- **Harness colours:** `--sky-harness-claude` `#D97757`, `--sky-harness-codex` `#8E9BBC`. Check them against the landing page's current harness gradients, and keep the gradients if they're better.

### 4c. `skyline-svelte-v5` and the elements build
New shared patterns go in `src/patterns/`, and each is exported as a custom element:

| Pattern | Element | Props (minimum) | Used by |
|---|---|---|---|
| `SMark` | `sky-s-mark` | `size`, `animate`, `label` | Landing nav, hero and footer; the app's top nav, phone top bar and empty states |
| `IsoCity` | `sky-iso-city` | `days`, `live`, `failed`, `errored`, `animate`, `drift` | Landing hero; an optional Overview header in the app later |
| `EvalExplorer` | `sky-eval-explorer` | `verifiers` (name, colour, score series, cost series), `passAt`, `judge`, `selected` | Landing pillar 04; a compact mode on the app's Evals list |
| `HarnessChip` | `sky-harness-chip` | `provider`, `label` | Landing; the app's Execution, Workflow and Session pages |
| `HarnessLanes` | `sky-harness-lanes` | `phases` (name, provider, span) | Landing pillar 02; the Workflow detail header in the app |
| `ToolLogTicker` | `sky-tool-log` | `rows`, `speed` | Landing pillar 03; the app's live execution view |
| `UsageBand` (exists as part of the Usage Meter) | `sky-usage-band` | `tokens` by type | Landing pillar 03 and "What it is" |

Every element needs:
- a static, server-friendly first render, so the shape shows even before its script runs;
- a story on `/dev/patterns`, unit tests for its core maths, and screenshot tests at 1440px and 390px wide;
- a reduced-motion check.

It also needs a size check: the landing page's whole elements payload must stay under 45 KB gzipped. Share one Svelte runtime chunk between the elements rather than bundling it into each.

### 4d. Dashboard updates the new design implies
- Replace the placeholder cube logo in `TopNav`/`PhoneTop` with `SMark`; use `brand/s-mark.svg` for the favicons and the PWA icon.
- Use `HarnessChip` wherever a phase shows its model.
- Optional, behind a flag: the compact `EvalExplorer` ranking ("Ranked by quality per dollar") on the Evals list.

### 4e. Docs redesign (`apps/syn-docs` in the monorepo)
Context for the agent:
- **Stack:** Next.js 16 + Fumadocs 16 (`fumadocs-ui`, `fumadocs-mdx`, `fumadocs-openapi`) + Tailwind 4, on Vercel at docs.syntropic137.com.
- **Content:** MDX in `content/docs/` (`guide/`, `cli/`, `api/`, `architecture/`, `workspaces/`).
- **Generated pages:** API pages come from `openapi.json`, CLI pages from `@syntropic137/cli` (`pnpm run generate`).

How to theme it:
- **Same repo, so use the workspace packages directly:** add `@syn137/skyline-themes` (and `@syn137/skyline-svelte-v5` elements only if a page embeds a shared visual) as `workspace:*` dependencies. Don't wait for P4's npm publish.
- **Theme by mapping, not rewriting.** `app/global.css` already overrides Fumadocs' `--color-fd-*` variables inside `@theme`. Point them at Skyline tokens, for example `--color-fd-background: var(--ds-color-bg)`, `--color-fd-primary: var(--ac)` and `--color-fd-border: var(--sky-color-border)`, plus fonts (`--sky-font-*`) and radii. Fumadocs layout, search, sidebar and MDX rendering stay as they are.
- **Light mode:** the docs offer light and dark today; dark is the default (`defaultTheme: 'dark'` in `app/layout.tsx`), and dark values live in the `.dark { … }` block of `app/global.css`. Skyline is dark-only for v1. Apply Skyline to dark mode, and keep the current light values until Skyline has a light theme. Don't drop the docs' light mode.
- **Brand:**
  - swap the logo in the docs nav (`components/DocsNav.tsx`, layout options) for `SMark`, as inline SVG from `brand/s-mark.svg`, or `sky-s-mark` if elements are loaded;
  - match the landing nav's links and order, with Docs selected;
  - restyle `DocsFooter`.
- **MDX components to restyle onto Skyline tokens:** `FeatureCard`/`FeatureGrid`, whose per-card `gradient` props (indigo, purple, cyan, green) collapse to the token set; also `Callout`, `Badge`, `GradientButton`, `HeadingCopyLinks`, `LLMCopyButton`. The shiki code theme should match the landing page's code windows.
- **Diagrams:** `components/diagrams/interactive/*` (React Flow) stays. Restyle only the node and edge colours through tokens.
- **Home route `app/(home)`:** the Three.js `HeroScene` and `components/hero/NetworkNodes.tsx` duplicate the landing page. Replace the docs home page per open question 3 (redirect, or a slim "start here" page in the new theme). Then remove the `three`, `@react-three/fiber` and `@react-three/drei` dependencies once `grep` shows nothing else imports them.
- **Leave alone:** the LLM routes (`app/llms*`, `/docs/*.txt`, `/docs/*.md` rewrites in `next.config.mjs`, `app/api/docs-txt`), the `/docs` redirect, the OpenAPI and CLI generation, and the `docs-drift`/`docs-lint` workflows.
- **Done when:**
  - every docs route renders in dark and light;
  - the LLM text routes are byte-identical before and after (diff them);
  - `pnpm --filter syn-docs build` and `types:check` pass;
  - the docs-lint and docs-drift workflows pass;
  - screenshots of the home page, a guide page, an API page and a CLI page are in the PR.

## 5. Landing page map (`apps/syn-landing`)

The copy is final and lives in the boards. Move all strings into `src/data/copy.ts`.

| # | New section (board) | Replaces today's | Build with |
|---|---|---|---|
| 1 | Hero: "Agent work that compounds." | `Hero`, `TextShimmer`, `EntropyAnimation`, hero video | React layout + `<sky-iso-city>` + `<sky-s-mark animate>` + three glass cards + headline numbers + `InstallTerminal` restyled with typing |
| 2 | What is Syntropic137? | `WhySyntropic` | React: 3 code-window cards (workflow file, phases with `<sky-harness-chip>`, recorded cost and score with `<sky-usage-band>`) |
| 3 | 01 Repeatable workflows | `HowItWorks` + `GitHubTriggers` | React pillar layout: YAML window, start-from cards, trigger rule sentence |
| 4 | 02 Any harness | `AgentControlPlane` | Pillar + `<sky-harness-lanes>`; harness names and colours from `harnesses.ts` |
| 5 | 03 Fully observable | `Observability` + `Security` | Pillar + `<sky-usage-band>` + `<sky-tool-log>`; isolation facts from `Security` |
| 6 | 04 Compounding improvement | (new) | `<sky-eval-explorer>` inside window chrome + the Capture/Replay/Judge/Decide strip |
| 7 | What people build with it | (new) | 6 use-case cards |
| 8 | Why a platform | parts of `WhySyntropic` | Comparison table |
| 9 | Make your agent work compound | `GetStarted`, `Install` | Closing call to action + `InstallCmd` + three steps + `<sky-s-mark>` with the outlined wordmark |
| 10 | Nav and footer | `Nav`, `Footer` | Restyled; `GitHubStars` stays in the nav. Nav links: Workflows, Harnesses, Observability, Evals, Docs (docs.syntropic137.com). |

Facts to keep accurate:
- **Install command:** `npx @syntropic137/setup init`. **Dashboard address:** `localhost:8137`.
- **Trigger examples** come from the monorepo's `apps/syn-docs/content/docs/guide/triggers.mdx`, for example `--event check_run.completed` and `syn triggers enable self-healing`.
- **Workflow YAML keys** come from `workflows/examples/*.yaml`: `phases[].agent.provider`/`model` and `prompt_template`.
- **Don't invent commands.** The Claude Code plugin has no "run workflow" command.

## 6. Phases and gates

| Phase | Repo | Scope | Done when |
|---|---|---|---|
| P0 Assets | monorepo | Unpack the boards and references into `design/`; add `brand/` SVGs | Committed; favicon and OG image made from `s-mark.svg` |
| P1 Tokens | monorepo | Section 4b + `motion.css` | Token lint passes (no literals outside themes); reduced-motion verified |
| P2 Core geometry | monorepo | Section 4a with unit tests | The `isoCube` refactor keeps the existing verdict, icon and phase-block screenshot baselines identical |
| P3 Patterns and elements | monorepo | Section 4c + dev pages + screenshot tests + elements build | Checks, tests and builds green; elements payload under 45 KB gzipped |
| P4 Move the landing page in | monorepo (+ upstream) | `git subtree add` the landing repo as `apps/syn-landing`; pnpm workspace; `syn-landing.yml` CI with all its gates; Vercel root directory, preview deployments off, ignored-build step. In parallel: land the upstream `feat/publish-design-contracts` PR and publish `design-contracts` and `design-tokens` (2b). | The unchanged landing page builds and passes Lighthouse, energy and em-dash checks in monorepo CI; a production deploy from `main` serves syntropic137.com; no preview deployments are created for PRs |
| P5 Tokens and shell | `apps/syn-landing` | Add the `@syn137/skyline-*` workspace dependencies, swap tokens and fonts, restyle `Nav` and `Footer`, remove the video and `EntropyAnimation` | Lighthouse thresholds still pass; em-dash lint passes |
| P6 Sections 1–5 | `apps/syn-landing` | Hero through 03 Observable | At 390px and 1440px wide, side by side with the boards (screenshots in the PR); energy test passes |
| P7 Sections 6–10 | `apps/syn-landing` | Explorer, use cases, comparison, closing call to action | Keyboard works throughout (explorer: arrow keys and focus); energy and Lighthouse pass |
| P8 Dashboard | monorepo | Section 4d (S logo in the app shell, harness chips, optional ranking) | Screenshot baselines updated on purpose; app checks green |
| P9 Docs | monorepo (`apps/syn-docs`) | Section 4e | Section 4e's done-when list |

## 7. Rules

These are the landing page's existing gates, now run by `syn-landing.yml` in the monorepo, and they bind every phase:
- **Idle CPU:** `tests/energy.spec.ts` allows under 500ms of CPU over 5s of idle, measured after 35s. So:
  - no animation may loop forever;
  - the city drift, the live pulses, the floating cards and the bobbing run for a few cycles (`animation-iteration-count`) and stop;
  - the tool-log ticker and the typing cursor run only while visible (IntersectionObserver) and stop after about 20s;
  - `text-shimmer` and `border-orbit`, which already loop forever, are removed or made finite.
- **No em dashes** in user-facing text (enforced in CI). The board copy uses em dashes in a few places; replace them with commas, colons or full stops.
- **Lighthouse minimums:** Performance 90, Accessibility 90, Best Practices 85, SEO 90. Aim for 95+.
- Every animation has a static end state and respects reduced motion.
- No colour literals outside `skyline-themes`, and no chart libraries.
- One draft PR per phase with screenshots next to the board; don't merge.
- If a board and this plan disagree, the board wins for visuals and this plan wins for architecture. Note the conflict in the PR.

## 8. Open questions for the human (ask, don't guess)

1. Inter or Instrument Sans for UI text on the landing page? (Plan default: Instrument Sans, matching the app.)
2. Social image: the S over the city (rendered from `brand/s-mark.svg`), or keep `twitter-banner_syntropic137.png`?
3. Should `docs.syntropic137.com`'s own home page redirect to the landing page or to `/docs/guide/getting-started`?
4. Later: should the eval explorer read from a public demo instance instead of `sample.ts`?

## 9. Answers (2026-10-09)

1. UI text: Instrument Sans.
2. Social image: the S over the run city, generated from `skyline-core`'s `sMark()` and `isoCity()` (lands with P2, not P0).
3. docs.syntropic137.com home: redirect to `/docs/guide/getting-started`.
4. Open: eval explorer reads `sample.ts` for now.

Also decided:
- The handoff folder's Landing boards were v3 copies; `design/canvas/Landing.dc.html` and `PhoneLanding.dc.html` are v4, pulled from the live canvas.
- One-repo version of this plan (landing moves to `apps/syn-landing`); no npm publish of Skyline.
- Vercel: no PR previews. Docs deploy only from `release` (project ignored-build-step set, plus `git.deploymentEnabled` in `apps/syn-docs/vercel.json`). The landing project builds only `main` until it moves in, then `release` like docs.
- Assets in this repo: boards in `design/canvas/`, generators in `design/reference/`, the S mark and icons in `design/brand/`. Paths in this plan that say `brand/` mean `design/brand/`.
- Phase PRs stack on `feat/skyline-svelte` (#1764).
