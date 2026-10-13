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
    backend TEXT NOT NULL DEFAULT 'local',
    capacity INTEGER NOT NULL,
    in_use INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    CHECK (in_use >= 0 AND in_use <= capacity)
);

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
