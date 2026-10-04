-- Migration: 008_day_rollup_execution_index
-- Description: Index the day rollup by execution, so execution-keyed reads of
--              agent_events can be bounded to the days that hold their rows
-- Date: 2026-10-04
-- PR: 0.34 batch E2 (executions, sessions and artifacts read in milliseconds)

-- WHO RUNS THIS. A deployment that leaves SYN_SKIP_AUTO_CREATE_TABLES unset
-- never needs it: EventStoreSchema._create_day_rollup()
-- (syn_adapters/events/schema.py) creates the index at API startup. A
-- deployment that sets the flag should apply it before starting E2; without it
-- every span lookup by execution is a sequential scan of the rollup, which is
-- slower but returns the same answer.
--
-- WHY. syn_domain.agent_event_span reads MIN(day), MAX(day) for a set of ids
-- from agent_event_day_rollup and bounds the hypertable read to those days,
-- which lets the planner exclude every other chunk. The session half is served
-- by idx_rollup_session_day (005); this is the execution half.
--
-- CONCURRENTLY, so applying it by hand never blocks ingestion: the trigger on
-- agent_events writes this table on every insert. It cannot run inside a
-- transaction block; run it with psql in autocommit (the default).

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rollup_execution_day
    ON agent_event_day_rollup (execution_id, day);
