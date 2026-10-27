-- Run Queue (ADR-072 D2-D5, D9, D10). Idempotent: runs at every startup.
-- Each `-- step:` line starts one step: it runs in its own transaction with its
-- row in execution_run_queue_schema_steps. Never rename or reorder a step;
-- append a new one.
-- step: executor_hosts
CREATE TABLE IF NOT EXISTS executor_hosts (
    host_id TEXT PRIMARY KEY,
    container_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch >= 0),
    draining BOOLEAN NOT NULL DEFAULT FALSE,
    successor_id TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- step: execution_budget
CREATE TABLE IF NOT EXISTS execution_budget (
    executor_id TEXT PRIMARY KEY,
    capacity INTEGER NOT NULL,
    in_use INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    CHECK (in_use >= 0 AND in_use <= capacity)
);
-- step: execution_budget_restart_columns
-- D3 Restart: which machine a budget belongs to, and the process that inherits
-- its slots as they are released.
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS container_id TEXT;
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS successor_id TEXT;

-- step: executor_pools
-- D13 Executor Pools. A budget row names its pool; pool capacity is a derived sum.
CREATE TABLE IF NOT EXISTS executor_pools (
    pool_id TEXT PRIMARY KEY,
    priority SMALLINT NOT NULL CHECK (priority >= 0),
    provider TEXT NOT NULL,
    region TEXT,
    isolation SMALLINT NOT NULL DEFAULT 10,
    capabilities TEXT[] NOT NULL DEFAULT '{}',
    overflow_delay_s INTEGER NOT NULL DEFAULT 60 CHECK (overflow_delay_s >= 0),
    defined_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO executor_pools (pool_id, priority, provider)
    VALUES ('default', 0, 'docker') ON CONFLICT DO NOTHING;
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS pool_id TEXT NOT NULL DEFAULT 'default';
-- Named and added once: ADD COLUMN IF NOT EXISTS ... REFERENCES re-adds the
-- constraint on some Postgres versions even when the column exists.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'execution_budget_pool_id_fkey'
        AND conrelid = 'execution_budget'::regclass) THEN
        ALTER TABLE execution_budget ADD CONSTRAINT execution_budget_pool_id_fkey
            FOREIGN KEY (pool_id) REFERENCES executor_pools (pool_id);
    END IF;
END $$;
-- step: execution_budget_drop_backend
-- Never written or read, before or since #1931, so an older image runs against
-- the table without it (#1965). A pool's provider replaces it (D3, D13).
ALTER TABLE execution_budget DROP COLUMN IF EXISTS backend;

-- step: execution_runs
CREATE TABLE IF NOT EXISTS execution_runs (
    execution_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN (
        'opening','admitted','claimed','fencing','reaped','abandoned','done','interrupted')),
    is_resume BOOLEAN NOT NULL,
    writer_epoch INTEGER NOT NULL CHECK (writer_epoch >= 0),
    reader_epoch INTEGER,
    executor_id TEXT REFERENCES execution_budget (executor_id),
    reconciler TEXT,
    lease_token BIGINT NOT NULL DEFAULT 0,
    leased_until TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    retry_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    reason TEXT,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    admitted_at TIMESTAMPTZ,
    -- A run carries a charge exactly while claimed, fencing or reaped (D3).
    CHECK ((executor_id IS NOT NULL) = (state IN ('claimed','fencing','reaped')))
);
CREATE INDEX IF NOT EXISTS execution_runs_state_admitted_idx
    ON execution_runs (state, admitted_at);

-- step: execution_budget_reap_scope
-- D5, D13: what the executor's reaper can reach (a Docker engine ID), derived
-- from the backend and never configured. A reconciler fences and takes over
-- only runs whose claimer shares it. Rows from before the column stay NULL,
-- which equals nothing, until a successor in their own container scopes them.
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS reap_scope TEXT;

-- step: execution_budget_claim_signals
-- D13 claim signals. claim_checked_at: the claim ran to its decision on this
-- row recently (a Claim Check), the only signal placement trusts to advertise
-- room. full_since: when this row last became full, NULL while it has room.
-- A trigger keeps full_since, so an older image's claim and release, which
-- know nothing of it, still keep it right during a rolling deploy. An explicit
-- write of full_since on a full row is kept (tests age it that way).
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS claim_checked_at TIMESTAMPTZ
    NOT NULL DEFAULT '-infinity';
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS full_since TIMESTAMPTZ;
CREATE OR REPLACE FUNCTION execution_budget_full_since() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.full_since := CASE WHEN NEW.in_use < NEW.capacity THEN NULL
        ELSE COALESCE(NEW.full_since, clock_timestamp()) END;
    RETURN NEW;
END $$;
-- Created only when absent, so a restart takes no table lock once it exists.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'execution_budget_full_since'
        AND tgrelid = 'execution_budget'::regclass) THEN
        CREATE TRIGGER execution_budget_full_since BEFORE INSERT OR UPDATE ON execution_budget
            FOR EACH ROW EXECUTE FUNCTION execution_budget_full_since();
    END IF;
END $$;
UPDATE execution_budget SET full_since = clock_timestamp()
    WHERE in_use >= capacity AND full_since IS NULL;

-- step: execution_runs_placement
-- D13 Placement, as Lane 2 telemetry on the row: never an event. Written at
-- claim, kept after release, overwritten by a later claim.
ALTER TABLE execution_runs ADD COLUMN IF NOT EXISTS placed_pool TEXT;
ALTER TABLE execution_runs ADD COLUMN IF NOT EXISTS overflowed BOOLEAN;
ALTER TABLE execution_runs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

-- step: credential_free_placement
-- #1917: an Executor Pool whose backend supplies no credentials (NoCredentials,
-- E2B) claims only runs whose workload needs none. Every run is 'agent' until
-- a start says otherwise (issue H), and every existing pool supplies them.
ALTER TABLE executor_pools ADD COLUMN IF NOT EXISTS supplies_credentials BOOLEAN
    NOT NULL DEFAULT TRUE;
ALTER TABLE execution_runs ADD COLUMN IF NOT EXISTS workload TEXT NOT NULL DEFAULT 'agent';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'execution_runs_workload_check'
        AND conrelid = 'execution_runs'::regclass) THEN
        ALTER TABLE execution_runs ADD CONSTRAINT execution_runs_workload_check
            CHECK (workload IN ('agent','scripted'));
    END IF;
END $$;
