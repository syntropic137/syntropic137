CREATE TABLE IF NOT EXISTS session_capture_catalog (
    source_instance_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_instance_id, producer_id, capture_id)
);

CREATE INDEX IF NOT EXISTS session_capture_catalog_revision_idx
    ON session_capture_catalog (
        source_instance_id, (payload->'run'->>'execution_id'),
        (payload->>'harness'), (payload->>'native_id'),
        (payload->'archive'->>'sha256'), producer_id, capture_id
    );

CREATE TABLE IF NOT EXISTS session_capture_delivery_jobs (
    destination_id TEXT NOT NULL,
    source_instance_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    queued BOOLEAN NOT NULL DEFAULT FALSE,
    lease_token BIGINT NOT NULL DEFAULT 0,
    leased_until TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    retry_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    PRIMARY KEY (destination_id, source_instance_id, producer_id, capture_id),
    FOREIGN KEY (source_instance_id,producer_id,capture_id)
        REFERENCES session_capture_catalog(source_instance_id,producer_id,capture_id)
);
CREATE INDEX IF NOT EXISTS session_capture_delivery_pending
    ON session_capture_delivery_jobs(destination_id,source_instance_id,retry_at)
    WHERE NOT queued;

CREATE TABLE IF NOT EXISTS session_inventory_heads (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    snapshot_id UUID,
    evidence_watermark BIGINT NOT NULL DEFAULT -1,
    PRIMARY KEY (source_instance_id, execution_id)
);
CREATE TABLE IF NOT EXISTS session_inventory_snapshots (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL,
    metadata JSONB NOT NULL,
    published BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_instance_id, execution_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS session_inventory_items (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('node','membership','edge','capture','gap','retraction','binding')),
    ordinal BIGINT NOT NULL CHECK (ordinal >= 0),
    payload JSONB NOT NULL,
    PRIMARY KEY (source_instance_id, execution_id, snapshot_id, kind, ordinal),
    FOREIGN KEY (source_instance_id, execution_id, snapshot_id)
        REFERENCES session_inventory_snapshots (source_instance_id, execution_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS session_evidence_watermarks (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    watermark BIGINT NOT NULL DEFAULT 0,
    dispatched_watermark BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (source_instance_id, execution_id),
    CHECK (dispatched_watermark <= watermark)
);
CREATE INDEX IF NOT EXISTS session_evidence_pending_idx
    ON session_evidence_watermarks (source_instance_id, execution_id)
    WHERE watermark > dispatched_watermark;
CREATE TABLE IF NOT EXISTS session_evidence_batches (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    producer_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (source_instance_id, execution_id, sequence),
    UNIQUE (source_instance_id, execution_id, producer_id, batch_id)
);
CREATE TABLE IF NOT EXISTS session_inventory_jobs (
    job_id TEXT PRIMARY KEY,
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    global_position BIGINT NOT NULL,
    stage TEXT NOT NULL,
    payload JSONB NOT NULL,
    lease_token BIGINT NOT NULL DEFAULT 0,
    leased_until TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    retry_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity'
);
CREATE INDEX IF NOT EXISTS session_inventory_jobs_prefix_idx
    ON session_inventory_jobs (source_instance_id, job_id text_pattern_ops);
CREATE INDEX IF NOT EXISTS session_inventory_jobs_run_idx
    ON session_inventory_jobs (source_instance_id, execution_id, global_position DESC);
CREATE INDEX IF NOT EXISTS session_inventory_jobs_pending_idx
    ON session_inventory_jobs (retry_at, global_position)
    WHERE stage IN ('pending','publishing');
CREATE TABLE IF NOT EXISTS session_capture_spools (
    source_instance_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    after_sequence BIGINT NOT NULL DEFAULT 0 CHECK (after_sequence >= 0),
    watermark BIGINT CHECK (watermark >= after_sequence),
    lease_token BIGINT NOT NULL DEFAULT 0,
    leased_until TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    retry_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    PRIMARY KEY (source_instance_id,session_id)
);
-- Allocate one source-wide sequence namespace for the canonical replication producer.
CREATE TABLE IF NOT EXISTS session_inventory_replication_sequences (
    source_instance_id TEXT PRIMARY KEY,
    high_watermark BIGINT NOT NULL CHECK (high_watermark >= 0)
);
-- Publication order is local truth, retained even while optional replication is disabled.
CREATE TABLE IF NOT EXISTS session_inventory_publications (
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL,
    parent_snapshot_id UUID,
    revision_sequence BIGINT NOT NULL CHECK (revision_sequence > 0),
    first_record_sequence BIGINT NOT NULL CHECK (first_record_sequence > 0),
    record_high_watermark BIGINT NOT NULL CHECK (record_high_watermark >= 0),
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_instance_id, execution_id, snapshot_id),
    UNIQUE (source_instance_id, execution_id, revision_sequence),
    FOREIGN KEY (source_instance_id, execution_id, snapshot_id)
        REFERENCES session_inventory_snapshots (source_instance_id, execution_id, snapshot_id),
    FOREIGN KEY (source_instance_id, execution_id, parent_snapshot_id)
        REFERENCES session_inventory_publications (source_instance_id, execution_id, snapshot_id),
    CHECK ((revision_sequence = 1) = (parent_snapshot_id IS NULL))
);
CREATE TABLE IF NOT EXISTS session_inventory_replication_jobs (
    destination_id TEXT NOT NULL,
    source_instance_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL,
    next_offset BIGINT NOT NULL DEFAULT 0 CHECK (next_offset >= 0),
    queued BOOLEAN NOT NULL DEFAULT FALSE,
    lease_token BIGINT NOT NULL DEFAULT 0,
    leased_until TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    retry_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
    PRIMARY KEY (destination_id,source_instance_id,execution_id,snapshot_id),
    FOREIGN KEY (source_instance_id,execution_id,snapshot_id)
        REFERENCES session_inventory_publications(source_instance_id,execution_id,snapshot_id)
);
CREATE INDEX IF NOT EXISTS session_inventory_replication_pending_idx
    ON session_inventory_replication_jobs(destination_id,source_instance_id,retry_at)
    WHERE NOT queued;

-- Receipt polling has its own lease; queued means local exporter durability only.
ALTER TABLE session_capture_delivery_jobs ADD COLUMN IF NOT EXISTS receipt_recorded BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE session_capture_delivery_jobs ADD COLUMN IF NOT EXISTS receipt_lease_token BIGINT NOT NULL DEFAULT 0;
ALTER TABLE session_capture_delivery_jobs ADD COLUMN IF NOT EXISTS receipt_poll_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity';
CREATE INDEX IF NOT EXISTS session_capture_receipt_pending
    ON session_capture_delivery_jobs(destination_id,source_instance_id,receipt_poll_at)
    WHERE queued AND NOT receipt_recorded;

-- Object-level revocation applies to every capture sharing these exact bytes.
CREATE TABLE IF NOT EXISTS session_transcript_revocations (
    source_instance_id TEXT NOT NULL,
    archive_sha256 TEXT NOT NULL CHECK (archive_sha256 ~ '^[a-f0-9]{64}$'),
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_instance_id, archive_sha256)
);
