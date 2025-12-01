-- Create event store schema
CREATE SCHEMA IF NOT EXISTS event_store;

-- Events table
CREATE TABLE IF NOT EXISTS event_store.events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type VARCHAR(255) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    event_data JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    version INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT unique_aggregate_version UNIQUE (aggregate_id, version)
);

-- Index for aggregate queries
CREATE INDEX IF NOT EXISTS idx_events_aggregate 
ON event_store.events (aggregate_type, aggregate_id, version);

-- Index for event type queries
CREATE INDEX IF NOT EXISTS idx_events_type 
ON event_store.events (event_type, created_at);

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

-- Processor todos table (for processor/todo pattern)
CREATE TABLE IF NOT EXISTS event_store.processor_todos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processor_name VARCHAR(255) NOT NULL,
    event_id UUID NOT NULL REFERENCES event_store.events(id),
    status VARCHAR(50) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    
    CONSTRAINT unique_processor_event UNIQUE (processor_name, event_id)
);

-- Index for pending todos
CREATE INDEX IF NOT EXISTS idx_todos_pending 
ON event_store.processor_todos (processor_name, status) 
WHERE status = 'pending';

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for workflow definitions
CREATE TRIGGER update_workflow_definitions_timestamp
    BEFORE UPDATE ON public.workflow_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Comments for documentation
COMMENT ON SCHEMA event_store IS 'Event sourcing infrastructure';
COMMENT ON TABLE event_store.events IS 'Immutable event log';
COMMENT ON TABLE event_store.processor_todos IS 'Processor work queue (todo pattern)';
COMMENT ON TABLE public.workflow_definitions IS 'Workflow templates seeded from YAML';
COMMENT ON TABLE public.artifacts IS 'Phase output artifacts';

