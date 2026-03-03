# 1Password Secret Management

Secrets are stored in a single 1Password item and resolved transparently at
startup. No code changes are needed to consume them — pydantic sees the
resolved values exactly as if they were plaintext.

If the `op` CLI is not installed or not authenticated, resolution is silently
skipped and the system behaves exactly as it does today with plaintext `.env`.

---

## How Secrets Reach the Dashboard

There are **two independent paths** — you only need one:

| Path | How secrets get in | Good for |
|------|-------------------|----------|
| **Docker secret files** | Raw files in `infra/docker/secrets/` → mounted at `/run/secrets/` → entrypoint reads and exports as env vars | Simple selfhost without 1Password |
| **1Password** | `op_resolver.py` fetches from vault → injects into `os.environ` at startup | Portable, multi-machine, CI/CD |

Both paths end at the same place: env vars that pydantic reads. If both are
configured, 1Password takes precedence (existing env vars are never overwritten).

### What the selfhost stack actually needs

| Secret | Docker secret file | 1Password field | Notes |
|--------|-------------------|-----------------|-------|
| **GitHub App PEM** | `github-private-key.pem` (raw PEM) | `SYN_GITHUB_PRIVATE_KEY` (base64-encoded) | Entrypoint auto-encodes the PEM to base64 |
| **GitHub webhook secret** | `github-webhook-secret.txt` | `SYN_GITHUB_WEBHOOK_SECRET` | Plain text |
| **DB password** | `db-password.txt` | Not needed — entrypoint builds `DATABASE_URL` from the file | |
| **Redis password** | `redis-password.txt` | Not needed — entrypoint builds `REDIS_URL` from the file | |
| **Anthropic API key** | N/A | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` | Set in 1Password or `infra/.env` |
| **GitHub App ID** | N/A | `SYN_GITHUB_APP_ID` | Set in 1Password or `infra/.env` |
| **GitHub App name** | N/A | `SYN_GITHUB_APP_NAME` | Set in 1Password or `infra/.env` |

> **Database URLs are automatic.** `SYN_OBSERVABILITY_DB_URL` and `DATABASE_URL`
> are constructed by the selfhost entrypoint from Docker service names. You never
> need to set them manually.

---

## Path A: Docker Secret Files (No 1Password)

The simplest approach. Generate secrets, copy files, done.

```bash
# Generate DB and Redis passwords
just secrets-generate

# Copy your GitHub App .pem file
cp ~/Downloads/your-app.pem infra/docker/secrets/github-private-key.pem
chmod 600 infra/docker/secrets/github-private-key.pem

# Verify all files are in place
just secrets-check
```

Set the remaining non-secret values in `infra/.env`:

```bash
APP_ENVIRONMENT=development      # safety check — prevents prod secrets in dev
SYN_GITHUB_APP_ID=123456
SYN_GITHUB_APP_NAME=your-app-name
ANTHROPIC_API_KEY=sk-ant-...
```

That's it. The selfhost entrypoint reads the secret files and exports:
- `github-private-key.pem` → base64-encodes → `SYN_GITHUB_PRIVATE_KEY`
- `github-webhook-secret.txt` → `SYN_GITHUB_WEBHOOK_SECRET`
- `db-password.txt` → builds `DATABASE_URL`
- `redis-password.txt` → builds `REDIS_URL`

### GitHub App PEM — the tricky one

The `.pem` file you download from GitHub is a multi-line RSA key file.

**For Docker secrets (Path A):** Just copy the raw `.pem` file as-is. The
entrypoint handles the base64 encoding automatically.

**For 1Password (Path B):** You need to base64-encode it first:

```bash
# Encode and copy to clipboard (macOS)
cat ~/Downloads/your-app.pem | base64 | tr -d '\n' | pbcopy

