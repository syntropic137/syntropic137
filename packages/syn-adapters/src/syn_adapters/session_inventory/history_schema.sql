-- Historical backfill (#1398). Separate from schema.sql so its lifecycle is explicit.

-- Legacy records without durable source IDs, materialized once. A fingerprint
-- is claimed by exactly one snapshot ordinal; restarts reuse it.
CREATE TABLE IF NOT EXISTS session_backfill_receipts (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{64}$'),
    snapshot_id UUID NOT NULL,
    ordinal BIGINT NOT NULL CHECK (ordinal >= 1),
    materialized_seq BIGSERIAL NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (source_instance_id, execution_id, fingerprint),
    UNIQUE (source_instance_id, execution_id, snapshot_id, ordinal)
);
CREATE INDEX IF NOT EXISTS session_backfill_receipts_order
    ON session_backfill_receipts (source_instance_id, execution_id, materialized_seq);

-- Durable bulk to-do list. Only the live inventory worker drains it.
CREATE TABLE IF NOT EXISTS session_backfill_queue (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'completed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_token BIGINT NOT NULL DEFAULT 0,
    leased_until TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    retry_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    job_id TEXT,
    failure_code TEXT,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_instance_id, execution_id, request_key)
);
CREATE INDEX IF NOT EXISTS session_backfill_queue_pending
    ON session_backfill_queue (source_instance_id, retry_at, execution_id)
    WHERE state = 'pending';
