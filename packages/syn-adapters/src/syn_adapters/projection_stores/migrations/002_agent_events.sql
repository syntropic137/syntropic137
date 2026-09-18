-- Migration: 002_agent_events
-- Description: Create simplified agent_events hypertable for observability
-- Date: 2025-12-17
-- ADR: ADR-029 Simplified Event System

-- Enable TimescaleDB if not already enabled
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Drop old table if it exists (we're in alpha, no backwards compatibility needed)
DROP TABLE IF EXISTS agent_observations;

-- Create new simplified table
CREATE TABLE IF NOT EXISTS agent_events (
    time TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    execution_id TEXT,
    phase_id TEXT,
    data JSONB NOT NULL
);

-- Create hypertable (partitioned by time for time-series optimization)
SELECT create_hypertable(
    'agent_events',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_events_session ON agent_events (session_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON agent_events (event_type, time DESC);
CREATE INDEX IF NOT EXISTS idx_events_execution ON agent_events (execution_id, time DESC);

-- The two composite indexes the cost read paths need (#1338).
--
-- Every cost query pairs an id with an event_type: the session-cost batch
-- queries are `session_id = ANY($1) AND event_type = $2`, the execution-cost
-- ones are `execution_id = $1 AND event_type = $2`. Neither pair is served by
-- the three indexes above, which lead on one column and then on `time` - so
-- the id narrows the scan and `event_type` is then re-checked on every row the
-- id matched.
--
-- WHAT THESE DO AND DO NOT FIX. They cover the UNCOMPRESSED chunks only.
-- `event_type` is in neither compress_segmentby (session_id) nor
-- compress_orderby (time), so inside a compressed chunk it cannot be answered
-- from an index at all - the batch is decompressed and filtered row by row,
-- whatever indexes exist on the hypertable. With a 1-day compression policy
-- (below) that makes these indexes the fix for today's data and no fix at all
-- for yesterday's.
--
-- For `session_id` that ceiling is survivable: session_id IS the segmentby
-- column, so a compressed chunk discards whole segments it does not need
-- before decompressing anything, and the work stays proportional to the
-- sessions on the page. For `execution_id` it is not: execution_id is neither
-- segmentby nor orderby, so an execution-keyed query decompresses every
-- segment of every chunk in range. That path needs a read model, not an index
-- (#1338, still open).
CREATE INDEX IF NOT EXISTS idx_events_session_type ON agent_events (session_id, event_type, time DESC);
CREATE INDEX IF NOT EXISTS idx_events_execution_type ON agent_events (execution_id, event_type, time DESC);

-- GIN index on data for JSONB queries
CREATE INDEX IF NOT EXISTS idx_events_data ON agent_events USING GIN (data);

-- Configure compression (for scale - compress after 1 day)
ALTER TABLE agent_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'session_id',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('agent_events', INTERVAL '1 day', if_not_exists => TRUE);

-- Optional: Retention policy (uncomment for production)
-- Keep events for 90 days
-- SELECT add_retention_policy('agent_events', INTERVAL '90 days', if_not_exists => TRUE);

-- Grant permissions (adjust as needed for your environment)
-- GRANT SELECT, INSERT ON agent_events TO syn_app;
