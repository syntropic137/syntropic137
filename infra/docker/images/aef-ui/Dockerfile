# AEF Dashboard UI - Production Dockerfile
# Multi-stage build: Node for build, nginx for serving
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/aef-ui/Dockerfile -t aef-ui .

# =============================================================================
# Build Stage
# =============================================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm

# Copy package files for dependency installation
COPY apps/aef-dashboard-ui/package.json apps/aef-dashboard-ui/pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source files
COPY apps/aef-dashboard-ui/ ./

# Build for production
# API_URL is set to /api - nginx will proxy to backend
ENV VITE_API_URL=/api
RUN pnpm run build

# =============================================================================
# Runtime Stage
# =============================================================================
FROM nginx:alpine AS runtime

# Copy built assets to nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY infra/docker/images/aef-ui/nginx.conf /etc/nginx/conf.d/default.conf

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost:80/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
