-- Run Queue (ADR-072 D2-D5, D9, D10). Idempotent: runs at every startup.
CREATE TABLE IF NOT EXISTS executor_hosts (
    host_id TEXT PRIMARY KEY,
    container_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch >= 0),
    draining BOOLEAN NOT NULL DEFAULT FALSE,
    successor_id TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS execution_budget (
    executor_id TEXT PRIMARY KEY,
    capacity INTEGER NOT NULL,
    in_use INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    CHECK (in_use >= 0 AND in_use <= capacity)
);
-- D3 Restart: which machine a budget belongs to, and the process that inherits
-- its slots as they are released.
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS container_id TEXT;
ALTER TABLE execution_budget ADD COLUMN IF NOT EXISTS successor_id TEXT;

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
-- Never written or read; a pool's provider replaces it (D3, D13).
ALTER TABLE execution_budget DROP COLUMN IF EXISTS backend;

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
