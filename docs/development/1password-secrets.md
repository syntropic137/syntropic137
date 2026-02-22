# 1Password Secret Management

Secrets are stored in a single 1Password item and resolved transparently at
startup. No code changes are needed to consume them — pydantic sees the
resolved values exactly as if they were plaintext.

If the `op` CLI is not installed or not authenticated, resolution is silently
skipped and the system behaves exactly as it does today with plaintext `.env`.

---

## Structure

One vault per environment, one item per vault named **`syntropic137-config`**.
Each secret is an individual field on that item, labeled after its env var.
One `op item get` call fetches everything at startup.

| Environment | Vault name |
|---|---|
| Local dev / homelab | `syn137-dev` |
| Beta / staging | `syn137-beta` |
| Production | `syn137-prod` |

---

## Creating the item

1. Open 1Password → select the vault (e.g. `syn137-dev`)
2. **+** → choose any type (API Credential works well)
3. Title: `syntropic137-config`
4. Add each secret as a field — label = env var name, value = the secret
5. Save

Repeat for `syn137-beta` and `syn137-prod` with environment-appropriate values.

### Fields to add

| Field label | What it is |
|---|---|
| `APP_ENVIRONMENT` | Environment name — **must match the vault** (`development` / `staging` / `production`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token (preferred over API key) |
| `ANTHROPIC_API_KEY` | Anthropic API key (fallback) |
| `OPENAI_API_KEY` | OpenAI API key |
| `SYN_GITHUB_APP_ID` | GitHub App ID |
| `SYN_GITHUB_APP_NAME` | GitHub App name slug (commits show as `<name>[bot]`) |
| `SYN_GITHUB_PRIVATE_KEY` | GitHub App signing key (base64-encoded PEM) |
| `SYN_GITHUB_WEBHOOK_SECRET` | GitHub webhook validation secret |
| `SYN_OBSERVABILITY_DB_URL` | TimescaleDB URL (dashboard/observability) |
| `ESP_EVENT_STORE_DB_URL` | TimescaleDB URL (event store) |
| `SYN_STORAGE_SUPABASE_URL` | Supabase project URL |
| `SYN_STORAGE_SUPABASE_KEY` | Supabase service role key |
| `SYN_STORAGE_MINIO_ACCESS_KEY` | MinIO access key |
| `SYN_STORAGE_MINIO_SECRET_KEY` | MinIO secret key |

> **`APP_ENVIRONMENT` is the boot-time safety check.** At startup, the resolver
> compares this field against the vault name. If they disagree (e.g. vault is
> `syn137-prod` but field says `development`), the process refuses to start.
> This prevents prod secrets running in dev and vice versa.

Only add the fields you actually need — skip anything unused for that environment.

---

## `.env` setup

Your `.env` only needs to know which vault to use. Everything else comes from
the 1Password item.

```bash
# .env

# --- Environment selector ---
# Change this one line to switch environments, or override from shell:
#   OP_VAULT=syn137-prod uv run python -m dashboard
OP_VAULT=syn137-dev

# --- Plain values (no 1Password needed) ---
APP_ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## Authentication

**Option A — Service Account (recommended for automation and CI):**

Create a service account at https://developer.1password.com/docs/service-accounts/
and grant it read access to the vaults it needs.

```bash
# ~/.zshrc or ~/.zshenv
export OP_SERVICE_ACCOUNT_TOKEN="ops_eyJ..."
```

**Option B — Interactive (personal dev machine):**

```bash
op signin   # sets OP_SESSION for the current shell
```

---

## Switching environments

```bash
# One-off from shell
OP_VAULT=syn137-prod uv run python -m dashboard

# Persistent: change OP_VAULT in .env
```

With direnv, create a per-machine `.envrc` (gitignored) to set it automatically:

```bash
# .envrc
export OP_VAULT=syn137-dev   # or syn137-beta / syn137-prod
```

```bash
direnv allow
```

---

## Verifying the item is readable

```bash
op item get syntropic137-config --vault syn137-dev --format json
```

Should print the item JSON with all your fields.

---

## Verifying the integration end-to-end

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

Precedence: **shell env > 1Password item fields > .env plaintext values**

---

## Without 1Password

If `op` is not installed, `OP_VAULT` is not set, or no token/session is
present, the resolver skips silently. Set secrets as plaintext in `.env`
exactly as before — nothing changes.
