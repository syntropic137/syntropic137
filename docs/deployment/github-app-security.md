# GitHub App Security Model

This document describes how AEF securely integrates with GitHub using GitHub Apps instead of Personal Access Tokens (PATs).

## Why GitHub Apps?

| Feature | Personal Access Token | GitHub App |
|---------|----------------------|------------|
| **Token Lifetime** | 90 days - 1 year | 1 hour (installation token) |
| **Scope** | User's full access | Only installed repos |
| **Revocation** | Manual per-token | Instant per-installation |
| **Audit Trail** | Shows as user | Shows as `app[bot]` |
| **Rate Limits** | 5k/hour shared | 5k/hour per installation |
| **Rotation** | Manual | Automatic |

## Token Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AEF Control Plane                           │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                    GitHubAppClient                           │   │
│   │                                                             │   │
│   │   1. Load private key (from Vault/env)                      │   │
│   │   2. Generate JWT (10 min TTL, signed with private key)     │   │
│   │   3. Exchange JWT for installation token (1 hour TTL)       │   │
│   │   4. Cache token, refresh at 50 min                         │   │
│   │                                                             │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                   │                                  │
│                                   ▼                                  │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                    Token Vending Service                     │   │
│   │                                                             │   │
│   │   • Issues scoped tokens to sidecars                        │   │
│   │   • Tracks which execution has which token                  │   │
│   │   • Revokes all tokens when execution completes             │   │
│   │                                                             │   │
│   └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent Container                              │
│                                                                     │
│   Environment:                                                      │
│     GITHUB_API_URL=http://localhost:8080/github                    │
│     EXECUTION_ID=exec-abc123                                        │
│                                                                     │
│   NO GITHUB TOKEN! All git operations go through sidecar.          │
│                                                                     │
│   Git commands use credential helper that calls sidecar:           │
│     git config credential.helper '!sidecar-git-credential'         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Token Types

### 1. Private Key (Master Secret)

- **What**: RSA private key in PEM format
- **Where**: Vault, AWS Secrets Manager, or base64-encoded in env
- **Lifetime**: Until rotated (recommend: 90 days)
- **Access**: Control plane only, never in containers

```bash
# Generate new private key (done in GitHub App settings)
# Download .pem file, base64 encode for storage
cat aef-app.pem | base64 | tr -d '\n'
```

### 2. JWT Token (Ephemeral)

- **What**: JSON Web Token signed with private key
- **Lifetime**: 10 minutes maximum
- **Use**: Exchange for installation token
- **Access**: Control plane only

```python
payload = {
    'iat': now - 60,      # Issued 60 seconds ago (clock skew)
    'exp': now + 600,     # Expires in 10 minutes
    'iss': app_id,        # GitHub App ID
}
jwt_token = jwt.encode(payload, private_key, algorithm='RS256')
```

### 3. Installation Token (Short-Lived)

- **What**: OAuth-style token for API access
- **Lifetime**: 1 hour (GitHub enforced maximum)
- **Scope**: Only repos where app is installed
- **Access**: Sidecar only, never in agent container

```python
response = httpx.post(
    f'https://api.github.com/app/installations/{installation_id}/access_tokens',
    headers={'Authorization': f'Bearer {jwt_token}'},
)
installation_token = response.json()['token']
# Token format: ghs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Security Controls

### 1. Private Key Protection

```yaml
# Vault policy for private key
path "secret/data/aef/github/private-key" {
  capabilities = ["read"]
}

# Only Token Vending Service can access
allowed_entity_aliases = ["token-vending-service"]
```

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
        "AgentParadise/sandbox_aef-engineer-beta",
        "AgentParadise/agentic-engineering-framework"
    ]
}
```

### 3. Token Revocation

Tokens can be revoked in multiple ways:

```python
# 1. Automatic: Token expires after 1 hour

# 2. Execution complete: Revoke immediately
await token_vending.revoke_tokens(execution_id)

# 3. Emergency: Revoke all tokens for installation
httpx.delete(
    f'https://api.github.com/installation/token',
    headers={'Authorization': f'Bearer {installation_token}'},
)

# 4. Nuclear: Suspend entire GitHub App
# Done via GitHub.com UI
```

### 4. Audit Trail

All GitHub operations are auditable:

```json
// GitHub audit log entry
{
  "@timestamp": "2025-12-12T01:30:00Z",
  "action": "git.push",
  "actor": "aef-engineer-beta[bot]",
  "actor_id": 12345678,
  "repository": "AgentParadise/sandbox_aef-engineer-beta",
  "ref": "refs/heads/feature/agent-changes",
  "commit_sha": "abc1234"
}
```

```json
// AEF internal audit log
{
  "timestamp": "2025-12-12T01:30:00Z",
  "execution_id": "exec-abc123",
  "workflow_id": "code-review-v1",
  "operation": "git.push",
  "repository": "AgentParadise/sandbox_aef-engineer-beta",
  "commit_sha": "abc1234",
  "agent_session": "session-xyz"
}
```

## Commit Attribution

Commits made by the agent show clear bot attribution:

```
commit abc1234567890
Author: aef-engineer-beta[bot] <2461312+aef-engineer-beta[bot]@users.noreply.github.com>
Date:   Thu Dec 12 01:30:00 2025 -0800

    feat: implement code review suggestions

    Applied by AEF agent
    - Workflow: code-review-v1
    - Execution: exec-abc123
    - Session: session-xyz

    Co-authored-by: Neural <neural@example.com>
```

## Multi-Tenancy Considerations

For multi-tenant deployments (multiple organizations):

```python
# Each organization has its own installation
installations = {
    "org-a": "12345678",  # Installation ID for Org A
    "org-b": "87654321",  # Installation ID for Org B
}

# Tokens are scoped per-installation
async def get_token_for_org(org: str) -> str:
    installation_id = installations[org]
    return await github_client.get_installation_token(installation_id)
```

See GitHub Issue #24 for multi-tenancy implementation details.

## Configuration

### Environment Variables

```bash
# Required
AEF_GITHUB_APP_ID=2461312
AEF_GITHUB_APP_NAME=aef-engineer-beta
AEF_GITHUB_INSTALLATION_ID=99311335
AEF_GITHUB_PRIVATE_KEY=<base64-encoded-pem>

# Optional
AEF_GITHUB_WEBHOOK_SECRET=<hmac-secret>
```

### Pydantic Settings

```python
from aef_shared.settings import get_settings

settings = get_settings()
github = settings.github

# Check if configured
if github.is_configured:
    print(f"Bot: {github.bot_username}")      # aef-engineer-beta[bot]
    print(f"Email: {github.bot_email}")        # 2461312+aef-engineer-beta[bot]@...
```

## Troubleshooting

### Token Generation Fails

```python
# Check private key format
import base64
private_key = base64.b64decode(settings.github.private_key.get_secret_value())
assert private_key.startswith(b'-----BEGIN RSA PRIVATE KEY-----')

# Check app ID matches key
# JWT will fail signature verification if mismatched
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
# Check rate limit status
curl -H "Authorization: Bearer $TOKEN" \
  https://api.github.com/rate_limit
```

## Related Documentation

- [GitHub App Setup Guide](./github-app-setup.md)
- [ADR-022: Secure Token Architecture](../adrs/ADR-022-secure-token-architecture.md)
- [Environment Configuration](../env-configuration.md)
