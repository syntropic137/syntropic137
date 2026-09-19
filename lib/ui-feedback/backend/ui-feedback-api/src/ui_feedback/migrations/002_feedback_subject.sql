-- UI Feedback Tables Migration
-- Version: 002
-- Description: Record WHAT a page was about when feedback was left.
--
-- One (kind, id) pair rather than one column per entity type: the host app
-- decides what its pages are about, and adding a page type needs no further
-- migration. ADD COLUMN IF NOT EXISTS keeps this idempotent and safe to apply
-- to a database that already ran 001.

ALTER TABLE feedback_items
    ADD COLUMN IF NOT EXISTS subject_kind VARCHAR(20),
    ADD COLUMN IF NOT EXISTS subject_id   VARCHAR(200);

-- Partial index: the overwhelming majority of rows have no subject, and the
-- only query that uses these columns filters on a non-NULL id.
CREATE INDEX IF NOT EXISTS idx_feedback_items_subject
    ON feedback_items(subject_kind, subject_id)
    WHERE subject_id IS NOT NULL;

-- Route filtering (agent triage: "everything left on /executions/...").
CREATE INDEX IF NOT EXISTS idx_feedback_items_route ON feedback_items(route);

COMMENT ON COLUMN feedback_items.subject_kind IS 'Domain object kind the page was about: execution, session, workflow, artifact, trigger';
COMMENT ON COLUMN feedback_items.subject_id IS 'Id of the domain object the page was about';
