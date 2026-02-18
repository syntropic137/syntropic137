-- Projection Tables Migration
-- Version: 001
-- Description: Create tables for CQRS projection read models
--
-- Each projection has its own isolated table for:
-- - Independent scaling
-- - Isolated testing
-- - Clear ownership per vertical slice
--
-- Note: The PostgresProjectionStore creates tables dynamically,
-- but this migration provides the initial schema for documentation
-- and manual setup if needed.

-- =====================================================
-- Workflow Projections
-- =====================================================

-- Workflow list view (summary data)
CREATE TABLE IF NOT EXISTS workflow_summaries (
    id VARCHAR(255) PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_summaries_updated_at
    ON workflow_summaries(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_summaries_status
    ON workflow_summaries((data->>'status'));

-- Workflow detail view (full data)
CREATE TABLE IF NOT EXISTS workflow_details (
    id VARCHAR(255) PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_details_updated_at
    ON workflow_details(updated_at DESC);


-- =====================================================
-- Session Projections
-- =====================================================

-- Session list view
CREATE TABLE IF NOT EXISTS session_summaries (
    id VARCHAR(255) PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_updated_at
    ON session_summaries(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_summaries_workflow
    ON session_summaries((data->>'workflow_id'));


-- =====================================================
-- Artifact Projections
-- =====================================================

-- Artifact list view
CREATE TABLE IF NOT EXISTS artifact_summaries (
    id VARCHAR(255) PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifact_summaries_updated_at
    ON artifact_summaries(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_artifact_summaries_workflow
    ON artifact_summaries((data->>'workflow_id'));


-- =====================================================
-- Dashboard Metrics Projection
-- =====================================================

-- Aggregated metrics (single row)
CREATE TABLE IF NOT EXISTS dashboard_metrics (
    id VARCHAR(50) PRIMARY KEY DEFAULT 'global',
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- =====================================================
-- Projection State Tracking
-- =====================================================

-- Tracks the last processed event position for each projection
-- Used for catch-up subscriptions to resume from where they left off
CREATE TABLE IF NOT EXISTS projection_states (
    projection_name VARCHAR(255) PRIMARY KEY,
    last_event_position BIGINT DEFAULT 0,
    last_event_id VARCHAR(255),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to all projection tables
DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        'workflow_summaries',
        'workflow_details',
        'session_summaries',
        'artifact_summaries',
        'dashboard_metrics',
        'projection_states'
    ])
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS update_%s_updated_at ON %s;
            CREATE TRIGGER update_%s_updated_at
                BEFORE UPDATE ON %s
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        ', tbl, tbl, tbl, tbl);
    END LOOP;
END $$;


-- =====================================================
-- Comments for documentation
-- =====================================================

COMMENT ON TABLE workflow_summaries IS 'Read model for workflow list views, maintained by WorkflowListProjection';
COMMENT ON TABLE workflow_details IS 'Read model for workflow detail views, maintained by WorkflowDetailProjection';
COMMENT ON TABLE session_summaries IS 'Read model for session list views, maintained by SessionListProjection';
COMMENT ON TABLE artifact_summaries IS 'Read model for artifact list views, maintained by ArtifactListProjection';
COMMENT ON TABLE dashboard_metrics IS 'Aggregated metrics for dashboard, maintained by DashboardMetricsProjection';
COMMENT ON TABLE projection_states IS 'Tracks last processed event position for each projection';
