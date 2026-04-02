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

# Install dependencies (frozen lockfile for reproducibility)
RUN pnpm install --frozen-lockfile --filter syn-dashboard-ui

# Copy ui-feedback source (resolved via Vite alias and tsconfig paths)
COPY lib/ui-feedback/packages/ui-feedback-react/ ./lib/ui-feedback/packages/ui-feedback-react/

# Copy dashboard source
COPY apps/syn-dashboard-ui/ ./apps/syn-dashboard-ui/

# Build for production
# API_URL is set to /api - nginx will proxy to backend
WORKDIR /workspace/apps/syn-dashboard-ui
ENV VITE_API_URL=/api
RUN pnpm build

# =============================================================================
# Build Stage — Pulse UI
# =============================================================================
FROM node:22-alpine AS pulse-builder

RUN corepack enable && corepack prepare pnpm@10.24.0 --activate

WORKDIR /workspace

COPY pnpm-workspace.yaml ./
COPY pnpm-lock.yaml ./
COPY apps/syn-pulse-ui/package.json ./apps/syn-pulse-ui/

RUN pnpm install --frozen-lockfile --filter syn-pulse-ui

COPY apps/syn-pulse-ui/ ./apps/syn-pulse-ui/

WORKDIR /workspace/apps/syn-pulse-ui
ENV VITE_BASE_PATH=/pulse/
RUN pnpm build

# =============================================================================
# Runtime Stage
# =============================================================================
FROM nginx:1.28.2-alpine AS runtime

# Copy built dashboard assets (served at /)
COPY --from=dashboard-builder /workspace/apps/syn-dashboard-ui/dist /usr/share/nginx/html

# Copy built pulse-ui assets (served at /pulse/)
COPY --from=pulse-builder /workspace/apps/syn-pulse-ui/dist /usr/share/nginx/html/pulse

# Copy nginx configuration
COPY infra/docker/images/gateway/nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/docker/images/gateway/security-headers.conf /etc/nginx/conf.d/security-headers.conf
COPY infra/docker/images/gateway/rate-limit.conf /etc/nginx/conf.d/00-rate-limit.conf

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
