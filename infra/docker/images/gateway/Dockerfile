# Syn137 Dashboard UI - Production Dockerfile
# Multi-stage build: Node for build, nginx for serving
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/gateway/Dockerfile -t gateway .

# =============================================================================
# Build Stage
# =============================================================================
FROM node:22-alpine AS builder

# Install pnpm (lockfile is v9.0)
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

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
# Runtime Stage
# =============================================================================
FROM nginx:1.28.2-alpine AS runtime

# Copy built assets to nginx
# Copy built dashboard assets from builder
COPY --from=builder /workspace/apps/syn-dashboard-ui/dist /usr/share/nginx/html

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
