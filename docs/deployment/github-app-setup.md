# GitHub App Setup

This guide walks you through setting up a GitHub App for secure agent authentication with AEF.

## Why Use a GitHub App?

| Feature | Personal Access Token | GitHub App |
|---------|----------------------|------------|
| Token Lifetime | 30-90 days (configurable) | **1 hour (auto-rotating)** |
| Permissions | User-level (all repos) | **Per-installation (granular)** |
| Audit Trail | Shows as user | **Shows as `app[bot]`** |
| Rate Limits | User limits | **Higher app limits** |
| Revocation | Manual | **Automatic on uninstall** |
| Self-healing | ❌ | **✅ CI logs, PR comments** |

## Quick Start

### Step 1: Create the GitHub App

#### For Organizations (Recommended)

1. Go to **Organization Settings** → **Developer settings** → **GitHub Apps** → **New GitHub App**
2. URL: `https://github.com/organizations/YOUR-ORG/settings/apps/new`

#### For Personal Accounts

1. Go to **Settings** → **Developer settings** → **GitHub Apps** → **New GitHub App**
2. URL: `https://github.com/settings/apps/new`

### Step 2: Configure App Settings

#### Basic Information

| Field | Value |
|-------|-------|
| **GitHub App name** | `aef-engineer-beta` (or your choice) |
| **Homepage URL** | Your AEF dashboard URL or repo URL |
| **Webhook** | Uncheck "Active" for now (enable later for self-healing) |

#### Repository Permissions

| Permission | Access | Why |
|------------|--------|-----|
| **Contents** | Read & Write | Push commits, read code |
| **Metadata** | Read-only | Required for all apps |
| **Pull requests** | Read & Write | Create PRs, read/write comments |
| **Actions** | Read-only | Read workflow runs, logs, artifacts |
| **Checks** | Read & Write | Read check results, create check runs |
| **Commit statuses** | Read & Write | Set status checks on commits |
| **Issues** | Read & Write | If agents create/update issues |

### Step 3: Create the App

Click **Create GitHub App**

### Step 4: Generate Private Key

1. On the app settings page, scroll to **Private keys**
2. Click **Generate a private key**
3. Save the downloaded `.pem` file securely
4. **⚠️ This is the only time you can download this key!**

### Step 5: Install App

1. Go to **Install App** tab (left sidebar)
2. Click **Install** next to your organization/account
3. Choose **All repositories** or **Only select repositories**
4. Click **Install**

### Step 6: Get Installation ID

After installing, look at the URL:
```
https://github.com/settings/installations/99311335
                                          ^^^^^^^^
                                          This is your Installation ID
```

### Step 7: Configure Environment

Add to your `.env` file:

```bash
# GitHub App - Required
AEF_GITHUB_APP_ID=2461312
AEF_GITHUB_APP_NAME=aef-engineer-beta
AEF_GITHUB_INSTALLATION_ID=99311335
AEF_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
<paste your .pem file contents here>
-----END RSA PRIVATE KEY-----"

# Git Identity - For commits
AEF_GIT_USER_NAME=aef-engineer-beta[bot]
AEF_GIT_USER_EMAIL=2461312+aef-engineer-beta[bot]@users.noreply.github.com
```

### Step 8: Test Configuration

```bash
uv run python -c "
from aef_shared.settings import get_settings
settings = get_settings()
github = settings.github

print(f'✓ App ID: {github.app_id}')
print(f'✓ App Name: {github.app_name}')
print(f'✓ Installation ID: {github.installation_id}')
print(f'✓ Configured: {github.is_configured}')
print(f'✓ Bot Username: {github.bot_username}')
print(f'✓ Bot Email: {github.bot_email}')
"
```

Expected output:
```
✓ App ID: 2461312
✓ App Name: aef-engineer-beta
✓ Installation ID: 99311335
✓ Configured: True
✓ Bot Username: aef-engineer-beta[bot]
✓ Bot Email: 2461312+aef-engineer-beta[bot]@users.noreply.github.com
```

---

## Environment Variables Reference

| Variable | Required | Secret? | Description |
|----------|----------|---------|-------------|
| `AEF_GITHUB_APP_ID` | Yes | No | Numeric App ID from settings page |
| `AEF_GITHUB_APP_NAME` | Yes | No | App slug for commit attribution |
| `AEF_GITHUB_INSTALLATION_ID` | Yes | No | Installation ID per org/account |
| `AEF_GITHUB_PRIVATE_KEY` | Yes | **YES** 🔐 | RSA private key (PEM format) |
| `AEF_GITHUB_WEBHOOK_SECRET` | For webhooks | **YES** 🔐 | HMAC secret for verification |

---

## Commit Attribution

With proper configuration, agent commits appear as:

```
Author: aef-engineer-beta[bot] <2461312+aef-engineer-beta[bot]@users.noreply.github.com>
```

This provides:
- ✅ Clear identification as automated commit
- ✅ Proper attribution in GitHub UI
- ✅ Easy filtering: `git log --author="[bot]"`

---

## Security Best Practices

1. **Never commit `.pem` files** - Add `*.pem` to `.gitignore`
2. **Use secrets management** in production (AWS Secrets Manager, Vault, etc.)
3. **Rotate keys periodically** - Generate new private keys and revoke old ones
4. **Minimum permissions** - Only enable permissions you actually need
5. **Monitor installations** - Review which repos have access periodically

---

## Troubleshooting

### "Private key is invalid"

- Ensure the entire PEM content is included (including `-----BEGIN/END-----` lines)
- Check for extra whitespace or line breaks
- Verify you're using the correct key for this app

### "Installation not found"

- Verify the Installation ID matches the installed org/account
- Ensure the app is still installed (check `https://github.com/settings/installations`)

### "Resource not accessible by integration"

- The app doesn't have permission for the requested action
- Update permissions in app settings and re-install

---

## Next Steps

- [Environment Configuration](../env-configuration.md) - Full env var reference
- [Git Identity Setup](git-identity-setup.md) - Additional credential options
- [Production Deployment](production-deployment.md) - Deploy with Docker/Kubernetes
