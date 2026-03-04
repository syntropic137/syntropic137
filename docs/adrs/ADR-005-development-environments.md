# ADR-005: Development Environment Strategy

## Status

Accepted

## Context

The Syntropic137 requires different storage and infrastructure configurations depending on the context:

1. **Unit Tests** - Need to run fast, be isolated, and have no external dependencies
2. **Local Development** - Need to mirror production as closely as possible for realistic testing
3. **CI/CD** - Need reproducible builds without complex infrastructure
4. **Production** - Need real, scalable infrastructure

A common anti-pattern is using in-memory or SQLite for "development" which leads to:
- Bugs that only appear in production (different SQL dialects, concurrency issues)
- False confidence from passing tests that don't reflect reality
- "Works on my machine" problems

## Decision

### Three-Tier Environment Strategy

| Environment | Storage | Event Store | Purpose |
|-------------|---------|-------------|---------|
| **Test** (`APP_ENVIRONMENT=test`) | In-memory | In-memory | Unit tests, fast feedback |
| **Development** (`APP_ENVIRONMENT=development`) | Docker PostgreSQL | Docker Event Store | Local dev mirrors production |
| **Production** (`APP_ENVIRONMENT=production`) | Cloud PostgreSQL | Cloud Event Store | Real infrastructure |

### 1. Test Environment (In-Memory)

**When:** Unit tests, integration tests mocking external services

**Storage:** `InMemoryEventStore`, `InMemoryWorkflowRepository`

**Characteristics:**
- ⚡ Fast (no I/O)
- 🔒 Isolated (each test gets fresh state)
- 🚫 No external dependencies
- ⚠️ NOT thread-safe
- ⚠️ Data lost on process exit

**Usage:**
```python
# In tests
from syn_adapters.storage import reset_storage

@pytest.fixture(autouse=True)
def clean_storage():
    reset_storage()  # Fresh state each test
```

**Code Location:** `packages/syn-adapters/src/syn_adapters/storage/in_memory.py`

### 2. Development Environment (Docker)

**When:** Local development, manual testing, debugging

**Storage:** PostgreSQL in Docker, Event Store in Docker

**Characteristics:**
- 🎯 Mirrors production behavior
- 🐘 Real PostgreSQL (same SQL dialect, constraints, transactions)
- 📦 Containerized (reproducible, easy setup)
- 💾 Data persists across restarts (via volumes)
- 🔄 Easy reset (`just dev-reset`)

**Usage:**
```bash
# Start local dev stack
just dev

# Run application against local stack
just run

# Reset database (fresh start)
just dev-reset

# Stop stack
just dev-down
```

**Code Location:** `docker/docker-compose.dev.yaml`

### 3. Production Environment

**When:** Deployed application serving real users

**Storage:** Cloud-managed PostgreSQL (e.g., Supabase, AWS RDS), Cloud Event Store

**Characteristics:**
- 🔐 Secure (credentials via secrets management)
- 📈 Scalable (managed services)
- 💰 Real costs
- 🔒 No direct access (via application only)

**Configuration:** Environment variables, secrets management

## Implementation

### Settings Integration

The `Settings` class enforces this strategy:

```python
@property
def use_in_memory_storage(self) -> bool:
    """In-memory storage ONLY allowed in test environment."""
    return self.database_url is None and self.is_test
```

This means:
- `APP_ENVIRONMENT=test` + no `DATABASE_URL` → In-memory ✅
- `APP_ENVIRONMENT=development` + no `DATABASE_URL` → Error (must use Docker) ❌
- `APP_ENVIRONMENT=production` + no `DATABASE_URL` → Error (must configure DB) ❌

### Docker Compose Structure

```yaml
# docker/docker-compose.dev.yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: syn
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d

  event-store:
    image: ghcr.io/neuralempowerment/event-store:latest
    ports:
      - "50051:50051"
    depends_on:
      - postgres

volumes:
  postgres_data:
```

### Justfile Commands

```makefile
# Start development stack
dev:
    docker compose -f docker/docker-compose.dev.yaml up -d

# Stop development stack
dev-down:
    docker compose -f docker/docker-compose.dev.yaml down

# Reset development database
dev-reset:
    docker compose -f docker/docker-compose.dev.yaml down -v
    docker compose -f docker/docker-compose.dev.yaml up -d

# Run tests (uses in-memory)
test:
    APP_ENVIRONMENT=test uv run pytest
```

### Environment Files

```bash
# .env.development (local dev)
APP_ENVIRONMENT=development
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/syn
EVENT_STORE_URL=grpc://localhost:50051
LOG_LEVEL=DEBUG
LOG_FORMAT=console

# .env.test (CI/CD and local tests)
APP_ENVIRONMENT=test
# No DATABASE_URL = in-memory
LOG_LEVEL=WARNING
```

## Consequences

### Positive

- **Production parity** - Local dev matches production behavior
- **Fast tests** - Unit tests don't wait for database
- **Reproducible** - Docker ensures consistent environment
- **Clear separation** - Each environment has explicit purpose
- **Fail-fast** - Missing database in dev/prod causes immediate error

### Negative

- **Docker required** - Developers must have Docker installed
- **Resource usage** - Docker containers use memory/CPU
- **Initial setup** - First `just dev` takes time to pull images

### Mitigations

- Provide `just dev` for one-command setup
- Document Docker installation in README
- Keep Docker images small and fast to start
- Offer `just dev-down` to free resources when not developing

## File Structure

```
syntropic137/
├── docker/
│   ├── docker-compose.dev.yaml    # Local development stack
│   ├── docker-compose.ci.yaml     # CI/CD stack (if needed)
│   └── init/
│       └── 01-init.sql            # Database initialization
├── packages/syn-adapters/
│   └── src/syn_adapters/storage/
│       ├── in_memory.py           # Test-only storage
│       └── postgres.py            # PostgreSQL storage (future)
└── .env.example                   # Template for developers
```

## References

- [12-Factor App: Dev/Prod Parity](https://12factor.net/dev-prod-parity)
- [The Pragmatic Programmer: Programming by Coincidence](https://pragprog.com/titles/tpp20/)
- ADR-004: Environment Configuration with Pydantic Settings