# Or encode to stdout (Linux)
cat ~/Downloads/your-app.pem | base64 -w0
```

Paste the resulting base64 string as the `SYN_GITHUB_PRIVATE_KEY` field value
in 1Password.

> **Note:** You still need the raw `.pem` file in `infra/docker/secrets/` even
> with 1Password, because the event-store (Rust binary) doesn't use
> `op_resolver.py`. The entrypoint only bridges the gap for the dashboard.

---

## Path B: 1Password

### Structure

One vault per environment, one item per vault named **`syntropic137-config`**.
Each secret is a field on that item, labeled after its env var.

| Environment | Vault name |
|---|---|
| Local dev / self-host | `syn137-dev` |
| Beta / staging | `syn137-beta` |
| Production | `syn137-prod` |

### Creating the item

1. Open 1Password → select the vault (e.g. `syn137-dev`)
2. **+** → choose any type (API Credential works well)
3. Title: `syntropic137-config`
4. Add each field below — label = env var name, value = the secret
5. Save

### Fields to add

| Field label | What it is | How to get the value |
|---|---|---|
| `APP_ENVIRONMENT` | Safety check — must match vault | `development` for syn137-dev, `production` for syn137-prod |
| `ANTHROPIC_API_KEY` | Anthropic API key | https://console.anthropic.com/settings/keys |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token (alternative) | Claude Code settings |
| `SYN_GITHUB_APP_ID` | GitHub App numeric ID | GitHub → Settings → Developer Settings → Your App → App ID |
| `SYN_GITHUB_APP_NAME` | GitHub App slug | Same page, the URL slug (e.g. `syn-engineer-beta`) |
| `SYN_GITHUB_PRIVATE_KEY` | GitHub App signing key (**base64-encoded**) | `cat your-app.pem \| base64 \| tr -d '\n'` |
| `SYN_GITHUB_WEBHOOK_SECRET` | GitHub webhook HMAC secret | `openssl rand -hex 32` (must match GitHub App settings) |

> **`APP_ENVIRONMENT` is a boot-time safety check.** The resolver compares this
> field against the vault name. If they disagree (e.g. vault is `syn137-prod`
> but field says `development`), the process refuses to start.

Only add the fields you need — skip anything unused for that environment.
You only need **one** of `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`.

### `.env` setup

Your `.env` only needs to know which vault to use. Everything else comes from
the 1Password item.

```bash
# infra/.env

OP_VAULT=syn137-dev
INCLUDE_OP_CLI=1          # include op CLI in dashboard image

# Non-secret values still go here
APP_ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## Storing the Service Account Token

Create a 1Password service account at
https://my.1password.com → **Developer** → **Service Accounts**, grant it
read access to your vault, and copy the token (`ops_eyJ...`).

### macOS — Keychain (recommended)

```bash
# One command — prompts for token with hidden input (nothing in shell history)
just secrets-store-token
```

Under the hood this stores `SYN_OP_SERVICE_ACCOUNT_TOKEN_<VAULT_UPPER>` in
Keychain (e.g. `SYN_OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV` for `OP_VAULT=syn137-dev`).

The selfhost recipes auto-retrieve it at startup:
1. Read `OP_VAULT` from `infra/.env`
2. Derive the Keychain service name
3. Retrieve via `security find-generic-password`
4. Export as `OP_SERVICE_ACCOUNT_TOKEN` for Docker Compose

To remove:
```bash
just secrets-delete-token
```

### Linux/CI — vault-specific env var

```bash
# Naming convention: OP_SERVICE_ACCOUNT_TOKEN_<VAULT_UPPER>
export OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV="ops_eyJ..."
```

The selfhost recipes detect this automatically.

For GitHub Actions, add as a repository secret named
`OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD`.

### Fallback — generic env var

```bash
export OP_SERVICE_ACCOUNT_TOKEN="ops_eyJ..."
```

Works but collides if you have multiple apps or environments on the same machine.

### Interactive (personal dev)

```bash
op signin   # sets OP_SESSION for the current shell
```

---

## Switching environments

```bash
# One-off from shell
OP_VAULT=syn137-prod uv run python -m dashboard

# Persistent: change OP_VAULT in infra/.env
```

With direnv, create a per-machine `.envrc` (gitignored):

```bash
# .envrc
export OP_VAULT=syn137-dev
```

```bash
direnv allow
```

---

## Verifying

### Check the 1Password item is readable

```bash
op item get syntropic137-config --vault syn137-dev --format json
```

### Check the integration end-to-end

```bash
uv run python -c "
from syn_shared.settings import get_settings
s = get_settings()
print(s.claude_code_oauth_token or s.anthropic_api_key)
"
```

Should print the resolved value, not blank or an error.

---

## How resolution works

1. Resolver reads `OP_VAULT` from `.env` / shell
2. Fetches the entire `syntropic137-config` item in one `op item get` call
3. Injects each field label→value into `os.environ`
4. Existing env vars are never overwritten — shell always wins
5. pydantic reads from `os.environ` as normal

Precedence: **shell env > 1Password item fields > Docker secrets > .env plaintext**

---

## Without 1Password

If `op` is not installed, `OP_VAULT` is not set, or no token/session is
present, the resolver skips silently. Use Docker secret files + `infra/.env`
plaintext values — everything works the same way.
