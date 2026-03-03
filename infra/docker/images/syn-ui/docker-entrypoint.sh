#!/bin/sh
set -e

# Generate nginx auth config from env vars.
# When SYN_API_PASSWORD is set: basic auth on all routes (except webhooks/health).
# When unset: no auth applied (local-only or Cloudflare Access mode).
# Write to /tmp/nginx-auth (tmpfs on read-only FS)
AUTH_DIR="/tmp/nginx-auth"
mkdir -p "$AUTH_DIR"

AUTH_CONF="$AUTH_DIR/auth.conf"

if [ -n "${SYN_API_PASSWORD:-}" ]; then
    USER="${SYN_API_USER:-admin}"
    htpasswd -cb "$AUTH_DIR/.htpasswd" "$USER" "$SYN_API_PASSWORD"
    cat > "$AUTH_CONF" <<EOF
# Auto-generated — basic auth enabled (user: ${USER})
auth_basic "Syntropic137";
auth_basic_user_file ${AUTH_DIR}/.htpasswd;
EOF
    echo "nginx: basic auth enabled (user: ${USER})"
else
    cat > "$AUTH_CONF" <<EOF
# Auto-generated — no auth (SYN_API_PASSWORD not set)
auth_basic off;
EOF
fi
