# Git Identity & Credentials Setup

**Problem**: Agents running in isolated containers cannot commit code without git configuration.

**Solution**: Inject git identity and credentials when creating workspaces.

---

## Quick Start

### 1. Local Development

Use your existing GitHub identity:

```bash
# Set environment variables (add to .env)
export SYN_GIT_USER_NAME="$(git config user.name)"
export SYN_GIT_USER_EMAIL="$(git config user.email)"
export SYN_GIT_TOKEN="$(gh auth token)"  # Requires GitHub CLI
```

### 2. CI/CD / Production

Create a bot account:

```bash
# Bot identity
export SYN_GIT_USER_NAME="syn-bot[bot]"
export SYN_GIT_USER_EMAIL="bot@syn137.dev"
export SYN_GIT_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
```

---

## Identity Sources

| Environment | Identity | Committer | Credentials |
|-------------|----------|-----------|-------------|
| **Local** | User's `.gitconfig` | Your name/email | `gh auth token` |
| **CI/CD** | Bot account | `syn-bot[bot]` | GitHub token |
| **Production** | GitHub App | `syn-app[bot]` | App installation token |

---

## Credential Types

### Option 1: HTTPS Token (Recommended for Getting Started)

```bash
# Create a Personal Access Token (PAT) at:
# https://github.com/settings/tokens/new
#
# Required scopes:
# - repo (full control)
# - workflow (if modifying GitHub Actions)

export SYN_GIT_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
```

**Pros:**
- ✅ Simple setup
- ✅ Works everywhere

**Cons:**
- ❌ Long-lived (manual rotation)
- ❌ No fine-grained permissions

### Option 2: GitHub App (Recommended for Production)

```bash
# Create a GitHub App at:
# https://github.com/settings/apps/new
#
# Required permissions:
# - Contents: Read & Write
# - Metadata: Read-only
# - Pull requests: Read & Write (if needed)

export SYN_GITHUB_APP_ID="123456"
export SYN_GITHUB_PRIVATE_KEY="$(cat app-private-key.pem)"
```

**Pros:**
- ✅ Tokens expire in 1 hour (automatic rotation)
- ✅ Fine-grained permissions (per-repo)
- ✅ Audit trail (shows as `app[bot]`)

**Cons:**
- ❌ More complex setup

### Option 3: SSH Key

```bash
# Generate SSH key (if you don't have one)
ssh-keygen -t ed25519 -C "syn-bot@yourdomain.com" -f ~/.ssh/syn137_bot_key

# Add to GitHub: https://github.com/settings/keys

export SYN_GIT_SSH_KEY="$(cat ~/.ssh/syn137_bot_key | base64)"
```

**Pros:**
- ✅ More secure than HTTPS
- ✅ No token in git URLs

**Cons:**
- ❌ Requires SSH key management
- ❌ More complex to inject

---

## Commit Metadata

All agent commits include metadata for traceability:

```
commit abc123def456
Author: syn-bot[bot] <bot@syn137.dev>
Date:   Wed Dec 11 19:30:00 2025

    feat: implement code review suggestions

    Applied by Syn137 agent
    - Workflow: code-review-workflow
    - Execution: exec-123456
    - Session: session-789
    - Agent: python-pro
    - Timestamp: 2025-12-11T19:30:00Z

    Co-authored-by: NeuralEmpowerment <neuralempowerment@gmail.com>
```

### Benefits

- ✅ Full audit trail
- ✅ Links to workflow execution
- ✅ Credit to human who initiated
- ✅ Easy filtering: `git log --author="syn-bot[bot]"`

---

## GitHub App Setup (Production)

### 1. Create GitHub App

1. Go to **Settings > Developer settings > GitHub Apps > New GitHub App**
2. Fill in:
   - **Name**: `syn137-production` (or your org name)
   - **Homepage URL**: Your Syn137 dashboard URL
   - **Webhook**: Uncheck "Active" (not needed)
3. **Permissions**:
   - Repository permissions:
     - **Contents**: Read & Write
     - **Metadata**: Read-only
     - **Pull requests**: Read & Write
4. Click **Create GitHub App**

### 2. Generate Private Key

1. Scroll to **Private keys** section
2. Click **Generate a private key**
3. Save the downloaded `.pem` file securely

### 3. Install App to Repositories

1. Go to **Install App** tab
2. Select repositories (all or specific)
3. Note the **Installation ID** from URL: `github.com/settings/installations/{id}`

### 4. Store Credentials Securely

```bash
# In production, use a secrets manager (Vault, AWS Secrets Manager, etc.)
# For local testing, use .env file (NEVER commit this):

cat > .env.github-app <<EOF
SYN_GITHUB_APP_ID="123456"
SYN_GITHUB_PRIVATE_KEY="$(cat syn-app.private-key.pem)"
EOF

chmod 600 .env.github-app
```

---

## Testing

### Test Commit in Container

```bash
# Start a test container with git identity
docker run --rm -it \
  -e GIT_USER_NAME="Syn137 Bot" \
  -e GIT_USER_EMAIL="bot@syn137.dev" \
  python:3.12-slim bash

# Inside container:
apt-get update && apt-get install -y git
git config --global user.name "$GIT_USER_NAME"
git config --global user.email "$GIT_USER_EMAIL"

# Test commit
git init /tmp/test && cd /tmp/test
echo "test" > file.txt
git add file.txt
git commit -m "test: agent commit"
git log --format="Author: %an <%ae>"
```

### Test with Syn137

```bash
# Run POC with git operations
just poc-isolation-quick

# Check if agent can commit
docker run --rm \
  -e SYN_GIT_USER_NAME="Test Bot" \
  -e SYN_GIT_USER_EMAIL="bot@test.dev" \
  syn-workspace:latest \
  git config --global --list
```

---

## Security Best Practices

| ✅ Do | ❌ Don't |
|------|----------|
| Use GitHub App tokens (1 hour expiry) | Use long-lived PATs |
| Store credentials in Vault/Secrets Manager | Hardcode tokens in config files |
| Rotate tokens regularly (90 days) | Share tokens across environments |
| Use fine-grained permissions | Use tokens with `admin:org` scope |
| Audit commit authors regularly | Allow anonymous commits |

---

## Troubleshooting

### Agent commits fail with "Author identity unknown"

**Cause**: Git identity not injected into container.

**Fix**:
```bash
# Check if environment variables are set
echo $SYN_GIT_USER_NAME
echo $SYN_GIT_USER_EMAIL

# Verify injection in container
docker exec <container_id> git config --global --list
```

### Push fails with "authentication failed"

**Cause**: No git credentials injected.

**Fix**:
```bash
# For HTTPS:
export SYN_GIT_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"

# For SSH:
export SYN_GIT_SSH_KEY="$(cat ~/.ssh/id_ed25519 | base64)"
```

### Commits show wrong author

**Cause**: Environment variables not passed to container.

**Fix**:
```bash
# Verify environment variables in container:
docker exec <container_id> env | grep GIT
```

---

## Implementation Status

Current status of git identity features:

- [ ] Inject git identity in `WorkspaceRouter.create()`
- [ ] Add `GitConfig` to `IsolatedWorkspaceConfig`
- [ ] HTTPS token credential injection
- [ ] SSH key credential injection
- [ ] GitHub App token generation
- [ ] Commit metadata template
- [ ] Integration tests
- [ ] Documentation for bot account setup

Track in ADR-021: Isolated Workspace Architecture
