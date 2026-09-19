-- Migration: 005_agent_event_day_rollup
-- Description: Per-(day, session, execution) rollup of agent_events, so the
--              contribution heatmap costs what it RETURNS instead of what the
--              telemetry table HOLDS.
-- Date: 2026-09-18
-- Issue: #1253

-- NOTHING EXECUTES THIS FILE. Read it as documentation, not as the thing that
-- ran. No migration runner exists in this repository for this directory; the
-- only `just` target that feeds .sql to psql is `feedback-migrate`, and it
-- points at lib/ui-feedback. Production and every test database get this
-- schema from EventStoreSchema.ensure_schema() at API startup
-- (syn_adapters/events/schema.py), which is therefore the authoritative
-- definition. If the two ever disagree, ensure_schema() is what you have.
--
-- Numbered 005, not 004: PR #1325 (#1322) adds 004_tool_call_counts.sql to
-- this directory. Since neither file is executed the number is only a name,
-- but two files claiming one number is a reader's trap, so this one moved.

-- WHY THIS TABLE EXISTS
--
-- GET /api/v1/insights/contribution-heatmap returns one row per day. It used
-- to read one agent_events row per event in the window to produce them:
-- 13.6-14.8s in production, the slowest endpoint in the system by ~5x, on the
-- dashboard landing page.
--
-- Three of its numbers are "how many DISTINCT things happened on day D":
-- executions per day, commits per day, and which sessions have their first
-- observation inside the window. No index answers a DISTINCT without visiting
-- the rows carrying the values, so no rewrite of those statements can bound
-- them. They need a rollup, and this is it: one row per
-- (day, session_id, execution_id) triple, which is the grain those three
-- answers are actually about.
--
-- WHY A TRIGGER AND NOT A PROJECTION
--
-- A new event-store projection replays from position zero on first deploy and
-- stalls every other projection while it does (#1318) - the dashboard goes
-- blind for ~20 minutes. This table is maintained by the database from the
-- table it summarises, so it never touches the event store and never enters
-- the projection coordinator. It is also the only way to catch every write:
-- insert_batch() uses COPY, which no application-level hook sees.
--
-- WHY THE WHOLE MIGRATION IS ONE TRANSACTION
--
-- CREATE TRIGGER takes ACCESS EXCLUSIVE on agent_events, so concurrent
-- inserts block until this commits. The backfill therefore sees exactly the
-- rows the trigger did not, with no window in between where an event is
-- counted twice or not at all. The cost is that ingest is blocked for the
-- length of one full scan of agent_events - plan the deploy for it.
--
-- That cost is paid ONCE. EventStoreSchema._create_day_rollup(), which is
-- what actually runs, wraps exactly these statements in one transaction and
-- skips the backfill when the table already exists - and because it is one
-- transaction, the table existing proves the backfill committed. Without that
-- gate the scan would be repeated at every API startup, blocking ingestion
-- each time, for a result ON CONFLICT DO NOTHING already made a no-op.

BEGIN;

CREATE TABLE IF NOT EXISTS agent_event_day_rollup (
    day          DATE        NOT NULL,
    session_id   TEXT        NOT NULL,
    execution_id TEXT,
    -- MIN(time) of the triple. The heatmap counts a session on the day it
    -- STARTED, and needs the instant, not just the day, to pick that day.
    first_time   TIMESTAMPTZ NOT NULL,
    commits      BIGINT      NOT NULL DEFAULT 0
);

-- THE KEY. execution_id is nullable, so it has to say what two NULLs mean. A
-- plain UNIQUE says "distinct", which would give unattributed telemetry one
-- rollup row per event and lose the bound this table exists to provide.
--
-- This was originally written as a unique index on COALESCE(execution_id, ''),
-- which bought that answer but also merged a genuine EMPTY-STRING execution id
-- into the unattributed row - COALESCE maps both to '' (#1371). NULLS NOT
-- DISTINCT (PostgreSQL 15+; production is 16.15) says the intended thing and
-- nothing more, and it is the grain the backfill's GROUP BY already produced.
--
-- A CONSTRAINT and not a bare index, so both ON CONFLICT clauses below can
-- name it instead of inferring an arbiter: inference matches on columns and
-- cannot express "the NULLS NOT DISTINCT one".
--
-- EventStoreSchema._create_day_rollup() is what actually runs, and it does
-- this under a guard - ADD CONSTRAINT has no IF NOT EXISTS, and it runs at
-- every API startup. That guard also DROPS a COALESCE index left by an
-- earlier deploy: leaving both in place would leave the defect, since the old
-- index would go on merging NULL with '' whatever this one says. It is safe
-- while the trigger is live because it shares that function's single
-- transaction, and because this key is strictly finer than the old one - any
-- two rows COALESCE kept apart differ under it too, so the build cannot fail
-- on existing data.
ALTER TABLE agent_event_day_rollup
    ADD CONSTRAINT agent_event_day_rollup_key
    UNIQUE NULLS NOT DISTINCT (day, session_id, execution_id);

-- Serves the "did this session exist before the window" anti-join.
CREATE INDEX IF NOT EXISTS idx_rollup_session_day
    ON agent_event_day_rollup (session_id, day);

-- `day` is derived with the SAME expression the heatmap's queries used to
-- bucket with, so the rollup's days are the queries' days by construction.
CREATE OR REPLACE FUNCTION agent_event_day_rollup_apply() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO agent_event_day_rollup (day, session_id, execution_id, first_time, commits)
    VALUES (
        time_bucket('1 day', NEW.time)::date,
        NEW.session_id,
        NEW.execution_id,
        NEW.time,
        CASE WHEN NEW.event_type = 'git_commit' THEN 1 ELSE 0 END
    )
    ON CONFLICT ON CONSTRAINT agent_event_day_rollup_key DO UPDATE
    SET first_time = LEAST(agent_event_day_rollup.first_time, EXCLUDED.first_time),
        commits    = agent_event_day_rollup.commits + EXCLUDED.commits;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_events_day_rollup ON agent_events;
CREATE TRIGGER agent_events_day_rollup
    AFTER INSERT ON agent_events
    FOR EACH ROW EXECUTE FUNCTION agent_event_day_rollup_apply();

-- Backfill everything already stored. ON CONFLICT DO NOTHING makes re-running
-- this migration a no-op rather than a double count.
INSERT INTO agent_event_day_rollup (day, session_id, execution_id, first_time, commits)
SELECT
    time_bucket('1 day', time)::date,
    session_id,
    execution_id,
    MIN(time),
    COUNT(*) FILTER (WHERE event_type = 'git_commit')
FROM agent_events
GROUP BY 1, 2, 3
ON CONFLICT ON CONSTRAINT agent_event_day_rollup_key DO NOTHING;

COMMIT;

COMMENT ON TABLE agent_event_day_rollup IS
    'Per-(day, session, execution) rollup of agent_events, maintained by trigger. Bounds the contribution heatmap (#1253).';
