# AEF Egress Proxy

Network allowlist enforcement for isolated agent workspaces.

## Overview

The egress proxy uses [mitmproxy](https://mitmproxy.org/) to intercept and filter
all outbound HTTP/HTTPS traffic from agent containers. Only traffic to explicitly
allowed hosts passes through; all other traffic is blocked with a 403 response.

See [ADR-021: Isolated Workspace Architecture](../../docs/adrs/ADR-021-isolated-workspace-architecture.md)

## Quick Start

```bash
# Build the proxy image
just proxy-build

# Start the proxy
just proxy-start

# Test allowlist
just proxy-test
```

## Manual Usage

### Build

```bash
docker build -t aef-egress-proxy:latest -f docker/egress-proxy/Dockerfile docker/egress-proxy/
```

### Run

```bash
# With default allowlist
docker run -d --name aef-egress-proxy -p 8080:8080 aef-egress-proxy:latest

# With custom allowlist
docker run -d --name aef-egress-proxy -p 8080:8080 \
  -e ALLOWED_HOSTS="api.anthropic.com,github.com,pypi.org" \
  aef-egress-proxy:latest
```

### Configure Containers to Use Proxy

```bash
docker run --rm \
  -e HTTP_PROXY=http://host.docker.internal:8080 \
  -e HTTPS_PROXY=http://host.docker.internal:8080 \
  python:3.12-slim \
  python -c "import urllib.request; print(urllib.request.urlopen('https://api.anthropic.com').status)"
```

## Default Allowed Hosts

The following hosts are allowed by default:

| Host | Purpose |
|------|---------|
| `api.anthropic.com` | Claude API |
| `api.openai.com` | OpenAI API |
| `github.com` | Git operations |
| `api.github.com` | GitHub API |
| `raw.githubusercontent.com` | Raw file access |
| `pypi.org` | Python packages |
| `files.pythonhosted.org` | Python package files |
| `registry.npmjs.org` | npm packages |

## Customizing the Allowlist

Set the `ALLOWED_HOSTS` environment variable:

```bash
# Comma-separated list
ALLOWED_HOSTS="api.anthropic.com,github.com,custom.api.com"

# Wildcard subdomains
ALLOWED_HOSTS="*.github.com,*.anthropic.com"
```

## Testing the Allowlist

```bash
# This should succeed (github.com is allowed)
curl -x http://localhost:8080 https://github.com

# This should fail with 403 (evil.com is not allowed)
curl -x http://localhost:8080 https://evil.com
```

## Architecture

```
┌─────────────────────┐
│   Agent Container   │
│  (HTTP_PROXY set)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Egress Proxy      │
│   (mitmproxy)       │
│                     │
│  ┌───────────────┐  │
│  │ allowlist.py  │  │
│  │ - Check host  │  │
│  │ - Allow/Block │  │
│  └───────────────┘  │
└──────────┬──────────┘
           │
           ▼
    ┌──────┴──────┐
    │             │
    ▼             ▼
  ALLOWED      BLOCKED
  (passes)     (403)
```

## Security Considerations

1. **TLS Interception**: The proxy terminates TLS to inspect traffic.
   Containers trust the proxy's CA certificate.

2. **No DNS Bypass**: Containers should use the proxy for all traffic.
   Consider `--network=none` with explicit proxy access.

3. **Logging**: All blocked requests are logged for audit.

## Troubleshooting

### Proxy not starting

```bash
# Check for port conflicts
lsof -i :8080

# Check Docker logs
docker logs aef-egress-proxy
```

### Container can't reach proxy

```bash
# Verify proxy is accessible from container
docker run --rm curlimages/curl curl -v http://host.docker.internal:8080
```

### SSL errors

```bash
# For testing, you may need to disable SSL verification
# (not recommended for production)
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org package
```
