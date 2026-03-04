# ADR-045: Secrets Management Standard

## Status

Accepted

## Context

Syn137 is open-source software that also runs in production under the `syntropic137` org. As the number of integrations grows (GitHub App, Anthropic, OpenAI, Supabase, MinIO, TimescaleDB), secret sprawl becomes a real risk:

- App ID and private key stored in separate, unlinked secrets → they drift out of sync (e.g. wrong App ID used with a valid key)
- No canonical list of what secrets exist → contributors don't know what to configure
- No naming convention → different environments use different variable names for the same value

The system already has a working 1Password resolver (`op_resolver.py`) that transparently injects `op://` references into the environment at startup. The question is how to standardize around it.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Process Startup                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │  resolve_op_      │   reads OP_VAULT from
                    │  secrets()        │◄── shell env / .env
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │ op CLI available             │ op CLI absent /
              │ + OP_VAULT set?              │ OP_VAULT not set
              ▼ YES                          ▼ NO
   ┌──────────────────────┐      ┌────────────────────────┐
   │  op item get         │      │  Skip — use plaintext  │
   │  syntropic137-config │      │  values from .env      │
   │  --vault <OP_VAULT>  │      └────────────────────────┘
   └──────────┬───────────┘
              │ injects all fields → os.environ
              │ (shell env always wins, never overwritten)
              ▼
   ┌──────────────────────┐
   │  Environment Guard   │  compares APP_ENVIRONMENT
   │  _validate_          │  vs vault-expected value
   │  environment_match() │
   └──────────┬───────────┘
              │
   ┌──────────┴──────────────────────┐
   │ MATCH (or test/offline/unknown) │  MISMATCH
   ▼                                 ▼
 Continue                    EnvironmentError
                             "refusing to start"
              │
              ▼
   ┌──────────────────────┐
   │  pydantic Settings() │  reads from os.environ as normal
   │  + GitHubAppSettings │  SYN_* prefix, all fields validated
   └──────────────────────┘


Precedence (highest → lowest):
  1. Shell environment variables
  2. 1Password item fields (injected by resolver)
  3. Plaintext values in .env


1Password item structure (one item per vault):

  vault: syn137-dev          vault: syn137-beta         vault: syn137-staging      vault: syn137-prod
  item: syntropic137-config  item: syntropic137-config  item: syntropic137-config  item: syntropic137-config
  ┌────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐
  │ APP_ENVIRONMENT        │   │ APP_ENVIRONMENT        │   │ APP_ENVIRONMENT        │   │ APP_ENVIRONMENT        │
  │   = development        │   │   = beta               │   │   = staging            │   │   = production         │
  │ SYN_GITHUB_APP_ID      │   │ SYN_GITHUB_APP_ID      │   │ SYN_GITHUB_APP_ID      │   │ SYN_GITHUB_APP_ID      │
  │ SYN_GITHUB_APP_NAME    │   │ SYN_GITHUB_APP_NAME    │   │ SYN_GITHUB_APP_NAME    │   │ SYN_GITHUB_APP_NAME    │
  │ SYN_GITHUB_PRIVATE_KEY │   │ SYN_GITHUB_PRIVATE_KEY │   │ SYN_GITHUB_PRIVATE_KEY │   │ SYN_GITHUB_PRIVATE_KEY │
  │ ANTHROPIC_API_KEY      │   │ ANTHROPIC_API_KEY      │   │ ANTHROPIC_API_KEY      │   │ ANTHROPIC_API_KEY      │
  │ ...                    │   │ ...                    │   │ ...                    │   │ ...                    │
  └────────────────────────┘   └────────────────────────┘   └────────────────────────┘   └────────────────────────┘
