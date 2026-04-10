# GitHub App Security Model

This document describes how Syn137 securely integrates with GitHub using GitHub Apps instead of Personal Access Tokens (PATs).

## Why GitHub Apps?

| Feature | Personal Access Token | GitHub App |
|---------|----------------------|------------|
| **Token Lifetime** | 90 days - 1 year | 1 hour (installation token) |
| **Scope** | User's full access | Only installed repos |
| **Revocation** | Manual per-token | Instant per-installation |
| **Audit Trail** | Shows as user | Shows as `app[bot]` |
| **Rate Limits** | 5k/hour shared | 5k/hour per installation |
| **Rotation** | Manual | Automatic |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Syn137 Control Plane (API container)            │
│                                                                     │
│   PEM key: /run/secrets/github_app_private_key (tmpfs, RAM-only)   │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                    GitHubAppClient                           │   │
│   │                                                             │   │
│   │   1. Read PEM from Docker secret (file path)                │   │
│   │   2. Generate JWT (10 min TTL, signed with PEM)             │   │
│   │   3. Exchange JWT for installation token (1 hour TTL)       │   │
│   │   4. Cache token, refresh at 50 min                         │   │
│   │                                                             │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                   │                                  │
│                           Setup Phase                                │
│                    (installation token only)                          │
│                                   │                                  │
└───────────────────────────────────┼──────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent Container                              │
│                                                                     │
│   Setup phase injects:                                              │
│     ~/.git-credentials        (installation token, 1-hour TTL)     │
│     ~/.config/gh/hosts.yml    (gh CLI auth)                        │
│                                                                     │
│   Then secrets are CLEARED from environment.                        │
│                                                                     │
│   NO PEM. NO raw signing key. Only the derived token.              │
│                                                                     │
│   All traffic routed through shared Envoy proxy:                   │
│     ANTHROPIC_BASE_URL=http://envoy-proxy:8081                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Token Types

### 1. PEM Key (Master Secret)

- **What**: RSA key in PEM format, downloaded from GitHub App settings
- **Where**: Docker secret at `/run/secrets/github_app_private_key` (tmpfs, RAM-only)
- **Lifetime**: Until rotated (recommend: 90 days)
- **Access**: API container only, never in agent containers

```bash
# Download .pem from GitHub App settings, then:
# Selfhost: place at ~/.syntropic137/secrets/github-app-private-key.pem
cp syn-app.pem ~/.syntropic137/secrets/github-app-private-key.pem
chmod 600 ~/.syntropic137/secrets/github-app-private-key.pem

# Docker Compose mounts it as a secret (tmpfs — never hits disk inside the container).
# The app reads it via SYN_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github_app_private_key
```

**Fallback (dev/CI):** Set `SYN_GITHUB_PRIVATE_KEY` as an env var with a `file:` path, raw PEM, or base64-encoded PEM. The Docker secret path takes priority when both are set.

### 2. JWT Token (Ephemeral)

- **What**: JSON Web Token signed with the PEM
- **Lifetime**: 10 minutes maximum
- **Use**: Exchange for installation token
- **Access**: API container only, never leaves the control plane

```python
payload = {
    'iat': now - 60,      # Issued 60 seconds ago (clock skew)
    'exp': now + 600,     # Expires in 10 minutes
    'iss': app_id,        # GitHub App ID
}
jwt_token = jwt.encode(payload, pem_key, algorithm='RS256')
```

### 3. Installation Token (Short-Lived)

- **What**: OAuth-style token for GitHub API access
- **Lifetime**: 1 hour (GitHub enforced maximum)
- **Scope**: Only repos where the app is installed
- **Access**: Baked into agent container during setup phase, then environment is cleared

```python
response = httpx.post(
    f'https://api.github.com/app/installations/{installation_id}/access_tokens',
    headers={'Authorization': f'Bearer {jwt_token}'},
)
installation_token = response.json()['token']
# Token format: ghs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **Note:** Installation tokens expire after 1 hour. For agent sessions exceeding 1 hour, token refresh is tracked in GitHub Issue #377.

## Security Controls

### 1. PEM Protection (Docker Secrets)

The PEM is mounted as a Docker secret — stored on tmpfs (RAM-only) inside the container:

- **Not visible** in `docker inspect` output
- **Not visible** in `/proc/1/environ` (not an env var)
- **Not visible** in `docker compose config` output
- **Not written** to the container filesystem (tmpfs only)
- **Host file** permissions: `0600` (owner read/write only)

```yaml
# docker-compose.syntropic137.yaml
secrets:
  github_app_private_key:
    file: ./secrets/github-app-private-key.pem

services:
  api:
    secrets:
      - github_app_private_key
    environment:
      SYN_GITHUB_APP_PRIVATE_KEY_FILE: /run/secrets/github_app_private_key
