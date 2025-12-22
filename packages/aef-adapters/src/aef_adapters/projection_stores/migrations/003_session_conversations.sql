-- Migration: 003_session_conversations
-- Description: Create session_conversations table for conversation log index
-- ADR: ADR-035-conversation-storage-architecture.md

-- Session-level conversation storage index
-- Session is the atomic unit - one session = one conversation file in S3
CREATE TABLE IF NOT EXISTS session_conversations (
    session_id TEXT PRIMARY KEY,

    -- Storage reference (MinIO/S3)
    bucket TEXT NOT NULL DEFAULT 'aef-conversations',
    object_key TEXT NOT NULL,
    size_bytes BIGINT,

    -- Correlation (for projection aggregation)
    execution_id TEXT,
    phase_id TEXT,
    workflow_id TEXT,

    -- Summary metrics (extracted from conversation)
    event_count INTEGER,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    tool_counts JSONB,  -- {"Bash": 5, "Read": 3, "Write": 2}

    -- Timestamps
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,

    -- Agent metadata
    model TEXT,
    success BOOLEAN,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_session_conv_execution ON session_conversations(execution_id);
CREATE INDEX IF NOT EXISTS idx_session_conv_workflow ON session_conversations(workflow_id);
CREATE INDEX IF NOT EXISTS idx_session_conv_time ON session_conversations(started_at DESC);

-- Comment for documentation
COMMENT ON TABLE session_conversations IS 'Index of conversation logs stored in MinIO/S3. See ADR-035.';
