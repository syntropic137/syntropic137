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
