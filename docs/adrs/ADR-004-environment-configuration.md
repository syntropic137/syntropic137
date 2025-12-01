# ADR-004: Environment Configuration with Pydantic Settings

## Status

Accepted

## Context

The Agentic Engineering Framework needs a robust configuration system that:

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

All configuration lives in a single `Settings` class in `aef_shared.settings`:

```python
from aef_shared import get_settings

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
packages/aef-shared/src/aef_shared/
├── settings/
│   ├── __init__.py      # Public exports
│   └── config.py        # Settings class and get_settings()
└── __init__.py          # Re-exports get_settings
```

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