```

Only the API container has access to the PEM. Agent containers never see it.

### 2. Token Scoping

Installation tokens are automatically scoped to:
- Only repositories where the app is installed
- Only permissions granted to the app (contents, issues, PRs, etc.)

```python
# Example: Token can only access these repos
{
    "permissions": {
        "contents": "write",
        "pull_requests": "write",
        "issues": "read"
    },
    "repositories": [
        "syntropic137/sandbox_aef-engineer-beta",
        "syntropic137/syntropic137"
    ]
}
```

### 3. Token Revocation

```python
# 1. Automatic: Token expires after 1 hour (GitHub enforced)

# 2. Emergency: Revoke a specific installation token
httpx.delete(
    f'https://api.github.com/installation/token',
    headers={'Authorization': f'Bearer {installation_token}'},
)

# 3. Nuclear: Suspend entire GitHub App via GitHub.com UI
```

### 4. Network Isolation

Agent containers run on a restricted Docker network (`agent-net`):

- **Anthropic API**: Routed through shared Envoy proxy (`envoy-proxy:8081`). Agents hold a placeholder key (`proxy-managed`); the token injector (`ext_authz`) replaces it with the real credential. Direct calls to `api.anthropic.com` fail.
- **GitHub API**: Passthrough — agents use the installation token baked into `~/.git-credentials` during setup. The token injector does not handle GitHub auth.
- **Package registries**: Passthrough (pypi.org, npmjs.org, etc.)
- **All other hosts**: Blocked by the Envoy allowlist (returns 403).

### 5. Audit Trail

All GitHub operations are auditable:

```json
// GitHub audit log entry
{
  "@timestamp": "2025-12-12T01:30:00Z",
  "action": "git.push",
  "actor": "your-app-name[bot]",
  "repository": "org/repo",
  "ref": "refs/heads/feature/agent-changes",
  "commit_sha": "abc1234"
}
```

## Commit Attribution

Commits made by the agent show clear bot attribution:

```
commit abc1234567890
Author: your-app-name[bot] <APP_ID+your-app-name[bot]@users.noreply.github.com>
Date:   Thu Dec 12 01:30:00 2025 -0800

    feat: implement code review suggestions
```

The `[bot]` suffix is added by GitHub automatically for GitHub App installations.

## Configuration

### Selfhost (Docker Compose)

```bash
# In ~/.syntropic137/.env:
SYN_GITHUB_APP_ID=123456
SYN_GITHUB_APP_NAME=your-app-name
SYN_GITHUB_WEBHOOK_SECRET=<hmac-secret>

# PEM file (not an env var — mounted as Docker secret):
# Place at ~/.syntropic137/secrets/github-app-private-key.pem
```

The compose file sets `SYN_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github_app_private_key` automatically. Do not override it.

### Dev/CI (env var fallback)

```bash
# Option 1: file reference
SYN_GITHUB_PRIVATE_KEY=file:/path/to/app.pem

# Option 2: raw PEM (must start with -----BEGIN)
SYN_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."

# Option 3: base64-encoded PEM
SYN_GITHUB_PRIVATE_KEY=LS0tLS1CRUdJTi...
```

### Pydantic Settings

```python
from syn_shared.settings import get_settings

settings = get_settings()
github = settings.github

# Check if configured (requires app_id + either key file or env var)
if github.is_configured:
    print(f"Bot: {github.bot_username}")      # your-app-name[bot]
    print(f"Email: {github.bot_email}")        # APP_ID+your-app-name[bot]@...
```

## Token Injector Architecture

The token injector is an HTTP service implementing Envoy's `ext_authz` protocol. It runs alongside the Envoy proxy and handles credential injection for agent containers.

**What it handles:**
- **Anthropic API** — injects `x-api-key` (or `Authorization: Bearer` for OAuth) by replacing the `proxy-managed` placeholder

**What it does NOT handle:**
- **GitHub API** — passthrough. Agents use installation tokens from the setup phase.
- **Package registries** — passthrough (pypi.org, npmjs.org, etc.)

```
Agent Container                 Envoy Proxy              Token Injector (ext_authz)
      │                              │                              │
      │  ANTHROPIC_BASE_URL          │                              │
      │  = http://proxy:8081         │                              │
      │──── x-api-key: proxy-managed ──►                            │
      │                              │──── ext_authz check ────────►│
      │                              │                              │
      │                              │◄─── 200 + real x-api-key ───│
      │                              │                              │
      │                              │──── request to anthropic ───►│
```

See `docker/token-injector/` and `docker/sidecar-proxy/` for implementation.

## Troubleshooting

### PEM Not Found

```bash
# Verify the secret is mounted
docker exec syn137-api ls -la /run/secrets/github_app_private_key

# Verify the env var points to the right path
docker exec syn137-api printenv SYN_GITHUB_APP_PRIVATE_KEY_FILE
```

### Permission Denied

```bash
# Check app is installed on repo
gh api /repos/OWNER/REPO/installation

# Check app has required permissions
gh api /app | jq '.permissions'
```

### Rate Limiting

```bash
# Check rate limit status (use an installation token)
curl -H "Authorization: Bearer $TOKEN" \
  https://api.github.com/rate_limit
```

## Related Documentation

- [GitHub App Setup Guide](../../docs/deployment/github-app-setup.md)
- [ADR-022: Secure Token Architecture](../../docs/adrs/ADR-022-secure-token-architecture.md)
