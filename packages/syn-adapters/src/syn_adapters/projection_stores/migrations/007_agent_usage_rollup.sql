-- Migration: 007_agent_usage_rollup
-- Description: Usage rollup behind GET /api/v1/metrics and the contribution
--              heatmap, maintained by a trigger on agent_events
-- Date: 2026-10-04
-- PR: #1558 (0.34 batch E1)

-- WHO RUNS THIS. A deployment that leaves SYN_SKIP_AUTO_CREATE_TABLES unset
-- never needs it: EventStoreSchema._create_usage_rollup()
-- (syn_adapters/events/schema.py) creates exactly these objects at API
-- startup, and that code is the definition. A deployment that SETS the flag -
-- its role holds no CREATE privilege and DDL is applied out of band - must
-- apply this file by hand BEFORE starting the version that reads the rollup.
-- Startup refuses to come up without it: EventStoreSchema.validate() fails if
-- a table or the trigger is absent, or if the backfill never completed,
-- because /metrics and the heatmap read the rollup unconditionally.
--
-- The statements below are rendered from the constants in schema.py, and
-- tests/events/test_schema_consistency.py fails if any of them stops matching.
-- Change schema.py first, then re-render this file.

-- INGEST IS NOT PAUSED FOR THE BACKFILL (#1558 review r2). Two transactions:
--
--   1. Tables and trigger. This holds agent_events (ACCESS EXCLUSIVE, which
--      DROP TRIGGER takes anyway, taken up front so the lock order cannot
--      deadlock with a concurrent insert), so inserts wait for it - but it
--      scans nothing, so the wait is milliseconds. From its COMMIT on, every
--      new event is counted by the trigger, into rows marked
--      backfilled = FALSE.
--   2. The backfill. Each INSERT writes (events) MINUS (the trigger's rows),
--      read in one statement and so one snapshot; an event and its trigger
--      row commit together, so whatever the trigger has counted is subtracted
--      and only the events it never saw remain. It takes no lock an insert
--      waits on, and replaces its own (backfilled = TRUE) rows, so re-running
--      this file converges rather than double-counting.
--
-- Run it with psql in autocommit (the default): the two halves must commit
-- separately. Startup does the same backfill in batches of sessions.

BEGIN;

-- USAGE_ROLLUP_SCHEMA_LOCK_KEY, the key _create_usage_rollup() takes, so a
-- by-hand run and an API startup queue rather than interleave.
SELECT pg_advisory_xact_lock(6319179922565843063);

-- agent_events before its chunks, so a concurrent insert cannot deadlock
-- with the trigger DDL below (AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL).
LOCK TABLE agent_events IN ACCESS EXCLUSIVE MODE;

CREATE TABLE IF NOT EXISTS agent_summary_usage (
    session_id            TEXT        NOT NULL,
    execution_id          TEXT,
    time                  TIMESTAMPTZ NOT NULL,
    model                 TEXT,
    requested_model       TEXT,
    has_requested_model   BOOLEAN     NOT NULL,
    vendor_cost_usd       NUMERIC,
    input_tokens          BIGINT      NOT NULL,
    output_tokens         BIGINT      NOT NULL,
    cache_creation_tokens BIGINT      NOT NULL,
    cache_read_tokens     BIGINT      NOT NULL,
    backfilled            BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_agent_summary_usage_session
ON agent_summary_usage (session_id);

CREATE INDEX IF NOT EXISTS idx_agent_summary_usage_execution
ON agent_summary_usage (execution_id);

CREATE TABLE IF NOT EXISTS agent_turn_usage_rollup (
    session_id            TEXT    NOT NULL,
    execution_id          TEXT,
    model                 TEXT,
    requested_model       TEXT,
    has_requested_model   BOOLEAN NOT NULL,
    input_tokens          BIGINT  NOT NULL,
    output_tokens         BIGINT  NOT NULL,
    cache_creation_tokens BIGINT  NOT NULL,
    cache_read_tokens     BIGINT  NOT NULL,
    observations          BIGINT  NOT NULL,
    backfilled            BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT agent_turn_usage_rollup_key UNIQUE NULLS NOT DISTINCT
        (session_id, execution_id, model, requested_model, has_requested_model, backfilled)
);

CREATE INDEX IF NOT EXISTS idx_agent_turn_usage_rollup_execution
ON agent_turn_usage_rollup (execution_id);

CREATE INDEX IF NOT EXISTS idx_agent_turn_usage_rollup_session
ON agent_turn_usage_rollup (session_id);

CREATE TABLE IF NOT EXISTS agent_usage_rollup_state (
    singleton     BOOLEAN     PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    backfilled_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE FUNCTION agent_usage_rollup_apply() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_type = 'session_summary' THEN
        INSERT INTO agent_summary_usage (session_id, execution_id, time, model, requested_model, has_requested_model, vendor_cost_usd, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)
        SELECT NEW.session_id, NEW.execution_id, NEW.time,
            
        NEW.data->>'model' as model, NEW.data->>'requested_model' as requested_model, (NEW.data ? 'requested_model') as has_requested_model,
        (NEW.data->>'total_cost_usd')::numeric AS vendor_cost_usd,
        COALESCE((NEW.data->>'total_input_tokens')::bigint, 0) AS input_tokens,
        COALESCE((NEW.data->>'total_output_tokens')::bigint, 0) AS output_tokens,
        COALESCE((NEW.data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
        COALESCE((NEW.data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens;
    ELSIF NEW.event_type = 'token_usage' THEN
        INSERT INTO agent_turn_usage_rollup (session_id, execution_id, model, requested_model, has_requested_model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, observations)
        SELECT NEW.session_id, NEW.execution_id,
            NEW.data->>'model' as model, NEW.data->>'requested_model' as requested_model, (NEW.data ? 'requested_model') as has_requested_model,
            
        COALESCE((NEW.data->>'input_tokens')::bigint, 0) AS input_tokens,
        COALESCE((NEW.data->>'output_tokens')::bigint, 0) AS output_tokens,
        COALESCE((NEW.data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
        COALESCE((NEW.data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens,
            1 AS observations
        ON CONFLICT ON CONSTRAINT agent_turn_usage_rollup_key DO UPDATE
        SET input_tokens = agent_turn_usage_rollup.input_tokens + EXCLUDED.input_tokens,
            output_tokens = agent_turn_usage_rollup.output_tokens + EXCLUDED.output_tokens,
            cache_creation_tokens =
                agent_turn_usage_rollup.cache_creation_tokens + EXCLUDED.cache_creation_tokens,
            cache_read_tokens =
                agent_turn_usage_rollup.cache_read_tokens + EXCLUDED.cache_read_tokens,
            observations = agent_turn_usage_rollup.observations + 1;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_events_usage_rollup ON agent_events;

CREATE TRIGGER agent_events_usage_rollup
    AFTER INSERT ON agent_events
    FOR EACH ROW EXECUTE FUNCTION agent_usage_rollup_apply();

-- Not complete until the backfill below commits.
DELETE FROM agent_usage_rollup_state;

COMMIT;

-- The backfill: no lock on agent_events beyond what a read takes.
BEGIN;

SELECT pg_advisory_xact_lock(6319179922565843063);

DELETE FROM agent_summary_usage WHERE backfilled AND TRUE;

DELETE FROM agent_turn_usage_rollup WHERE backfilled AND TRUE;

INSERT INTO agent_summary_usage (session_id, execution_id, time, model, requested_model, has_requested_model, vendor_cost_usd, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, backfilled)
SELECT session_id, execution_id, time, model, requested_model, has_requested_model, vendor_cost_usd, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, TRUE
FROM (
    SELECT session_id, execution_id, time, 
    data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
    (data->>'total_cost_usd')::numeric AS vendor_cost_usd,
    COALESCE((data->>'total_input_tokens')::bigint, 0) AS input_tokens,
    COALESCE((data->>'total_output_tokens')::bigint, 0) AS output_tokens,
    COALESCE((data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
    COALESCE((data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
    FROM agent_events
    WHERE event_type = 'session_summary' AND TRUE
    EXCEPT ALL
    SELECT session_id, execution_id, time, model, requested_model, has_requested_model, vendor_cost_usd, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens
    FROM agent_summary_usage
    WHERE NOT backfilled AND TRUE
) missed;

INSERT INTO agent_turn_usage_rollup (session_id, execution_id, model, requested_model, has_requested_model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, observations, backfilled)
SELECT e.session_id, e.execution_id, e.model, e.requested_model, e.has_requested_model,
    e.input_tokens - COALESCE(t.input_tokens, 0),
    e.output_tokens - COALESCE(t.output_tokens, 0),
    e.cache_creation_tokens - COALESCE(t.cache_creation_tokens, 0),
    e.cache_read_tokens - COALESCE(t.cache_read_tokens, 0),
    e.observations - COALESCE(t.observations, 0),
    TRUE
FROM (
    SELECT session_id, execution_id, data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
        SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
        SUM(cache_creation_tokens) AS cache_creation_tokens,
        SUM(cache_read_tokens) AS cache_read_tokens,
        COUNT(*) AS observations
    FROM (
        SELECT session_id, execution_id, data, 
    COALESCE((data->>'input_tokens')::bigint, 0) AS input_tokens,
    COALESCE((data->>'output_tokens')::bigint, 0) AS output_tokens,
    COALESCE((data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
    COALESCE((data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
        FROM agent_events
        WHERE event_type = 'token_usage' AND TRUE
    ) turns
    GROUP BY session_id, execution_id, data->>'model', data->>'requested_model', (data ? 'requested_model')
) e
LEFT JOIN agent_turn_usage_rollup t
  ON NOT t.backfilled
 AND t.session_id = e.session_id
 AND t.execution_id IS NOT DISTINCT FROM e.execution_id
 AND t.model IS NOT DISTINCT FROM e.model
 AND t.requested_model IS NOT DISTINCT FROM e.requested_model
 AND t.has_requested_model = e.has_requested_model
WHERE e.observations > COALESCE(t.observations, 0);

INSERT INTO agent_usage_rollup_state (singleton, backfilled_at) VALUES (TRUE, now())
ON CONFLICT (singleton) DO UPDATE SET backfilled_at = EXCLUDED.backfilled_at;

COMMIT;
