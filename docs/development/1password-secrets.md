# Secret Management

This guide covers how to configure secrets for Syntropic137. Most users will
use **Path A** (Docker secret files + `.env`) — it's the simplest and requires
no external tools. **Path B** (1Password) is an optional add-on for teams that
want centralized, portable secret management.

If the `op` CLI is not installed or not authenticated, 1Password resolution is
silently skipped and the system behaves exactly as it does with plaintext `.env`.

---

## Quick Start (Path A — No 1Password)

This is the default path. Run `just onboard` and follow the prompts — the wizard
handles secret generation, GitHub App creation, and `.env` configuration
automatically.

```bash
just onboard
```

The wizard will:
1. Generate DB and Redis passwords → `infra/docker/secrets/`
2. Walk you through GitHub App creation (opens browser)
3. Write all values to `infra/.env`
4. Build and start the stack

That's it. Skip to [Verifying](#verifying) to confirm everything works.

If you want to understand what's happening under the hood or configure secrets
manually, read on.

---

## How Secrets Reach the Application

There are **two independent paths** — you only need one:

| Path | How secrets get in | Good for |
|------|-------------------|----------|
| **A: Docker secret files** | Raw files in `infra/docker/secrets/` → mounted at `/run/secrets/` → entrypoint reads and exports as env vars | Most users, simple selfhost |
| **B: 1Password** | `op_resolver.py` fetches from vault → injects into `os.environ` at startup | Teams, multi-machine, CI/CD |

Both paths end at the same place: env vars that pydantic reads. If both are
configured, 1Password takes precedence (existing env vars are never overwritten).

### What the selfhost stack needs

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

> **Requires 1Password Business or Teams.** Service accounts — needed for
> non-interactive secret resolution — are not available on Individual or Family
> plans. If you're on a personal plan, use [Path A](#path-a-docker-secret-files-no-1password).

### Starting fresh

If you're setting up for the first time, you won't have GitHub App credentials
yet — the setup wizard creates them. Here's the bootstrap order:

#### 1. Create the vault

In 1Password, create a vault for your environment:

| Environment | Vault name |
|---|---|
| Local dev / self-host | `syn137-dev` |
| Beta / staging | `syn137-beta` |
| Production | `syn137-prod` |

#### 2. Create the item with empty fields

Create a new item in the vault with all the field labels pre-created. You'll
fill in the values as you go through setup — some you'll have now (like
`APP_ENVIRONMENT` and `ANTHROPIC_API_KEY`), others come later after the
setup wizard creates the GitHub App.

**Via the GUI (recommended, especially with multiple 1Password accounts):**

1. Open 1Password → switch to your business/teams account
2. Select the vault (e.g., `syn137-dev`)
3. **+** → choose **API Credential**
4. Title: `syntropic137-config`
5. Add each field from the table below — set the label to the env var name,
   leave the value empty for fields you don't have yet
6. Save

**Via the CLI (single-account setups):**

```bash
op signin

op item create \
  --category "API Credential" \
  --title "syntropic137-config" \
  --vault "syn137-dev" \
  'APP_ENVIRONMENT=development' \
  'ANTHROPIC_API_KEY=' \
  'CLAUDE_CODE_OAUTH_TOKEN=' \
  'SYN_GITHUB_APP_ID=' \
  'SYN_GITHUB_APP_NAME=' \
  'SYN_GITHUB_PRIVATE_KEY=' \
  'SYN_GITHUB_WEBHOOK_SECRET=' \
  'CLOUDFLARE_TUNNEL_TOKEN='
```

> **Multiple 1Password accounts?** If you have both personal and business
> accounts, add `--account my-business.1password.com` to the command. The GUI
> is usually easier in this case — just switch accounts in the sidebar.

This uses your personal 1Password session (interactive login), not the service
account. The service account only needs **read** access.

#### 3. Create a service account

1. Go to https://my.1password.com → **Developer** → **Service Accounts**
2. Create a new service account
3. Grant it **read-only** access to your vault (e.g., `syn137-dev`)
4. Copy the token (`ops_eyJ...`)

#### 4. Store the service account token

```bash
just secrets-store-token
```

