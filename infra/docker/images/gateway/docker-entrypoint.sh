#!/bin/sh
set -e

# Generate nginx auth config and shared locations from env vars.
# When SYN_API_PASSWORD is set: basic auth on port 8081 (tunnel).
# Port 80 (localhost) is always unauthenticated.
AUTH_DIR="/tmp/nginx-auth"
mkdir -p "$AUTH_DIR"

# --- Auth config (included by port 8081 server block) ---
if [ -n "${SYN_API_PASSWORD:-}" ]; then
    USER="${SYN_API_USER:-admin}"
    htpasswd -cb "$AUTH_DIR/.htpasswd" "$USER" "$SYN_API_PASSWORD"
    cat > "$AUTH_DIR/auth.conf" <<EOF
auth_basic "Syntropic137";
auth_basic_user_file ${AUTH_DIR}/.htpasswd;
EOF
    echo "nginx: basic auth enabled on port 8081 (user: ${USER})"
else
    cat > "$AUTH_DIR/auth.conf" <<EOF
auth_basic off;
EOF
fi

# --- Shared locations (included by both server blocks) ---
cat > "$AUTH_DIR/locations.conf" <<'LOCATIONS'
# GitHub webhook endpoint — NO auth (uses HMAC signature verification)
location = /api/v1/webhooks/github {
    auth_basic off;
    proxy_pass http://api:8000/webhooks/github;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;

    limit_req zone=webhooks burst=30 nodelay;
    limit_req_status 429;
}

# API v1 proxy
location /api/v1/ {
    proxy_pass http://api:8000/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_cache_bypass $http_upgrade;
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;

    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self' wss: ws:; font-src 'self' https://cdn.jsdelivr.net; frame-ancestors 'self';" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    limit_req zone=api burst=50 nodelay;
    limit_req_status 429;
}

# WebSocket proxy
location /ws/ {
    proxy_pass http://api:8000/ws/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 86400;
}

# Legacy WebSocket path
location /api/v1/ws {
    proxy_pass http://api:8000/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 86400;
}

# SSE endpoint
location /api/v1/stream {
    proxy_pass http://api:8000/stream;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 86400;
    chunked_transfer_encoding off;
}

# Health check — no auth
location /health {
    auth_basic off;
    access_log off;
    return 200 "healthy\n";
    add_header Content-Type text/plain;
    include /etc/nginx/conf.d/security-headers.conf;
}

# Static assets (dashboard)
location /assets/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
    include /etc/nginx/conf.d/security-headers.conf;
}


# SPA routing (dashboard — root)
location / {
    try_files $uri $uri/ /index.html;
}

# Error pages
error_page 500 502 503 504 /50x.html;
location = /50x.html {
    root /usr/share/nginx/html;
}
LOCATIONS
