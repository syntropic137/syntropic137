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
-- either table or the trigger is absent, because /metrics and the heatmap read
-- both unconditionally and would otherwise answer 503 on every request.
--
-- The statements below are rendered from the constants in schema.py, and
-- tests/events/test_schema_consistency.py fails if any of them stops matching.
-- Change schema.py first, then re-render this file.

-- WHY IT IS SAFE TO BACKFILL HERE, unlike 004. 004 cannot backfill because the
-- old application, still serving while a migration runs, does not maintain
-- that tally. This rollup is maintained by the DATABASE: the trigger is
-- created first, in the same transaction as the backfill, and CREATE TRIGGER
-- takes SHARE ROW EXCLUSIVE on agent_events, so concurrent inserts wait for
-- the COMMIT and are then counted by the trigger. The backfill sees exactly the
-- rows the trigger did not. Ingest pauses for one scan of the two usage event
-- types - plan the deploy for it.
--
-- Re-running converges: the backfill deletes and recomputes both tables from
-- agent_events rather than adding to them.

BEGIN;

-- USAGE_ROLLUP_SCHEMA_LOCK_KEY, the key _create_usage_rollup() takes, so a
-- by-hand run and an API startup queue rather than interleave.
SELECT pg_advisory_xact_lock(6319179922565843063);

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
    cache_read_tokens     BIGINT      NOT NULL
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
    CONSTRAINT agent_turn_usage_rollup_key UNIQUE NULLS NOT DISTINCT
        (session_id, execution_id, model, requested_model, has_requested_model)
);

CREATE INDEX IF NOT EXISTS idx_agent_turn_usage_rollup_execution
ON agent_turn_usage_rollup (execution_id);

CREATE INDEX IF NOT EXISTS idx_agent_turn_usage_rollup_session
ON agent_turn_usage_rollup (session_id);

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
        INSERT INTO agent_turn_usage_rollup (session_id, execution_id, model, requested_model, has_requested_model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)
        SELECT NEW.session_id, NEW.execution_id,
            NEW.data->>'model' as model, NEW.data->>'requested_model' as requested_model, (NEW.data ? 'requested_model') as has_requested_model,

        COALESCE((NEW.data->>'input_tokens')::bigint, 0) AS input_tokens,
        COALESCE((NEW.data->>'output_tokens')::bigint, 0) AS output_tokens,
        COALESCE((NEW.data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
        COALESCE((NEW.data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
        ON CONFLICT ON CONSTRAINT agent_turn_usage_rollup_key DO UPDATE
        SET input_tokens = agent_turn_usage_rollup.input_tokens + EXCLUDED.input_tokens,
            output_tokens = agent_turn_usage_rollup.output_tokens + EXCLUDED.output_tokens,
            cache_creation_tokens =
                agent_turn_usage_rollup.cache_creation_tokens + EXCLUDED.cache_creation_tokens,
            cache_read_tokens =
                agent_turn_usage_rollup.cache_read_tokens + EXCLUDED.cache_read_tokens;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_events_usage_rollup ON agent_events;

CREATE TRIGGER agent_events_usage_rollup
    AFTER INSERT ON agent_events
    FOR EACH ROW EXECUTE FUNCTION agent_usage_rollup_apply();

DELETE FROM agent_summary_usage;

DELETE FROM agent_turn_usage_rollup;

INSERT INTO agent_summary_usage (session_id, execution_id, time, model, requested_model, has_requested_model, vendor_cost_usd, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)
SELECT session_id, execution_id, time,
    data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
    (data->>'total_cost_usd')::numeric AS vendor_cost_usd,
    COALESCE((data->>'total_input_tokens')::bigint, 0) AS input_tokens,
    COALESCE((data->>'total_output_tokens')::bigint, 0) AS output_tokens,
    COALESCE((data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
    COALESCE((data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
FROM agent_events
WHERE event_type = 'session_summary';

INSERT INTO agent_turn_usage_rollup (session_id, execution_id, model, requested_model, has_requested_model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)
SELECT session_id, execution_id, data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
    SUM(input_tokens), SUM(output_tokens),
    SUM(cache_creation_tokens), SUM(cache_read_tokens)
FROM (
    SELECT session_id, execution_id, data,
    COALESCE((data->>'input_tokens')::bigint, 0) AS input_tokens,
    COALESCE((data->>'output_tokens')::bigint, 0) AS output_tokens,
    COALESCE((data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
    COALESCE((data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
    FROM agent_events
    WHERE event_type = 'token_usage'
) turns
GROUP BY session_id, execution_id, data->>'model', data->>'requested_model', (data ? 'requested_model');

COMMIT;
