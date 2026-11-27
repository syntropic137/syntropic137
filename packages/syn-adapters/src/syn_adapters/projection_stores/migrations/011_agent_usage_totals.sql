-- Migration: 011_agent_usage_totals
-- Description: ADR-079 part 1: agent_turn_usage_rollup.reported_observations,
--              the turns that reported tokens, kept by the usage rollup's
--              trigger and backfill
-- Date: 2026-11-27
-- PR: #2387 (issue #2383)

-- WHO RUNS THIS. As for 007: a deployment that leaves
-- SYN_SKIP_AUTO_CREATE_TABLES unset never needs it, because
-- EventStoreSchema._create_usage_rollup() (syn_adapters/events/schema.py)
-- adds the column, replaces the trigger function and backfills at startup.
-- A deployment that SETS the flag applies 007 first, then this file.
--
-- The statements below are rendered from the constants in schema.py, and
-- tests/events/test_schema_consistency.py fails if any of them stops matching.
-- Change schema.py first, then re-render this file. They supersede 007's
-- trigger function and backfill; 007 is kept as it shipped.
--
-- WHY THE BACKFILL RUNS AGAIN. The column arrives at 0 on every existing row,
-- and the rows the old trigger wrote balance on observations, so only a
-- backfill whose keep condition also compares reported_observations can fill
-- them. Same two transactions as 007, for the same reason: the first holds
-- agent_events for milliseconds and scans nothing; the second holds no lock
-- an insert waits on, and converges if re-run.
--
-- Part 1 of 011. ADR-079's canonical tier is appended in a later slice.
--
-- Run it with psql in autocommit (the default): the two halves must commit
-- separately.

BEGIN;

-- USAGE_ROLLUP_SCHEMA_LOCK_KEY, the key _create_usage_rollup() takes.
SELECT pg_advisory_xact_lock(6319179922565843063);

-- agent_events before its chunks (AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL).
LOCK TABLE agent_events IN ACCESS EXCLUSIVE MODE;

ALTER TABLE agent_turn_usage_rollup
ADD COLUMN IF NOT EXISTS reported_observations BIGINT NOT NULL DEFAULT 0;

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
        INSERT INTO agent_turn_usage_rollup (session_id, execution_id, model, requested_model, has_requested_model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, observations, reported_observations)
        SELECT NEW.session_id, NEW.execution_id,
            NEW.data->>'model' as model, NEW.data->>'requested_model' as requested_model, (NEW.data ? 'requested_model') as has_requested_model,

        COALESCE((NEW.data->>'input_tokens')::bigint, 0) AS input_tokens,
        COALESCE((NEW.data->>'output_tokens')::bigint, 0) AS output_tokens,
        COALESCE((NEW.data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
        COALESCE((NEW.data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens,
            1 AS observations,
            CASE WHEN ((COALESCE((NEW.data->>'input_tokens')::bigint, 0) + COALESCE((NEW.data->>'output_tokens')::bigint, 0) + COALESCE((NEW.data->>'cache_creation_tokens')::bigint, 0) + COALESCE((NEW.data->>'cache_read_tokens')::bigint, 0)) = 0) THEN 0 ELSE 1 END
        ON CONFLICT ON CONSTRAINT agent_turn_usage_rollup_key DO UPDATE
        SET input_tokens = agent_turn_usage_rollup.input_tokens + EXCLUDED.input_tokens,
            output_tokens = agent_turn_usage_rollup.output_tokens + EXCLUDED.output_tokens,
            cache_creation_tokens =
                agent_turn_usage_rollup.cache_creation_tokens + EXCLUDED.cache_creation_tokens,
            cache_read_tokens =
                agent_turn_usage_rollup.cache_read_tokens + EXCLUDED.cache_read_tokens,
            observations = agent_turn_usage_rollup.observations + 1,
            reported_observations =
                agent_turn_usage_rollup.reported_observations + EXCLUDED.reported_observations;
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

INSERT INTO agent_turn_usage_rollup (session_id, execution_id, model, requested_model, has_requested_model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, observations, reported_observations, backfilled)
SELECT e.session_id, e.execution_id, e.model, e.requested_model, e.has_requested_model,
    e.input_tokens - COALESCE(t.input_tokens, 0),
    e.output_tokens - COALESCE(t.output_tokens, 0),
    e.cache_creation_tokens - COALESCE(t.cache_creation_tokens, 0),
    e.cache_read_tokens - COALESCE(t.cache_read_tokens, 0),
    e.observations - COALESCE(t.observations, 0),
    e.reported_observations - COALESCE(t.reported_observations, 0),
    TRUE
FROM (
    SELECT session_id, execution_id, data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
        SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
        SUM(cache_creation_tokens) AS cache_creation_tokens,
        SUM(cache_read_tokens) AS cache_read_tokens,
        COUNT(*) AS observations,
        COUNT(*) FILTER (WHERE NOT ((COALESCE((data->>'input_tokens')::bigint, 0) + COALESCE((data->>'output_tokens')::bigint, 0) + COALESCE((data->>'cache_creation_tokens')::bigint, 0) + COALESCE((data->>'cache_read_tokens')::bigint, 0)) = 0)) AS reported_observations
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
WHERE e.observations > COALESCE(t.observations, 0)
   OR e.reported_observations > COALESCE(t.reported_observations, 0);

INSERT INTO agent_usage_rollup_state (singleton, backfilled_at) VALUES (TRUE, now())
ON CONFLICT (singleton) DO UPDATE SET backfilled_at = EXCLUDED.backfilled_at;

COMMIT;
