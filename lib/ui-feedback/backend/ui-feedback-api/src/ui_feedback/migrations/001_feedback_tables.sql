-- UI Feedback Tables Migration
-- Version: 001
-- Description: Create tables for feedback items and media storage

-- =====================================================
-- Feedback Items Table
-- =====================================================

CREATE TABLE IF NOT EXISTS feedback_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Location context
    url TEXT NOT NULL,
    route TEXT,
    viewport_width INT,
    viewport_height INT,
    click_x INT,
    click_y INT,
    css_selector TEXT,
    xpath TEXT,
    component_name TEXT,

    -- Feedback content
    feedback_type VARCHAR(20) DEFAULT 'bug',  -- bug, feature, ui_ux, performance, question, other
    comment TEXT,

    -- Ticket workflow
    status VARCHAR(20) DEFAULT 'open',  -- open, in_progress, resolved, closed, wont_fix
    priority VARCHAR(10) DEFAULT 'medium',  -- low, medium, high, critical
    assigned_to TEXT,
    resolution_notes TEXT,

    -- Metadata
    app_name TEXT NOT NULL,
    app_version TEXT,
    user_agent TEXT,

    -- Environment context (for knowing where feedback came from)
    environment VARCHAR(50),    -- development, staging, production
    git_commit VARCHAR(50),     -- git commit hash
    git_branch VARCHAR(100),    -- git branch name
    hostname TEXT,              -- hostname where app is running

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_feedback_items_status ON feedback_items(status);
CREATE INDEX IF NOT EXISTS idx_feedback_items_app ON feedback_items(app_name);
CREATE INDEX IF NOT EXISTS idx_feedback_items_type ON feedback_items(feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_items_priority ON feedback_items(priority);
CREATE INDEX IF NOT EXISTS idx_feedback_items_created ON feedback_items(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_items_environment ON feedback_items(environment);

-- =====================================================
-- Feedback Media Table
-- =====================================================

CREATE TABLE IF NOT EXISTS feedback_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_id UUID NOT NULL REFERENCES feedback_items(id) ON DELETE CASCADE,

    -- Media info
    media_type VARCHAR(20) NOT NULL,  -- screenshot, voice_note
    mime_type VARCHAR(50) NOT NULL,   -- image/png, audio/webm, etc.
    file_name TEXT,
    file_size INT,

    -- Storage (PostgreSQL for dev, external URL for S3/Supabase later)
    data BYTEA,           -- Binary data for local storage
    external_url TEXT,    -- URL for external storage (future)

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_media_feedback ON feedback_media(feedback_id);
CREATE INDEX IF NOT EXISTS idx_feedback_media_type ON feedback_media(media_type);

-- =====================================================
-- Auto-update timestamps
-- =====================================================

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_feedback_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to feedback_items
DROP TRIGGER IF EXISTS trigger_feedback_items_updated_at ON feedback_items;
CREATE TRIGGER trigger_feedback_items_updated_at
    BEFORE UPDATE ON feedback_items
    FOR EACH ROW
    EXECUTE FUNCTION update_feedback_updated_at();

-- =====================================================
-- Comments for documentation
-- =====================================================

COMMENT ON TABLE feedback_items IS 'Stores UI feedback items with location context and ticket workflow';
COMMENT ON TABLE feedback_media IS 'Stores media attachments (screenshots, voice notes) for feedback items';

COMMENT ON COLUMN feedback_items.css_selector IS 'CSS selector path to the clicked element';
COMMENT ON COLUMN feedback_items.xpath IS 'XPath to the clicked element';
COMMENT ON COLUMN feedback_items.component_name IS 'React component name if detected';
COMMENT ON COLUMN feedback_items.feedback_type IS 'Type: bug, feature, ui_ux, performance, question, other';
COMMENT ON COLUMN feedback_items.status IS 'Workflow status: open, in_progress, resolved, closed, wont_fix';
COMMENT ON COLUMN feedback_items.priority IS 'Priority: low, medium, high, critical';
COMMENT ON COLUMN feedback_items.environment IS 'Environment: development, staging, production';
COMMENT ON COLUMN feedback_items.git_commit IS 'Git commit hash for tracking which version';
COMMENT ON COLUMN feedback_items.git_branch IS 'Git branch name';
COMMENT ON COLUMN feedback_items.hostname IS 'Hostname where the app is running';

COMMENT ON COLUMN feedback_media.media_type IS 'Type of media: screenshot or voice_note';
COMMENT ON COLUMN feedback_media.data IS 'Binary data for local/dev storage';
COMMENT ON COLUMN feedback_media.external_url IS 'URL for external storage (S3/Supabase) - future use';
