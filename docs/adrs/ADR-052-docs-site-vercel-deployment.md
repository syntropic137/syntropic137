# ADR-052: Documentation Site Deployment via Vercel

## Status

**Superseded** — 2026-04-01 (originally accepted 2026-03-31)

Updated to use Vercel git integration instead of CLI-based deployment.

## Context

The public documentation site (`apps/syn-docs/`, Fumadocs + Next.js) needs to be deployed to `docs.syntropic137.com`. The marketing landing page already runs on `syntropic137.com` via Vercel's git integration from a separate repo (`syntropic137-landing-page`).

Three deployment approaches were considered:

1. **Vercel git integration** — connect the monorepo to Vercel, set root directory to `apps/syn-docs/`. Simple, automatic PR previews, production deploys on merge.
2. **GitHub Actions + Vercel CLI** — build in CI, deploy via `vercel deploy --prod`. Full control over when deploys happen, but requires managing secrets and no PR previews.
3. **Static export + Cloudflare Pages** — `next export` to static files. Loses SSR/ISR capabilities.

## Decision

Use **Vercel git integration** (Option 1) with the monorepo connected.

### Why (updated)

The original decision chose Option 2 (CLI-based) to avoid connecting the monorepo to Vercel. After further evaluation:

- **The repo is open source** — no security concern with Vercel having read access
- **PR previews are valuable** — seeing docs changes before merge catches layout/content issues
- **Less operational overhead** — no secrets to manage (`VERCEL_TOKEN`, org/project IDs), no workflow to maintain
- **Build scoping works** — Vercel's root directory setting (`apps/syn-docs`) and "Ignored Build Step" prevent unnecessary builds from unrelated monorepo changes
- **Production gating** — production branch can be set to a release branch if needed, or deploy on merge to main

### Vercel Project Configuration

| Setting | Value |
|---------|-------|
| **Root Directory** | `apps/syn-docs` |
| **Framework** | Next.js (auto-detected) |
| **Build Command** | `pnpm run build` |
| **Install Command** | `pnpm install` |
| **Production Branch** | `main` (or a release branch for gated deploys) |

### DNS

```
docs.syntropic137.com → cname.vercel-dns.com
```

Configure in Cloudflare DNS and add the custom domain in the Vercel project dashboard.

## Consequences

- Automatic PR preview URLs for docs changes
- Production deploys on merge to the production branch
- No GitHub secrets or CLI workflows to maintain
- CI `docs-site` job still validates the build independently
- Landing page (`syntropic137.com`) and docs (`docs.syntropic137.com`) remain separate Vercel projects
