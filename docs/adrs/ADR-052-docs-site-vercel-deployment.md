# ADR-052: Documentation Site Deployment via Vercel CLI

## Status

**Accepted** — 2026-03-31

## Context

The public documentation site (`apps/syn-docs/`, Fumadocs + Next.js) needs to be deployed to `docs.syntropic137.com`. The marketing landing page already runs on `syntropic137.com` via Vercel's git integration from a separate repo (`syntropic137-landing-page`).

Three deployment approaches were considered:

1. **Vercel git integration** — connect the monorepo to Vercel, set root directory to `apps/syn-docs/`. Simple, but exposes the entire monorepo to Vercel and deploys on every push — too noisy for a docs site.
2. **GitHub Actions + Vercel CLI** — build in CI, deploy via `vercel deploy --prod`. Full control over when deploys happen. Monorepo stays disconnected from Vercel.
3. **Static export + Cloudflare Pages** — `next export` to static files, deploy to Cloudflare. Loses SSR/ISR capabilities and Vercel's Next.js optimizations.

## Decision

Use **GitHub Actions + Vercel CLI** (Option 2) with release-only deployment.

### Why

- **Monorepo isolation** — the monorepo is not connected to Vercel. Only the deploy workflow has access via `VERCEL_TOKEN`.
- **Release-only deploys** — docs deploy alongside platform releases (`release: [published]`), not on every push. Docs should reflect released state, not work-in-progress.
- **Trunk-based dev compatibility** — no preview deploys on PRs by default. The CI `docs-site` job already validates the build. Manual `workflow_dispatch` available for preview deploys when needed.
- **Consistent pipeline** — follows the same pattern as `release-containers.yaml` (also triggered by releases).

### Deployment Trigger

| Event | Action |
|-------|--------|
| GitHub release published | Auto-deploy to `docs.syntropic137.com` |
| `workflow_dispatch` | Manual deploy (hotfixes, preview) |
| PR / push to main | No deploy — CI build check only |

### Build Pipeline

```
pnpm install → pnpm generate (CLI + OpenAPI docs) → pnpm build → vercel deploy --prod
```

The `generate` step runs two auto-generation scripts:
- `generate:cli` — introspects the Typer CLI app (`apps/syn-cli/`) and outputs MDX files
- `generate:openapi` — reads the OpenAPI spec and generates API reference pages

### Required GitHub Secrets

| Secret | Source |
|--------|--------|
| `VERCEL_TOKEN` | [vercel.com/account/tokens](https://vercel.com/account/tokens) |
| `VERCEL_ORG_ID` | `.vercel/project.json` after `vercel link` |
| `VERCEL_PROJECT_ID` | `.vercel/project.json` after `vercel link` |

### One-Time Setup

```bash
cd apps/syn-docs
npx vercel link
# Follow prompts to create/link the project
# Copy org_id and project_id from .vercel/project.json
# Add all three secrets to GitHub repo settings
```

Then configure the custom domain `docs.syntropic137.com` in the Vercel project dashboard and add a CNAME record in Cloudflare DNS:

```
docs.syntropic137.com → cname.vercel-dns.com
```

## Consequences

- Docs are always in sync with releases — users never see unreleased docs
- `workflow_dispatch` provides an escape hatch for urgent doc fixes
- The `docs-drift.yml` CI check on main ensures generated docs stay fresh between releases
- No Vercel build minutes consumed on PRs (only on releases + manual triggers)
- Landing page (`syntropic137.com`) and docs (`docs.syntropic137.com`) are separate Vercel projects with independent deploy cycles
