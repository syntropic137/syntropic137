-- =============================================================================
-- AEF Unified Database Schema - Initial Setup
-- =============================================================================
-- This script initializes the consolidated TimescaleDB database.
--
-- NOTE: The event-sourcing-platform (ESP) manages its own tables via sqlx migrations:
--   - events, aggregates, idempotency, projection_checkpoints
-- These are created automatically when the event-store service starts.
--
-- This script only creates:
-- - TimescaleDB/pgvector extensions
-- - Observability tables (agent_events) - used by Dashboard API
-- - Workflow management tables (workflow_definitions, artifacts)
-- =============================================================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable pgvector for future AI/embedding features
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- OBSERVABILITY SCHEMA (Agent Events / Telemetry)
-- =============================================================================

-- Agent events table - high-volume telemetry data
CREATE TABLE IF NOT EXISTS public.agent_events (
    id UUID DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    session_id UUID,
    execution_id UUID,
    phase_id VARCHAR(255),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data JSONB NOT NULL DEFAULT '{}',
    
    -- Composite primary key for hypertable
    PRIMARY KEY (id, timestamp)
);

-- Convert to hypertable for time-series optimization
-- 1-hour chunks for high-volume telemetry data
SELECT create_hypertable(
    'public.agent_events',
    'timestamp',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Enable compression on agent_events for older data (after 7 days)
ALTER TABLE public.agent_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'session_id, execution_id'
);

-- Auto-compress chunks older than 7 days
SELECT add_compression_policy('public.agent_events', INTERVAL '7 days', if_not_exists => TRUE);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_agent_events_session 
ON public.agent_events (session_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_agent_events_execution 
ON public.agent_events (execution_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_agent_events_type 
ON public.agent_events (event_type, timestamp DESC);

-- =============================================================================
-- WORKFLOW MANAGEMENT SCHEMA
-- =============================================================================

-- Workflow definitions table (seeded from YAML)
CREATE TABLE IF NOT EXISTS public.workflow_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    version VARCHAR(50) NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Artifacts table
CREATE TABLE IF NOT EXISTS public.artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL,
    phase_name VARCHAR(255) NOT NULL,
    artifact_name VARCHAR(255) NOT NULL,
    artifact_type VARCHAR(100) NOT NULL,
    content TEXT,
    content_hash VARCHAR(64),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT unique_workflow_artifact UNIQUE (workflow_id, phase_name, artifact_name)
);

-- Index for workflow artifact lookups
CREATE INDEX IF NOT EXISTS idx_artifacts_workflow 
ON public.artifacts (workflow_id, phase_name);

-- =============================================================================
-- UTILITY FUNCTIONS
-- =============================================================================

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for workflow definitions
DROP TRIGGER IF EXISTS update_workflow_definitions_timestamp ON public.workflow_definitions;
CREATE TRIGGER update_workflow_definitions_timestamp
    BEFORE UPDATE ON public.workflow_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- DOCUMENTATION
-- =============================================================================
COMMENT ON TABLE public.agent_events IS 'Observability telemetry events (hypertable)';
COMMENT ON TABLE public.workflow_definitions IS 'Workflow templates seeded from YAML';
COMMENT ON TABLE public.artifacts IS 'Phase output artifacts';
