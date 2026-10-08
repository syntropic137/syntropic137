# Syn137 Gateway - Production Dockerfile
# Multi-stage build: Node for UI builds, nginx for serving + reverse proxy
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/gateway/Dockerfile -t gateway .

# =============================================================================
# Build Stage — Dashboard UI
# =============================================================================
FROM node:22-alpine AS dashboard-builder

# Install pnpm
RUN corepack enable && corepack prepare pnpm@10.24.0 --activate

WORKDIR /workspace

# Copy workspace config and lockfiles for dependency caching
COPY pnpm-workspace.yaml ./
COPY pnpm-lock.yaml ./
COPY apps/syn-dashboard-ui/package.json ./apps/syn-dashboard-ui/
# @syn137/ui-feedback-react is a workspace dependency of the dashboard
# (ADR-016), and pnpm-workspace.yaml lists it, so --frozen-lockfile needs its
# manifest here to resolve the link.
COPY lib/ui-feedback/packages/ui-feedback-react/package.json ./lib/ui-feedback/packages/ui-feedback-react/

# Install dependencies (frozen lockfile for reproducibility)
RUN pnpm install --frozen-lockfile --filter 'syn-dashboard-ui...'

# The widget is consumed from source (the package's `main` is src/index.ts),
# so the build needs it, not just its manifest.
COPY lib/ui-feedback/packages/ui-feedback-react/ ./lib/ui-feedback/packages/ui-feedback-react/

# Copy dashboard source
COPY apps/syn-dashboard-ui/ ./apps/syn-dashboard-ui/

# Build for production
# API_URL is set to /api - nginx will proxy to backend
WORKDIR /workspace/apps/syn-dashboard-ui
ENV VITE_API_URL=/api
RUN pnpm build

# =============================================================================
# Build Stage — Skyline UI (apps/syn-ui), served at /next
# =============================================================================
# The Svelte 5 rebuild runs beside the React dashboard at /next until every
# route passes its parity check (Skyline spec, Migration plan). The React build
# above still owns /; nothing in that stage changes.
FROM node:22-alpine AS skyline-builder

RUN corepack enable && corepack prepare pnpm@10.24.0 --activate

WORKDIR /workspace

COPY pnpm-workspace.yaml ./
COPY pnpm-lock.yaml ./
# Manifests first so the install layer caches across source edits. The four
# workspace packages export source (no build step), so the app needs them all.
COPY apps/syn-ui/package.json ./apps/syn-ui/
COPY packages/syn-ui/themes/package.json ./packages/syn-ui/themes/
COPY packages/syn-ui/skyline-core/package.json ./packages/syn-ui/skyline-core/
COPY packages/syn-ui/skyline-svelte-v5/package.json ./packages/syn-ui/skyline-svelte-v5/
COPY packages/syn-ui/data/package.json ./packages/syn-ui/data/

RUN pnpm install --frozen-lockfile --filter 'syn-ui...'

COPY packages/syn-ui/ ./packages/syn-ui/
COPY apps/syn-ui/ ./apps/syn-ui/

# SYN_UI_BASE sets Vite's base, so asset URLs and the router live under /next/.
# API calls stay absolute (/api/v1), served by the same locations as the React
# app. `build` also runs the 100 KB first-load size budget.
WORKDIR /workspace/apps/syn-ui
ENV SYN_UI_BASE=/next/
RUN pnpm build

# =============================================================================
# Runtime Stage
# =============================================================================
FROM nginx:1.28.2-alpine AS runtime

# Copy built dashboard assets (served at /)
COPY --from=dashboard-builder /workspace/apps/syn-dashboard-ui/dist /usr/share/nginx/html

# Copy built Skyline assets (served at /next; see locations.conf in the entrypoint)
COPY --from=skyline-builder /workspace/apps/syn-ui/dist /usr/share/nginx/html/next

# Copy nginx configuration
COPY infra/docker/images/gateway/nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/docker/images/gateway/security-headers.conf /etc/nginx/conf.d/security-headers.conf
COPY infra/docker/images/gateway/rate-limit.conf /etc/nginx/conf.d/00-rate-limit.conf
COPY infra/docker/images/gateway/log-format.conf /etc/nginx/conf.d/00-log-format.conf

# Install apache2-utils for htpasswd (used by auth entrypoint)
RUN apk add --no-cache apache2-utils

# Copy entrypoint (generates auth config from env vars at startup)
COPY infra/docker/images/gateway/docker-entrypoint.sh /docker-entrypoint.d/40-auth.sh
RUN chmod +x /docker-entrypoint.d/40-auth.sh

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=5s \
    CMD wget -q --spider http://localhost:80/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
