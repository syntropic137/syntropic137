# Syn137 Pulse UI - Production Dockerfile
# Multi-stage build: Node build + nginx serve
#
# Build context: Repository root (not this directory)
# Build: docker build -f apps/syn-pulse-ui/Dockerfile -t syn-pulse-ui .

# =============================================================================
# Build Stage
# =============================================================================
FROM node:22-alpine AS builder

# Install pnpm
RUN corepack enable && corepack prepare pnpm@10.24.0 --activate

WORKDIR /app

# Copy workspace config and lockfiles for dependency caching
COPY pnpm-workspace.yaml ./
COPY pnpm-lock.yaml ./
COPY apps/syn-pulse-ui/package.json ./apps/syn-pulse-ui/

# Install dependencies (frozen lockfile for reproducibility)
RUN pnpm install --frozen-lockfile --filter syn-pulse-ui

# Copy pulse-ui source
COPY apps/syn-pulse-ui/ ./apps/syn-pulse-ui/

# Build the pulse UI
WORKDIR /app/apps/syn-pulse-ui
RUN pnpm build

# =============================================================================
# Serve Stage
# =============================================================================
FROM nginx:alpine AS runtime

# Copy custom nginx config for SPA routing
COPY apps/syn-pulse-ui/nginx.conf /etc/nginx/conf.d/default.conf

# Copy build output from builder stage
COPY --from=builder /app/apps/syn-pulse-ui/dist /usr/share/nginx/html

# Create non-root user and set permissions
RUN addgroup -g 1000 -S syn && \
    adduser -u 1000 -S syn -G syn && \
    chown -R syn:syn /usr/share/nginx/html && \
    chown -R syn:syn /var/cache/nginx && \
    chown -R syn:syn /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown syn:syn /var/run/nginx.pid

USER syn

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO /dev/null http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
