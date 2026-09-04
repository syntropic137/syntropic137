#!/bin/sh
set -e

# Generate nginx auth config and shared locations from env vars.
#
# Two listeners, one rule: a listener that is reachable from beyond this host
# requires Basic Auth.
#
#   Port 8081 is the tunnel listener. It is never host-published, but
#     cloudflared reaches it from the internet, so its auth follows
#     SYN_API_PASSWORD exactly as before.
#
#   Port 80 is the listener the host publishes, at SYN_GATEWAY_BIND. While
#     that is a loopback address the port is reachable from this host only,
#     so auth stays off and local dev/testing/Playwright is unaffected. Bound
#     anywhere else it is reachable from that network, so a password becomes
#     mandatory: without one this script exits non-zero and nginx never
#     starts (#1022). That is the whole point - before this, binding off
#     loopback published an unauthenticated API while SYN_API_PASSWORD sat
#     set in the operator's .env, protecting a port nothing published.
#
# A container cannot observe its own host port mapping, so the compose file
# has to pass SYN_GATEWAY_BIND in alongside the `ports:` entry that uses it.
# Forgetting that wiring would silently disarm the check, so it is enforced by
# ci/fitness/infrastructure/test_gateway_bind.py.
AUTH_DIR="${AUTH_DIR:-/tmp/nginx-auth}"
mkdir -p "$AUTH_DIR"

GATEWAY_BIND="${SYN_GATEWAY_BIND:-127.0.0.1}"

# 127.0.0.0/8, ::1 (docker accepts it bracketed or bare), and the name that
# resolves to them. Docker also treats an empty host IP as "every interface",
# which is emphatically not loopback and falls through to the default branch.
# `127.foo.example` is a hostname that merely starts with 127, so it is
# rejected before the numeric branch: guessing wrong there would fail open.
is_loopback() {
    case "$1" in
        localhost|::1|"[::1]") return 0 ;;
        127.*[!0-9.]*)         return 1 ;;
        127.*)                 return 0 ;;
        *)                     return 1 ;;
    esac
}

if ! is_loopback "$GATEWAY_BIND" && [ -z "${SYN_API_PASSWORD:-}" ]; then
    cat >&2 <<ERROR
gateway: refusing to start.

  SYN_GATEWAY_BIND=${GATEWAY_BIND} publishes the dashboard and the API to that
  network, and SYN_API_PASSWORD is empty, so nothing would ask a caller for
  credentials.

  Either set SYN_API_PASSWORD (generate one with: openssl rand -hex 32), or
  leave SYN_GATEWAY_BIND at 127.0.0.1 and reach the stack over a VPN or
  tunnel.
ERROR
    exit 1
fi

# --- Auth stanzas, one per listener ---
# Written unconditionally so nginx's `include` always resolves; "off" is a
# stanza too. The host listener also carries the brute-force backstop when it
# is exposed - the tunnel listener gets its equivalent at server scope in
# nginx.conf, which is left alone so an unauthenticated tunnel keeps today's
# throttling.
AUTH_USER="${SYN_API_USER:-admin}"
if [ -n "${SYN_API_PASSWORD:-}" ]; then
    htpasswd -cb "$AUTH_DIR/.htpasswd" "$AUTH_USER" "$SYN_API_PASSWORD"
fi

write_auth_off() {
    cat > "$AUTH_DIR/$1" <<EOF
auth_basic off;
EOF
}

write_auth_on() {
    cat > "$AUTH_DIR/$1" <<EOF
auth_basic "Syntropic137";
auth_basic_user_file ${AUTH_DIR}/.htpasswd;
EOF
}

if [ -n "${SYN_API_PASSWORD:-}" ]; then
    write_auth_on auth-tunnel.conf
    echo "nginx: basic auth enabled on port 8081 (user: ${AUTH_USER})"
else
    write_auth_off auth-tunnel.conf
fi

if is_loopback "$GATEWAY_BIND"; then
    write_auth_off auth-host.conf
else
    write_auth_on auth-host.conf
    cat >> "$AUTH_DIR/auth-host.conf" <<EOF
limit_req zone=auth burst=20 nodelay;
limit_req_status 429;
EOF
    echo "nginx: basic auth enabled on port 80 (user: ${AUTH_USER}, bind: ${GATEWAY_BIND})"
fi

# --- Shared locations (included by both server blocks) ---
cat > "$AUTH_DIR/locations.conf" <<'LOCATIONS'
# Keep redirects relative. nginx auto-appends a trailing slash for prefix
# locations (e.g. /api/v1 -> /api/v1/) and by default builds an absolute URL
# from the listen port and scheme, leaking the internal :8081 port and
# downgrading https->http in the Location header. Relative redirects avoid both.
absolute_redirect off;
port_in_redirect off;

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

    # A location with its own limit_req does NOT inherit the server-scope auth
    # backstop, so declare it here too: /api/v1/ is Basic-Auth-protected and must
    # not fall back to the looser api-zone rate for credential guessing. Both
    # zones apply; the more restrictive wins per request. The webhook location
    # below is unauthenticated (HMAC-verified), so it keeps only its own zone.
    limit_req zone=api burst=50 nodelay;
    limit_req zone=auth burst=20 nodelay;
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

# Health check — no auth. Exact match on /health and /healthz only: a prefix
# location would leave everything under /health* (e.g. /healthfoo) unauthenticated,
# so any future route mounted there would silently inherit the auth bypass.
location ~ ^/healthz?$ {
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


# SPA routing (dashboard — root). The brute-force backstop is applied at server
# scope for whichever listener is authenticated (8081 in nginx.conf, port 80 via
# auth-host.conf when it is bound off loopback), so it covers this and every
# other Basic-Auth path without throttling a loopback-only port 80. Nothing to
# add here.
location / {
    try_files $uri $uri/ /index.html;
}

# Error pages
error_page 500 502 503 504 /50x.html;
location = /50x.html {
    root /usr/share/nginx/html;
}
LOCATIONS