```

## Decision

### 1. `SYN_` Prefix for All Product Secrets

All Syn137-managed secrets use the `SYN_` prefix.

**Rationale:** The prefix is the product namespace, not an org name — consistent with the package names (`syn-adapters`, `syn-shared`). It prevents collisions when Syn137 runs alongside other tools that use the same underlying services (e.g. a separate GitHub App in the same shell environment). Contributors don't need to know about Syntropic137 to understand the convention.

Generic names like `GITHUB_APP_ID` are not used because they are ambiguous and prone to collision.

### 2. Co-locate Related Credentials in a Single 1Password Item

Credentials that must be used together are stored in a **single named 1Password item**, not as separate secrets. The canonical example is GitHub App identity:

| Field label | Maps to env var |
|---|---|
| `SYN_GITHUB_APP_ID` | `SYN_GITHUB_APP_ID` |
| `SYN_GITHUB_APP_NAME` | `SYN_GITHUB_APP_NAME` |
| `SYN_GITHUB_PRIVATE_KEY` | `SYN_GITHUB_PRIVATE_KEY` |
| `SYN_GITHUB_WEBHOOK_SECRET` | `SYN_GITHUB_WEBHOOK_SECRET` |

Storing them together means they are always updated atomically. An App ID from one item can never be paired with a private key from another.

### 3. One Vault Per Environment, One Config Item Per Vault

```
vault: syn137-dev     → item: syntropic137-config
vault: syn137-beta    → item: syntropic137-config
vault: syn137-staging → item: syntropic137-config
vault: syn137-prod    → item: syntropic137-config
```

Switching environments requires changing a single value (`OP_VAULT`). All secrets for that environment are fetched in one `op item get` call at startup.

### 4. The Resolver Is Prefix-Agnostic

`op_resolver.py` injects **every field** from the `syntropic137-config` item into `os.environ`, regardless of its name. The field label must exactly match the env var the application expects.

This means ecosystem-standard names that don't carry the `SYN_` prefix work without any aliasing:

| Field label in 1Password item | Why it stays unprefixed |
|---|---|
| `ANTHROPIC_API_KEY` | Standard name read by Anthropic SDK |
| `OPENAI_API_KEY` | Standard name read by OpenAI SDK |
| `CLAUDE_CODE_OAUTH_TOKEN` | Generated and named by Claude Code tooling |

These are intentional exceptions to the `SYN_` prefix rule. Prefixing them would require aliasing inside every agent container that invokes the SDKs directly.

All other Syn137-managed secrets use the `SYN_` prefix as described in Decision 1.

### 5. Graceful Fallback — No 1Password Required


The resolver silently skips if:
- `op` CLI is not installed
- `OP_VAULT` is not set
- No 1Password session or service account token is present

In this case pydantic reads directly from `.env` plaintext values, exactly as before. Open-source contributors without a 1Password Business account set secrets as plain values in `.env`. The application code is identical in both cases.

### 6. `.env.example` as Canonical Field Reference

`.env.example` (committed to the repo) is the primary configuration guide. It:
- Opens with a quickstart (3 steps) and full Option A / Option B setup instructions
- Lists every configurable env var with a description
- 1Password users set only `OP_VAULT` and leave secret fields blank — all values are injected automatically
- Plain-env users fill in values directly

This makes `.env.example` the single source of truth for both audiences and removes the need to consult code to discover what secrets are needed.

### 7. Environment Field as a Boot-Time Sanity Check

Each 1Password item includes an `APP_ENVIRONMENT` field whose value matches the vault:

| Vault | `APP_ENVIRONMENT` value |
|---|---|
| `syn137-dev` | `development` |
| `syn137-beta` | `beta` |
| `syn137-staging` | `staging` |
| `syn137-prod` | `production` |

At startup, after injecting secrets, `_validate_environment_match()` in `op_resolver.py` derives the expected environment directly from the vault name:

```python
_VAULT_EXPECTED_ENV = {
    "syn137-dev":     "development",
    "syn137-beta":    "beta",
    "syn137-staging": "staging",
    "syn137-prod":    "production",
}
```

It then reads `APP_ENVIRONMENT` from `os.environ` (which may have come from the shell, the injected item, or `.env`) and raises `EnvironmentError` if they disagree. The process refuses to start.

The check is bypassed when `APP_ENVIRONMENT` is `test` or `offline`, when the vault name is not in the known map (custom deployments), or when `APP_ENVIRONMENT` is not set at all.

Plain-env users set `APP_ENVIRONMENT` directly in `.env`. The check still applies when `OP_VAULT` is also set.

### 8. Per-Vault Service Account Tokens

Each vault has its own 1Password service account with access scoped to that vault only. The corresponding token is stored in `.env` under a vault-derived key:

| Vault | Token env var |
|---|---|
| `syn137-dev` | `OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV` |
| `syn137-beta` | `OP_SERVICE_ACCOUNT_TOKEN_SYN137_BETA` |
| `syn137-staging` | `OP_SERVICE_ACCOUNT_TOKEN_SYN137_STAGING` |
| `syn137-prod` | `OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD` |

At startup, `resolve_op_secrets()` reads `OP_VAULT`, derives the vault-specific key (`OP_SERVICE_ACCOUNT_TOKEN_` + vault uppercased with hyphens replaced by underscores), and injects it as `OP_SERVICE_ACCOUNT_TOKEN` before calling `_op_available()`. The shell environment always wins: if `OP_SERVICE_ACCOUNT_TOKEN` is already set in the shell, the vault-specific value is ignored.

This means a compromised dev token cannot access beta, staging, or production vaults. Each service account is granted read-only access to exactly one vault in the 1Password console.

Plain-env users (no 1Password) leave all four token vars blank — the resolver silently skips.

### 9. Shell Environment Always Wins

Precedence order (highest to lowest):
1. Shell environment variables
2. 1Password item fields (via `op_resolver.py`)
3. Plaintext values in `.env`

This allows CI and production deployments to inject secrets via environment without any 1Password dependency.

## Consequences

### Positive

- App ID and private key can never drift out of sync — they live in one item
- Contributors have a single file (`.env.example`) to understand what to configure
- The `SYN_` prefix prevents collisions with other tools in the same environment
- No 1Password required — open-source contributors use plain `.env` without friction
- Switching environments is a one-line change (`OP_VAULT=syn137-prod`)

### Negative

- The `SYN_` prefix means forking the project requires renaming env vars (acceptable — forks are a divergence point anyway)
- All secrets must be re-added to the 1Password item when a new integration is added (low friction given the single-item-per-env model)

### Neutral

- Existing deployments using plaintext `.env` require no migration
- The resolver (`op_resolver.py`) is already implemented; this ADR formalises the conventions around it

## References

- [docs/development/1password-secrets.md](../development/1password-secrets.md) — operational setup guide
- [ADR-024: Setup Phase Secrets](ADR-024-setup-phase-secrets.md) — GitHub App token lifecycle
- [packages/syn-shared/src/syn_shared/settings/op_resolver.py](../../packages/syn-shared/src/syn_shared/settings/op_resolver.py) — resolver implementation
