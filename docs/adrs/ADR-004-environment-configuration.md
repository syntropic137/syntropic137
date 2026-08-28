# ADR-004: Environment Configuration with Pydantic Settings

## Status

Accepted

## Context

The Syntropic137 needs a robust configuration system that:

1. **Validates on startup** - Fails immediately with clear errors if required values are missing
2. **Documents itself** - Each setting has a description explaining purpose and where to get it
3. **Protects secrets** - API keys and passwords don't leak in logs or error messages
4. **Supports multiple environments** - Development, staging, production, test
5. **Integrates with existing tooling** - Works with `.env` files, CI/CD, Docker

We evaluated several approaches:
- Raw `os.environ` - No validation, no type safety, easy to miss required vars
- `python-dotenv` alone - Loads `.env` but no validation
- `dynaconf` - Feature-rich but complex, different patterns than our Pydantic-based codebase
- `pydantic-settings` - Extends Pydantic BaseModel with env loading, native to our stack

## Decision

Use **Pydantic Settings** (`pydantic-settings`) for all environment configuration.

### Key Design Choices

#### 1. Centralized Settings Class

All configuration lives in a single `Settings` class in `syn_shared.settings`:

```python
from syn_shared import get_settings

settings = get_settings()
```

#### 2. Fail-Fast Validation

Settings are validated immediately on first access. Missing required values cause clear errors:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
anthropic_api_key
  Field required [type=missing]
```

#### 3. Self-Documenting Fields

Each setting includes a description explaining:
- What it's for
- Where to get it (for API keys)
- Default behavior

```python
anthropic_api_key: SecretStr | None = Field(
    default=None,
    description=(
        "Anthropic API key for Claude models. "
        "Get from: https://console.anthropic.com/settings/keys "
        "Required when using Claude agent adapter."
    ),
)
```

#### 4. Secret Protection

Sensitive values use `SecretStr` which:
- Won't appear in `repr()` or `str()`
- Won't leak in logs or error messages
- Requires explicit `.get_secret_value()` to access

```python
# Safe - won't expose secret
logger.info("Settings loaded", settings=settings)

# Explicit access required
api_key = settings.anthropic_api_key.get_secret_value()
```

#### 5. Computed Properties

Convenience properties for common checks:

```python
settings.is_development  # True if APP_ENVIRONMENT=development
settings.is_production   # True if APP_ENVIRONMENT=production
settings.use_in_memory_storage  # True if no DATABASE_URL set
```

#### 6. Cached with Reset

Settings are cached via `@lru_cache` for performance, with `reset_settings()` for testing:

```python
@pytest.fixture(autouse=True)
def reset_settings_cache():
    reset_settings()
    yield
    reset_settings()
```

#### 7. Mock Objects: Test Environment Only

All mock objects in the codebase (`MockAgent`, `MockProjectionManager`, `InMemoryEventStore`, etc.) **must validate** they are running in the test environment:

```python
def _assert_test_environment() -> None:
    """Assert test environment - REQUIRED for all mocks."""
    app_env = os.getenv("APP_ENVIRONMENT", "").lower()
    if app_env != "test":
        raise MockTestEnvironmentError(
            f"Mock objects can only be used in test environment. "
            f"Current APP_ENVIRONMENT: '{app_env}'"
        )
```

**This is critical** - mocks should NEVER run in development, staging, or production. The environment check:

1. Prevents accidental mock usage in production
2. Forces real implementations for E2E testing
3. Fails fast with clear error messages

See `docs/testing/E2E-ACCEPTANCE-TESTS.md` for the full mocking policy.

### Configuration Categories

| Category | Examples | Required |
|----------|----------|----------|
| Application | `APP_ENVIRONMENT`, `DEBUG` | No (defaults) |
| Database | `DATABASE_URL`, `DATABASE_POOL_SIZE` | Production only |
| Event Store | `EVENT_STORE_URL` | Production only |
| Logging | `LOG_LEVEL`, `LOG_FORMAT` | No (defaults) |
| Agents | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | When using agents |
| Storage | `S3_*` variables | When using S3 |

### File Structure

```
packages/syn-shared/src/syn_shared/
├── settings/
│   ├── __init__.py      # Public exports
│   ├── config.py        # Settings class and get_settings()
│   ├── constants.py     # Port, URL, and env var name constants (single source)
│   ├── dev_tooling.py   # DevToolingSettings (DEV__ prefix) + get_dev_api_url()
│   └── infra.py         # InfraSettings (SYN_ prefix for selfhost)
└── __init__.py          # Re-exports get_settings
```

### 8. Two Env File Scopes

The project uses two `.env` files for different audiences:

| File | Scope | Loaded by |
|------|-------|-----------|
| `.env` (root) | Application config - ports, API keys, feature flags | `set dotenv-load` in justfile (native) |
| `infra/.env` | Infrastructure config - domain, tunnel tokens, Cloudflare | `scripts/resolve_infra_env.py` (eval'd by recipes) |

Both files have auto-generated `.env.example` templates. Root `.env.example` is generated
from Pydantic Settings classes via `just gen-env`.

### 9. Zero Magic Strings Rule

All ports, URLs, and environment variable name strings are defined exactly once in a
named constant. Everything else imports the constant. No exceptions.

**Python constants:** `packages/syn-shared/src/syn_shared/settings/constants.py`
- `DEV_API_HOST_PORT`, `SELFHOST_GATEWAY_PORT` - port numbers
- `DEFAULT_DEV_API_URL`, `DEFAULT_SELFHOST_API_URL` - derived URLs
- `ENV_DEV_API_URL`, `ENV_SYN_API_URL`, `ENV_SYN_PUBLIC_HOSTNAME` - env var names

**TypeScript constants:** `apps/syn-cli-node/src/constants.ts`
- `SELFHOST_GATEWAY_PORT`, `DEFAULT_SELFHOST_API_URL`, `ENV_SYN_API_URL`

**Infra constants:** `infra/scripts/infra_config.py`
- Internal service ports, compose file paths, env var name constants

### 10. Dev vs Selfhost Separation

Two stacks run independently and serve different audiences:

| | Dev Stack | Selfhost Stack |
|--|-----------|----------------|
| **Audience** | Contributors, dev tools | End users, CLI |
| **API port** | 9137 (direct) | 8137 (nginx gateway) |
| **Env var** | `DEV__API_URL` | `SYN_API_URL` |
| **Settings class** | `DevToolingSettings` | `InfraSettings` |
| **Gateway** | None | nginx with basic auth |

Dev tools (seed scripts, replay, E2E tests) use `get_dev_api_url()` from
`syn_shared.settings.dev_tooling`. The CLI (`syn`) uses `SYN_API_URL` defaulting
to `http://localhost:8137` for selfhost users.