This stores the token in macOS Keychain (see [Storing the Service Account Token](#storing-the-service-account-token) for Linux/CI options).

#### 5. Run the setup wizard

```bash
just onboard
```

The wizard creates the GitHub App and writes credentials to `infra/.env`.

#### 6. Copy GitHub credentials back to 1Password

After the wizard completes, the GitHub App credentials exist in `infra/.env`
but not yet in 1Password. Update the item with the values the wizard generated:

```bash
# Read the values from infra/.env (printed by the wizard)
# Then update the 1Password item:
op signin

op item edit "syntropic137-config" \
  --vault "syn137-dev" \
  'SYN_GITHUB_APP_ID=123456' \
  'SYN_GITHUB_APP_NAME=your-app-name' \
  'SYN_GITHUB_PRIVATE_KEY=<base64-encoded-pem>' \
  'SYN_GITHUB_WEBHOOK_SECRET=<webhook-secret>'
```

Now 1Password is the source of truth. On subsequent startups, the resolver
fetches all values from the vault automatically.

### Structure

One vault per environment, one item per vault named **`syntropic137-config`**.
Each secret is a field on that item, labeled after its env var.

### Fields reference

| Field label | What it is | How to get the value |
|---|---|---|
| `APP_ENVIRONMENT` | Safety check — must match vault | `development` for syn137-dev, `production` for syn137-prod |
| `ANTHROPIC_API_KEY` | Anthropic API key | https://console.anthropic.com/settings/keys |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token (alternative) | Claude Code settings |
| `SYN_GITHUB_APP_ID` | GitHub App numeric ID | GitHub → Settings → Developer Settings → Your App → App ID |
| `SYN_GITHUB_APP_NAME` | GitHub App slug | Same page, the URL slug (e.g. `syn-engineer-beta`) |
| `SYN_GITHUB_PRIVATE_KEY` | GitHub App signing key (**base64-encoded**) | `cat your-app.pem \| base64 \| tr -d '\n'` |
| `SYN_GITHUB_WEBHOOK_SECRET` | GitHub webhook HMAC secret | `openssl rand -hex 32` (must match GitHub App settings) |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token | Zero Trust → Networks → Connectors → your tunnel → Install |

> **`APP_ENVIRONMENT` is a boot-time safety check.** The resolver compares this
> field against the vault name. If they disagree (e.g. vault is `syn137-prod`
> but field says `development`), the process refuses to start.

Only add the fields you need — skip anything unused for that environment.
You only need **one** of `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`.

### `.env` setup

The vault name is derived automatically from `APP_ENVIRONMENT` — no separate
`OP_VAULT` variable is needed.

```bash
# infra/.env

APP_ENVIRONMENT=development   # → vault syn137-dev
INCLUDE_OP_CLI=1              # include op CLI in dashboard image

# Non-secret values still go here
LOG_LEVEL=INFO
```

---

## Storing the Service Account Token

The service account token authenticates the `op` CLI for non-interactive use.
There are several ways to provide it, and they can coexist safely.

### Token precedence

The resolver looks for the token in this order (highest priority first):

| Priority | Source | Example | Used by |
|----------|--------|---------|---------|
| 1 | **Vault-specific env var** (shell or `.env`) | `OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV=ops_eyJ...` | `just dev`, `just onboard`, runtime |
| 2 | **macOS Keychain** | Stored via `just secrets-store-token` | `just onboard`, `just selfhost-*` |
| 3 | **Generic env var** (shell or `.env`) | `OP_SERVICE_ACCOUNT_TOKEN=ops_eyJ...` | All (fallback) |

The vault-specific env var **always wins**, even if the generic
`OP_SERVICE_ACCOUNT_TOKEN` is already set. This prevents a stale generic
token from another app from shadowing the correct vault-specific one.

### For local dev — vault-specific env var in `.env` (recommended)

The simplest option for day-to-day development. Add to your root `.env`:

```bash
OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV=ops_eyJ...
```

This is picked up by `just dev`, `just onboard`, and the runtime resolver
without any Keychain prompts or extra steps.

### macOS — Keychain

```bash
# One command — prompts for token with hidden input (nothing in shell history)
just secrets-store-token
```

Under the hood this stores `SYN_OP_SERVICE_ACCOUNT_TOKEN_<VAULT_UPPER>` in
Keychain (e.g. `SYN_OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV` for `APP_ENVIRONMENT=development`).

The selfhost recipes auto-retrieve it at startup:
1. Read `APP_ENVIRONMENT` from `infra/.env`
2. Derive vault name (e.g. `development` → `syn137-dev`)
3. Derive the Keychain service name
4. Retrieve via `security find-generic-password`
5. Export as `OP_SERVICE_ACCOUNT_TOKEN` for Docker Compose

To remove:
```bash
just secrets-delete-token
```

> **Both `.env` and Keychain?** No conflict. The vault-specific env var in
> `.env` takes precedence. The Keychain acts as a backup for contexts that
> don't source `.env` (like selfhost recipes).

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
Prefer the vault-specific naming convention instead.

### Interactive (personal dev)

```bash
op signin   # sets OP_SESSION for the current shell
```

---

## Switching environments

```bash
# One-off from shell
APP_ENVIRONMENT=production uv run python -m dashboard

# Persistent: change APP_ENVIRONMENT in infra/.env
```

With direnv, create a per-machine `.envrc` (gitignored):

```bash
# .envrc
export APP_ENVIRONMENT=development
```

```bash
direnv allow
```

---

## Verifying

### Check secret files are in place (Path A)

```bash
just secrets-check
```

### Check the 1Password item is readable (Path B)

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

1. Resolver reads `APP_ENVIRONMENT` from `.env` / shell
2. Derives the vault name (e.g. `development` → `syn137-dev`)
3. Fetches the entire `syntropic137-config` item in one `op item get` call
4. Injects each field label→value into `os.environ`
5. Existing env vars are never overwritten — shell always wins
6. pydantic reads from `os.environ` as normal

Precedence: **shell env > 1Password item fields > Docker secrets > .env plaintext**

---

## Without 1Password

If `op` is not installed, `APP_ENVIRONMENT` is `test`/`offline`/unset, or no
token/session is present, the resolver skips silently. Use Docker secret files
+ `infra/.env` plaintext values — everything works the same way.
