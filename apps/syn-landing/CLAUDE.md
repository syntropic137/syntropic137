# AGENTS.md: apps/syn-landing (syntropic137.com)

The public marketing site. Vite + React 19 + TypeScript, plain CSS, deployed on
Vercel. It moved into this monorepo by `git subtree` from
syntropic137/syntropic137-landing-page (history kept); this copy is now the source of truth.
`CLAUDE.md` here is an identical copy of this file: edit AGENTS.md, then copy it.

The root `AGENTS.md` applies too (git workflow, no rebases, no force-pushes).

## Rebuild in progress

The page is being rebuilt on Skyline in phases. Read `design/landing-plan.md`
first: section 3 (decisions), 5 (page map), 6 (phases), 7 (rules). Boards live
in `design/canvas/`; if a board and the plan disagree, the board wins for
visuals and the plan for architecture.

## Commands (from the repo root)

| Recipe | Does |
|---|---|
| `just landing-dev` | Vite dev server |
| `just landing-build` | Production build into `apps/syn-landing/dist` |
| `just landing-preview` | Serve the build (`LANDING_PORT`, default 3000) |
| `just landing-qa` | Copy lint, typecheck, build |
| `just landing-lighthouse` | Lighthouse against `vite preview` with the CI minimums |
| `just landing-energy` | `tests/energy.spec.ts` (about 2 minutes) |

Or `pnpm --filter syn-landing <script>`. Dependencies come from the root
`pnpm-lock.yaml` (pnpm workspace); there is no npm lockfile.

## Gates (`.github/workflows/syn-landing.yml`)

Path-filtered to `apps/syn-landing/**`, `packages/syn-ui/**` and the pnpm
install inputs. They bind every change:

- **No em dashes** in `src/`, `index.html` or `README.md`
  (`scripts/check-copy.sh`). Use a period, comma or colon.
- **Lighthouse minimums** (desktop): Performance 90, Accessibility 90,
  Best Practices 85, SEO 90 (`lighthouserc.json`).
- **Idle CPU** (`tests/energy.spec.ts`): under 500ms of CPU over 5s of idle,
  measured after 35s, and no infinite CSS animations (only `border-orbit` is
  allowed). Every animation runs a few cycles and stops on a static end state.
- Typecheck (`tsc --noEmit`), build, CodeQL and gitleaks.

## Deployment

Vercel, from the `release` branch only (`vercel.json`: `git.deploymentEnabled`).
There are no preview deployments; PRs are checked by the CI gates above.
`scripts/vercel-ignore-build.sh` skips a release build when nothing under this
app, `packages/syn-ui` or the pnpm inputs changed. `VITE_GITHUB_STARS` (see
`.env.example`) is set in the Vercel project.

## Design system

Skyline: `docs/syntropic137-design-system.md` points at it. The old
`--color-*` / `--glass-*` tokens in `src/globals.css` are swapped for
Skyline's in P5; until then, don't add new ones.

<!-- VERCEL BEST PRACTICES START -->
## Best practices for developing on Vercel

These defaults are optimized for AI coding agents (and humans) working on apps that deploy to Vercel.

- Treat Vercel Functions as stateless + ephemeral (no durable RAM/FS, no background daemons), use Blob or marketplace integrations for preserving state
- Edge Functions (standalone) are deprecated; prefer Vercel Functions
- Don't start new projects on Vercel KV/Postgres (both discontinued); use Marketplace Redis/Postgres instead
- Store secrets in Vercel Env Variables; not in git or `NEXT_PUBLIC_*`
- Provision Marketplace native integrations with `vercel integration add` (CI/agent-friendly)
- Sync env + project settings with `vercel env pull` / `vercel pull` when you need local/offline parity
- Use `waitUntil` for post-response work; avoid the deprecated Function `context` parameter
- Set Function regions near your primary data source; avoid cross-region DB/service roundtrips
- Tune Fluid Compute knobs (e.g., `maxDuration`, memory/CPU) for long I/O-heavy calls (LLMs, APIs)
- Use Runtime Cache for fast **regional** caching + tag invalidation (don't treat it as global KV)
- Use Cron Jobs for schedules; cron runs in UTC and triggers your production URL via HTTP GET
- Use Vercel Blob for uploads/media; Use Edge Config for small, globally-read config
- If Enable Deployment Protection is enabled, use a bypass secret to directly access them
- Add OpenTelemetry via `@vercel/otel` on Node; don't expect OTEL support on the Edge runtime
- Enable Web Analytics + Speed Insights early
- Use AI Gateway for model routing, set AI_GATEWAY_API_KEY, using a model string (e.g. 'anthropic/claude-sonnet-4.6'), Gateway is already default in AI SDK
  needed. Always curl https://ai-gateway.vercel.sh/v1/models first; never trust model IDs from memory
- For durable agent loops or untrusted code: use Workflow (pause/resume/state) + Sandbox; use Vercel MCP for secure infra access
<!-- VERCEL BEST PRACTICES END -->
