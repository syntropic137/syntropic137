# 🚇 Cloudflare Tunnel Setup for AEF Self-Host

This guide helps you set up secure external access to your self-hosted AEF deployment using Cloudflare Tunnel.

## Why Cloudflare Tunnel?

| Feature | Benefit |
|---------|---------|
| **No port forwarding** | Works behind NAT, firewalls, CGNAT |
| **Zero-trust security** | Cloudflare handles TLS termination |
| **DDoS protection** | Cloudflare's global network protects your server |
| **Free tier** | Tunnels are included in the free Cloudflare plan |

## Prerequisites

1. A **Cloudflare account** (free tier works)
2. A **domain** with DNS managed by Cloudflare
3. AEF stack running locally (test with `just infra-up` first)

## Quick Setup (Recommended)

### Step 1: Create Tunnel in Cloudflare Dashboard

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to: **Networks** → **Tunnels** → **Create a tunnel**
3. Select **Cloudflared** connector type
4. Name your tunnel: `syn-selfhost`
5. Click **Save tunnel**
6. **Copy the tunnel token** (long base64 string starting with `eyJ...`)

### Step 2: Configure Public Hostnames

In the tunnel configuration, add these public hostnames:

| Subdomain | Domain | Type | URL |
|-----------|--------|------|-----|
| `aef` | yourdomain.com | HTTP | `http://syn-ui:80` |
| `api.aef` | yourdomain.com | HTTP | `http://syn-dashboard:8000` |

**Important:** The service URLs use Docker container names, not `localhost`.

### Step 3: Configure Environment

```bash
# Navigate to infra directory
cd infra

# Copy environment template
cp .env.example .env

# Edit .env and add your tunnel token
# CLOUDFLARE_TUNNEL_TOKEN=eyJ...your-token...
# SYN_DOMAIN=aef.yourdomain.com
```

### Step 4: Generate Secrets

```bash
# From repo root
just secrets-generate

# Copy your GitHub App private key
cp ~/path/to/your-app.pem infra/docker/secrets/github-private-key.pem
```

### Step 5: Deploy

```bash
# Start the full self-hosted stack with Cloudflare Tunnel
just selfhost-up-tunnel

# Check status
just selfhost-status

# View tunnel logs
just selfhost-logs cloudflared
```

### Step 6: Verify Access

```bash
# Test external access (replace with your domain)
curl https://aef.yourdomain.com/health
curl https://api.aef.yourdomain.com/health
```

## Alternative: CLI Setup

If you prefer using the `cloudflared` CLI:

### Install cloudflared

```bash
# macOS
brew install cloudflared

# Ubuntu/Debian
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Windows (via scoop)
scoop install cloudflared
```

### Authenticate and Create Tunnel

```bash
# Login to Cloudflare
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create syn-selfhost

# Configure DNS routes
cloudflared tunnel route dns syn-selfhost aef.yourdomain.com
cloudflared tunnel route dns syn-selfhost api.aef.yourdomain.com

# Get tunnel token
cloudflared tunnel token syn-selfhost
```

Then add the token to your `.env` file as shown above.

## Tunnel Configuration (Advanced)

If you need to run cloudflared outside of Docker (e.g., as a system service), use this config template:

```yaml
# Copy to: tunnel-config.yaml
# Run with: cloudflared tunnel --config tunnel-config.yaml run

tunnel: <your-tunnel-id>
credentials-file: /path/to/credentials.json

ingress:
  # Main UI
  - hostname: aef.yourdomain.com
    service: http://localhost:80
    originRequest:
      noTLSVerify: true

  # API endpoint
  - hostname: api.aef.yourdomain.com
    service: http://localhost:8000
    originRequest:
      noTLSVerify: true

  # Catch-all (required)
  - service: http_status:404
```

## Troubleshooting

### Tunnel Not Connecting

```bash
# Check cloudflared container logs
just selfhost-logs cloudflared

# Common issues:
# - Invalid tunnel token → regenerate in dashboard
# - Network firewall blocking outbound 443 → allow HTTPS egress
```

### 502 Bad Gateway

```bash
# Verify services are running
just selfhost-status

# Check if services can reach each other
docker exec syn-ui wget -qO- http://syn-dashboard:8000/health
```

### DNS Not Resolving

```bash
# Check DNS propagation
dig aef.yourdomain.com

# Verify DNS records exist in Cloudflare dashboard
# Should show CNAME pointing to <tunnel-id>.cfargotunnel.com
```

### Connection Timeouts

The tunnel configuration uses these timeouts:
- HTTP requests: 300s (5 minutes)
- WebSocket connections: 86400s (24 hours)

If you experience timeouts, check:
1. Backend service health
2. Network connectivity between containers
3. Cloudflare dashboard for tunnel status

## Security Considerations

1. **Access Policies**: Add Cloudflare Access policies for authentication
2. **Rate Limiting**: Configure rate limiting in Cloudflare dashboard
3. **WAF Rules**: Enable Cloudflare WAF for additional protection
4. **Tunnel Token**: Keep your tunnel token secret - it grants full tunnel access

## Useful Commands

```bash
# Start self-hosted stack with tunnel
just selfhost-up-tunnel

# Stop self-hosted stack (auto-detects tunnel)
just selfhost-down

# View all logs
just selfhost-logs

# View tunnel logs only
just selfhost-logs cloudflared

# Check tunnel status
just selfhost-tunnel-status

# Restart specific service
just selfhost-restart cloudflared
```

## Related Documentation

- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Cloudflare Zero Trust](https://developers.cloudflare.com/cloudflare-one/)
- [AEF Self-Host Deployment Guide](../docs/selfhost-deployment.md)
