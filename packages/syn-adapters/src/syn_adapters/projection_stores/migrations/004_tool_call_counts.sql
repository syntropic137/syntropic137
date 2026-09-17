-- Migration: 004_tool_call_counts
-- Description: Tool-call tally read model, so the list endpoints stop counting
--              rows in the compressed agent_events hypertable on every request
-- Date: 2026-09-17
-- Issue: #1322

-- WHY. `/sessions` and `/executions` priced a page by running
--
--     SELECT session_id, COUNT(*) FROM agent_events
--     WHERE session_id = ANY($1) AND event_type = 'tool_execution_completed'
--     GROUP BY session_id
--
-- against a hypertable compressed with segmentby = session_id and
-- orderby = time. `event_type` is in neither, so inside a compressed chunk no
-- index can be consulted for it and every segment of every session on the page
-- is decompressed to evaluate the predicate. Measured at 219,140 rows: 60,562
-- buffer hits and 905ms for sixteen sessions. The tally below replaces that
-- with a point read of ~one row per session.
--
-- Definition, maintenance and readers all live in
-- packages/syn-domain/src/syn_domain/tool_call_counts.py. This file is the
-- hand-applied spelling of what EventStoreSchema.ensure_schema() creates
-- automatically on startup; both must stay in step.

CREATE TABLE IF NOT EXISTS agent_tool_call_counts (
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    tool_calls BIGINT NOT NULL,
    PRIMARY KEY (session_id, execution_id)
);

-- by_execution() filters on execution_id, which is the second key column and
-- so has no usable prefix in the primary key index.
CREATE INDEX IF NOT EXISTS idx_tool_call_counts_execution
ON agent_tool_call_counts (execution_id);

-- One-time backfill. This IS the definition of the tally: it may be re-run
-- against a truncated table at any time to check the maintained counts.
-- '' is how a row that carried no execution_id is keyed - the column is part of
-- the primary key and a key cannot be NULL.
INSERT INTO agent_tool_call_counts (session_id, execution_id, tool_calls)
SELECT session_id, COALESCE(execution_id, ''), COUNT(*)
FROM agent_events
WHERE event_type = 'tool_execution_completed'
GROUP BY session_id, COALESCE(execution_id, '')
ON CONFLICT (session_id, execution_id) DO UPDATE
SET tool_calls = EXCLUDED.tool_calls;

COMMENT ON TABLE agent_tool_call_counts IS
    'Tool calls per (session, execution), maintained incrementally as agent_events are written. See #1322.';
