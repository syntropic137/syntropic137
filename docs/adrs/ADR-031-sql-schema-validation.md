# ADR-031: SQL Schema Validation for Raw SQL Operations

**Status: ✅ ACCEPTED**

**Date:** 2025-12-17

**Deciders:** @neural

**Related:**
- ADR-026: TimescaleDB Observability Storage
- ADR-029: Simplified Event System

---

## Context

AEF uses raw SQL with `asyncpg` for high-performance database operations, particularly for the `AgentEventStore` which needs to handle 100K+ events/sec. While raw SQL provides maximum performance, it lacks the compile-time type safety that ORMs provide.

During E2E testing, we discovered a **schema drift** issue:
- Python code expected `TEXT` columns for `session_id` and `execution_id`
- The actual database had `UUID` columns
- This caused cryptic `asyncpg.exceptions.DataError` at runtime

This is a common problem with raw SQL: **type mismatches are only caught at runtime, often with unclear error messages**.

## Decision

We will implement **startup schema validation** for all database adapters that use raw SQL. This provides:

1. **Early failure** - Schema mismatches are caught at initialization, not during operation
2. **Clear errors** - Validation errors list exactly which columns are wrong
3. **Type safety** - Pydantic models validate data before DB insertion
4. **No ORM overhead** - Keep raw SQL performance for hot paths

### Implementation Pattern

```python
# 1. Define expected schema as constant
EXPECTED_COLUMNS = {
    "id": "uuid",
    "time": "timestamp with time zone",
    "session_id": "uuid",
    "data": "jsonb",
}

# 2. Define Pydantic model for type validation
class MyEvent(BaseModel):
    id: UUID | None = None
    time: datetime
    session_id: UUID | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("session_id", mode="before")
    @classmethod
    def parse_uuid(cls, v):
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError:
                return None
        return v

# 3. Validate schema on initialize()
async def _validate_schema(self, conn: Connection) -> None:
    rows = await conn.fetch("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'my_table'
        AND table_schema = 'public'
    """)

    actual = {r["column_name"]: r["data_type"] for r in rows}

    mismatches = []
    for col, expected in EXPECTED_COLUMNS.items():
        actual_type = actual.get(col)
        if actual_type is None:
            mismatches.append(f"Missing column: {col}")
        elif not actual_type.startswith(expected.split()[0]):
            mismatches.append(f"{col}: expected '{expected}', got '{actual_type}'")

    if mismatches:
        raise SchemaValidationError("\\n".join(mismatches))

# 4. Validate data through model before insert
async def insert_one(self, data: dict) -> None:
    validated = MyEvent.from_dict(data)  # Type-safe!
    await conn.execute(
        "INSERT INTO my_table (...) VALUES ($1, $2, ...)",
        validated.time, validated.session_id, ...
    )
```

### What This Catches

| Issue | When Caught | Error Message |
|-------|-------------|---------------|
| Missing column | Startup | `Missing column: session_id` |
| Wrong column type | Startup | `session_id: expected 'uuid', got 'text'` |
| Invalid UUID string | Insert time | `EventValidationError: invalid UUID` |
| Type coercion needed | Insert time | Pydantic handles gracefully |

### What This Doesn't Catch

- Column constraints (NOT NULL, CHECK, etc.)
- Index existence
- Foreign key relationships
- Permissions issues

For these, rely on integration tests and migration tooling.

## Alternatives Considered

### 1. Full ORM (SQLAlchemy/SQLModel)
**Pros:** Compile-time type safety, automatic schema sync
**Cons:** Performance overhead, complexity, less control over queries
**Decision:** Rejected for hot paths. Keep raw SQL for performance.

### 2. No Validation (Status Quo)
**Pros:** Simple, no overhead
**Cons:** Cryptic runtime errors, debugging nightmare
**Decision:** Rejected. The debugging cost outweighs validation overhead.

### 3. Database Migrations Only
**Pros:** Schema always matches code
**Cons:** Doesn't catch drift from manual changes, no runtime validation
**Decision:** Use migrations AND runtime validation.

## Consequences

### Positive
- Schema mismatches caught at startup with clear messages
- Type errors caught before DB insert with Pydantic details
- No ORM overhead for high-throughput operations
- Easy to test with mocked connections

### Negative
- Must maintain `EXPECTED_COLUMNS` in sync with migrations
- Validation adds ~1 query at startup (negligible)
- Pydantic validation adds ~microseconds per insert

### Type Safety Spectrum

Different approaches provide different levels of type safety:

| Approach | Static (mypy) | Startup | Runtime | Use Case |
|----------|---------------|---------|---------|----------|
| Raw SQL | ❌ | ❌ | ❌ Cryptic | Don't use alone |
| Raw SQL + Pydantic | ✅ Models | ✅ Schema | ✅ Clear | High-perf paths |
| gRPC + Protobuf | ⚠️ Stubs | N/A | ✅ | Domain events |
| SQLModel ORM | ✅ Models | ⚠️ | ✅ | CRUD operations |

**Note:** In Python, "build time" = "mypy/type-check time". True compile-time safety requires a compiled language.

### Migration Path

Adapters using raw SQL that need schema validation:

| Adapter | Location | Status | Priority |
|---------|----------|--------|----------|
| `AgentEventStore` | `syn-adapters/events/store.py` | ✅ Done | - |
| `PostgresProjectionStore` | `syn-adapters/projection_stores/postgres_store.py` | ❌ TODO | High |
| `SessionToolsProjection` | `syn-adapters/projections/session_tools.py` | ❌ TODO | Medium |
| `SessionCostProjection` | `syn-domain/contexts/costs/.../projection.py` | ❌ TODO | Medium |

**Note:** Domain events use `EventStoreClient` (gRPC), which provides type safety via Protocol Buffers.
The old `PostgresEventStore` was dead code and has been deleted.

## Implementation Checklist

For each adapter using raw SQL:

- [ ] Define `EXPECTED_COLUMNS` constant
- [ ] Create Pydantic model with validators
- [ ] Add `_validate_schema()` method
- [ ] Call validation in `initialize()`
- [ ] Add `SchemaValidationError` exception
- [ ] Write positive/negative unit tests
- [ ] Update integration tests if needed

## References

- `packages/syn-adapters/src/syn_adapters/events/models.py` - Example Pydantic model
- `packages/syn-adapters/src/syn_adapters/events/store.py` - Example validation implementation
- `packages/syn-adapters/tests/events/test_schema_validation.py` - Example tests
