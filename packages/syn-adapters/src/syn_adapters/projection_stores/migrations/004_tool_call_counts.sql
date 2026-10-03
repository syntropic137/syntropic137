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
-- hand-applied spelling of the DDL that module auto-creates when a deployment
-- has not set SYN_SKIP_AUTO_CREATE_TABLES; both must stay in step.

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

-- The version stamp. One row, and the schema is what enforces that rather
-- than the discipline of everyone who writes it.
CREATE TABLE IF NOT EXISTS agent_tool_call_counts_version (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    rebuilt_version INTEGER NOT NULL
);

-- THIS MIGRATION DELIBERATELY DOES NOT BACKFILL, and left to itself that is
-- the wrong instinct, so here is the reason.
--
-- A migration runs against a live database while the PREVIOUS version of the
-- application is still serving. That version does not maintain this tally -
-- it is the version being replaced precisely because it does not. Every
-- tool_execution_completed row it appends between this file running and the
-- new binary's first breath is in agent_events and absent from a table
-- backfilled here.
--
-- The result is a tally that is populated, plausible and short. Nothing about
-- the rows says so; "does it have rows in it" is the one question that cannot
-- distinguish it from a correct one, and it is the question a startup check is
-- most tempted to ask. Undercounting, permanently, with no blank table and no
-- log line.
--
-- So the rows are not this file's to write. agent_tool_call_counts_version is
-- left EMPTY, which is what an unreconstructed tally looks like, and the first
-- startup of the new application recounts from agent_events, stamps its
-- definition version, and is cheap on every startup after. A migration cannot
-- write that stamp because a migration is not a writer that maintains these
-- counts, and the stamp means exactly that one thing.
--
-- See tool_call_counts.ensure_ready() / rebuild(). To force a recount by hand:
--     uv run python scripts/backfill/rebuild_tool_call_counts.py --apply

COMMENT ON TABLE agent_tool_call_counts IS
    'Tool calls per (session, execution), maintained incrementally as agent_events are written. See #1322.';

COMMENT ON TABLE agent_tool_call_counts_version IS
    'Definition version the tally was last reconstructed to. Written only by tool_call_counts.rebuild(). See #1322.';
