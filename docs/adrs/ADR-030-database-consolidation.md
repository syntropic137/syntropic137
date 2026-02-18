# ADR-030: Database Consolidation to Single TimescaleDB Instance

## Status

**Accepted** - 2025-12-18

## Context

Following ADR-026 (TimescaleDB for Observability), we had **two PostgreSQL instances** running in the development environment:

```
┌──────────────────┐     ┌──────────────────┐
│ aef-postgres     │     │ aef-timescaledb  │
│ :5432            │     │ :5433            │
│                  │     │                  │
│ ├── events       │     │ └── agent_events │
│ ├── aggregates   │     │     (hypertable) │
│ └── projections  │     │                  │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         ▼                        ▼
┌──────────────────┐     ┌──────────────────┐
│ Event Store      │     │ Dashboard API    │
│ (Rust gRPC)      │     │ (Python)         │
└──────────────────┘     └──────────────────┘
```

### Problems with Two Databases

1. **Operational Complexity** - Two containers to manage, monitor, backup
2. **Port Confusion** - 5432 vs 5433, easy to misconfigure
3. **Resource Waste** - Two PostgreSQL processes, double the memory
4. **Missed Optimization** - Domain events are append-only but not using hypertables
5. **Future Scaling** - Harder to migrate to managed database (Supabase)

### Key Insight

**Event sourcing is fundamentally append-only** - the same access pattern that TimescaleDB optimizes for time-series data. The domain `events` table would benefit from hypertable optimizations just like `agent_events`.

## Decision

**Consolidate both PostgreSQL instances into a single TimescaleDB instance.**

### Architecture

```
┌────────────────────────────────────────────┐
│ aef-timescaledb (single instance)          │
│ :5432                                      │
│                                            │
│ Tables managed by ESP (sqlx migrations):   │
│ ├── events                                 │
│ ├── aggregates                             │
│ ├── idempotency                            │
│ └── projection_checkpoints                 │
│                                            │
│ Tables managed by init-db:                 │
│ ├── agent_events (hypertable)              │
│ ├── workflow_definitions                   │
│ └── artifacts                              │
│                                            │
└──────────────────┬─────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌──────────────────┐  ┌──────────────────┐
│ Event Store      │  │ Dashboard API    │
│ (Rust gRPC)      │  │ (Python)         │
└──────────────────┘  └──────────────────┘
```

### Database Configuration

```yaml
# docker-compose.dev.yaml
timescaledb:
  image: timescale/timescaledb:latest-pg16
  container_name: syn-db
  environment:
    POSTGRES_DB: aef        # Single unified database
    POSTGRES_USER: aef
    POSTGRES_PASSWORD: aef_dev_password
  ports:
    - "5432:5432"           # Standard PostgreSQL port
```

### Connection Strings

Both services connect to the same database:

```bash
# Event Store (Rust)
DATABASE_URL=postgres://aef:aef_dev_password@timescaledb:5432/aef

# Dashboard API (Python) - via settings
TIMESCALE_HOST=timescaledb
TIMESCALE_PORT=5432
TIMESCALE_DB=aef
```

## Decision Drivers

1. **Simplicity** - One database to manage, backup, monitor
2. **Performance** - TimescaleDB hypertables for append-only workloads
3. **Cost** - Half the memory, one connection pool
4. **Future-Ready** - Easy path to Supabase (PostgreSQL + Vector + S3)
5. **DI Support** - Settings allow separate URLs if needed

## Consequences

### Positive

✅ **Single Container** - Reduced from 2 PostgreSQL containers to 1

✅ **Single Port** - No more 5432 vs 5433 confusion

✅ **Unified Backup** - One `pg_dump` for all data

✅ **Better Performance** - TimescaleDB optimizations for all append-only tables

✅ **Lower Memory** - Single PostgreSQL process (~256MB vs ~512MB)

✅ **Supabase Ready** - Direct path to cloud PostgreSQL

### Negative

⚠️ **Shared Resources** - High observability writes could impact domain events

⚠️ **Single Point of Failure** - One database means one failure domain

### Mitigations

1. **Separate Tables** - Domain events and observability in different tables
2. **Connection Pooling** - Each service has its own pool
3. **Future Option** - Settings support separate `OBSERVABILITY_DATABASE_URL` if needed

## Migration Notes

**No data migration required** - System is in alpha, no production data.

Simply:
1. `docker compose down -v` (removes old volumes)
2. `docker compose up -d` (starts unified database)
3. Tables created automatically by ESP migrations and init-db script

## Data Retention Strategy

**Critical distinction between event types:**

| Aspect | Domain Events (ESP) | Observability Events |
|--------|---------------------|---------------------|
| **Table** | `events` | `agent_events` |
| **Purpose** | Business state, audit trail | Debugging, metrics |
| **Retention** | **Forever** ♾️ | Configurable (7-90 days) |
| **Compression** | Optional | Required (90% reduction) |
| **Examples** | WorkflowStarted, PhaseCompleted | tool_execution, token_usage |

### Domain Events: Forever

Domain events are the **source of truth** for event sourcing. They:
- Enable aggregate replay and rebuilding projections
- Provide complete audit trail for compliance
- Support temporal queries ("what was the state on date X?")

**Never auto-delete domain events.** The ESP `events` table has no retention policy.

### Observability Events: Configurable

Observability events are **operational telemetry**. They:
- Help debug agent behavior
- Power real-time dashboards
- Can be safely aged out after analysis

The `agent_events` hypertable supports optional retention:

```sql
-- Example: Add 30-day retention (only if needed)
SELECT add_retention_policy('agent_events', INTERVAL '30 days');
```

Currently **no retention policy is set** - observability events are kept indefinitely.
Configure based on storage costs vs debugging needs.

## Authentication Strategy

AEF is primarily a **GitHub-integrated service**. Authentication approach:

| Component | Auth Method | Rationale |
|-----------|-------------|-----------|
| **Agent Operations** | GitHub App | Native GitHub integration, auto-rotating tokens |
| **Dashboard UI** | GitHub OAuth | Users already have GitHub accounts |
| **API Access** | GitHub App tokens | Consistent with agent auth |

### Why Not Supabase Auth?

While Supabase offers convenient auth with Row-Level Security (RLS), we avoid it because:

1. **Vendor lock-in** - RLS policies are Supabase-specific
2. **GitHub-native** - Our users are developers, already on GitHub
3. **Simpler model** - One auth system (GitHub) vs two

### Future: Multi-tenant Dashboard

For a managed service with multiple organizations:

```
┌─────────────────────────────────────────────────┐
│                 Dashboard App                    │
│  ┌───────────────────────────────────────────┐  │
│  │ GitHub OAuth Login                         │  │
│  │  → Map GitHub org to AEF tenant            │  │
│  │  → Use GitHub App for repo operations      │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Related ADRs

- **ADR-026**: TimescaleDB for Observability Storage (introduces TimescaleDB)
- **ADR-007**: Event Store Integration (describes ESP architecture)
- **ADR-012**: Artifact Storage (future Supabase consideration)
- **ADR-022**: Secure Token Architecture (GitHub App tokens)

## Future Work

### Supabase Migration Path

For managed PostgreSQL (not auth):

```
Current:  Docker TimescaleDB → Future: Supabase PostgreSQL
                                      + Supabase Storage (replaces MinIO)
                                      + Supabase Vector (pgvector)
                                      - NOT Supabase Auth (use GitHub)
```

### Hypertable for Domain Events

Future optimization: Convert ESP `events` table to hypertable for better append performance. Requires changes to ESP migrations.
