# AEF Dashboard UI - Production Dockerfile
# Multi-stage build: Node for build, nginx for serving
#
# Build context: Repository root (not this directory)
# Build: docker build -f infra/docker/images/syn-ui/Dockerfile -t syn-ui .

# =============================================================================
# Build Stage
# =============================================================================
FROM node:20-alpine AS builder

# Install pnpm globally
RUN npm install -g pnpm

# Set up workspace structure matching the monorepo layout
# This is required because vite.config.ts uses relative paths like:
# path.resolve(__dirname, '../../lib/ui-feedback/...')
WORKDIR /workspace

# Copy ui-feedback package (dependency referenced in vite.config.ts)
COPY lib/ui-feedback/packages/ui-feedback-react/ ./lib/ui-feedback/packages/ui-feedback-react/

# Copy app package files for dependency installation
COPY apps/syn-dashboard-ui/package.json apps/syn-dashboard-ui/pnpm-lock.yaml ./apps/syn-dashboard-ui/

# Install dependencies from the app directory
WORKDIR /workspace/apps/syn-dashboard-ui
RUN pnpm install --frozen-lockfile

# Copy app source files (excluding node_modules already installed above)
COPY apps/syn-dashboard-ui/src ./src
COPY apps/syn-dashboard-ui/public ./public
COPY apps/syn-dashboard-ui/index.html ./index.html
COPY apps/syn-dashboard-ui/vite.config.ts ./vite.config.ts
COPY apps/syn-dashboard-ui/tsconfig*.json ./
COPY apps/syn-dashboard-ui/eslint.config.js ./eslint.config.js

# Build for production
# API_URL is set to /api - nginx will proxy to backend
ENV VITE_API_URL=/api
RUN pnpm run build

# =============================================================================
# Runtime Stage
# =============================================================================
FROM nginx:1.28.2-alpine AS runtime

# Copy built assets to nginx
COPY --from=builder /workspace/apps/syn-dashboard-ui/dist /usr/share/nginx/html

# Copy nginx configuration
COPY infra/docker/images/syn-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/docker/images/syn-ui/security-headers.conf /etc/nginx/conf.d/security-headers.conf
COPY infra/docker/images/syn-ui/rate-limit.conf /etc/nginx/conf.d/00-rate-limit.conf

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost:80/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