### 11. Env Loading Pipeline

Settings classes are the single source of truth for env var definitions:

```
Settings classes (Pydantic BaseSettings)
  -> scripts/generate_env_example.py
    -> .env.example (auto-generated, never edit manually)
      -> .env (user copies and fills in values)
```

Run `just gen-env` to regenerate `.env.example` after any Settings change.

### 12. Naming Conventions

- **`SYN_PUBLIC_HOSTNAME`** replaces the deprecated `SYN_DOMAIN` (avoid DDD
  "domain" ambiguity in a domain-driven design codebase)
- Dev tooling env vars use the **`DEV__`** prefix via `DevToolingSettings`
  (double underscore matches Pydantic Settings `env_prefix`)
- Infrastructure env vars use the **`SYN_`** prefix

### 13. Workspace Capability Settings (central session store)

Some settings are not consumed by Syntropic137 at all. They are a **contract
supplied to a capability that runs inside the workspace container**, shipped by
the agentic-primitives image. Central session capture is the first of these and
sets the pattern.

Two namespaces, deliberately distinct:

| Namespace | Owner | Read by |
| --- | --- | --- |
| `SYN_SESSION_STORE_*` | this repo, a `BaseSettings` class like any other | the API, at provision time |
| `AGENTIC_SESSION_STORE_*` | agentic-primitives (ADR-040 capability contract) | the capability, inside the container |

The API translates the first into the second when it creates a workspace. It
never captures anything itself.

**Rules for a settings group of this kind:**

1. **Opt-in, and completely off by default.** Syntropic137 must stay deployable
   by an operator with no such service. When `SYN_SESSION_STORE_URL` is unset,
   **no** capability variable is written into the container - not
   `PROVIDER=none`, not an empty value. Absence and "explicitly disabled" are
   different, and only absence guarantees the container behaves exactly as it
   did before the feature existed.
2. **The foreign contract's variable names are declared once**, in
   `syn_shared.env_constants`, with a test rejecting a bare literal anywhere
   else. These names are owned by another repo; a typo is not a local bug.
3. **Credentials stay `SecretStr` and are read only at the injection point.**
   Never logged, never in an exception message, and never written to a
   container label, since labels are readable via `docker inspect`.
4. **Identifiers passed through are sanitised, not trusted.** The partition is
   a relative `<execution_id>/<workspace_id>`; the capability hard-fails an
   absolute path or `..`.

#### Resolution order, and why the vault "just works"

A field of this group needs **no code change to configure**. The API image
bakes the `op` CLI and `resolve_op_secrets()` runs before `Settings()` is
constructed, injecting **every field** on the `syntropic137-config` item keyed
by its label. So adding `SYN_SESSION_STORE_URL` as a vault field is sufficient.

Two consequences worth stating, because both have bitten:

- **An empty value in `.env` does not win over the vault.** Injection skips only
  a *truthy* existing value, so the `SYN_SESSION_STORE_URL=` that ships in
  `.env.example` still resolves from 1Password.
- **A compose overlay that enumerates variables individually breaks this.**
  `op_resolver` derives a **per-vault** token name from `APP_ENVIRONMENT`
  (`syn137-beta` -> `OP_SERVICE_ACCOUNT_TOKEN_SYN137_BETA`). An overlay passing
  only the generic `OP_SERVICE_ACCOUNT_TOKEN` leaves that stack unable to read
  its own vault, and every vault-only setting silently stays at its default.
  Prefer `env_file` over enumeration; if you must enumerate, forward the
  per-vault names too.

## Consequences

### Positive

- **Type safety** - All settings are typed, IDE autocomplete works
- **Early failure** - Invalid config caught at startup, not runtime
- **Self-documenting** - Descriptions visible in code and via `Settings.model_json_schema()`
- **Secure by default** - Secrets protected without extra effort
- **Testable** - Easy to mock with `reset_settings()` and environment patches
- **Consistent with codebase** - Uses Pydantic like our domain models

### Negative

- **Requires import** - Must import settings, not just read `os.environ`
- **Startup cost** - Validation runs on first access (negligible in practice)
- **Learning curve** - Developers must know Pydantic Settings patterns

### Neutral

- **`.env` files** - Supported but not required; env vars work directly
- **No hot reload** - Settings cached; restart required for changes (appropriate for production)

## References

- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [12-Factor App Config](https://12factor.net/config)
- [The Pragmatic Programmer - Configuration](https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/)
- `docs/env-configuration.md` - Full variable reference
