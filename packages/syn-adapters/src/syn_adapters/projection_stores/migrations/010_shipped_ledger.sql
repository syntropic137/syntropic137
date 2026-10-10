-- Migration: 010_shipped_ledger
-- Description: The shipped ledger (facts) and its daily rollup, Lane 2, for
--              GET /metrics/shipped ("Shipped by agents")
-- Date: 2026-10-10
-- PR: #1857

-- WHO RUNS THIS. Nothing in this repository: there is no migration runner for
-- this directory, these files document DDL. A deployment that leaves
-- SYN_SKIP_AUTO_CREATE_TABLES unset never needs it: the API applies the same
-- numbered steps at startup (syn_adapters/events/shipped_ledger.py,
-- MIGRATIONS, recorded in shipped_ledger_meta.schema_version). A deployment
-- that SETS the flag must apply this file to the observability database
-- (SYN_OBSERVABILITY_DB_URL) itself and then set
-- shipped_ledger_meta.schema_version to 1; until it does, the API serves
-- normally, ledger writes fail and are logged (never raised into a phase),
-- and GET /metrics/shipped answers 503.
--
-- FACTS ARE NEVER RESET. shipped_commits, shipped_pull_requests,
-- github_pull_request_merges and github_repository_aliases are the record;
-- merges have no other source. Changes to them are new numbered steps here and
-- in MIGRATIONS, forward only. shipped_daily is derived: the API rebuilds it
-- from the facts whenever ROLLUP_VERSION changes.
--
-- MUST MATCH syn_adapters/events/shipped_ledger.py (_META and MIGRATIONS[1]).

CREATE TABLE IF NOT EXISTS shipped_ledger_meta (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    schema_version INT NOT NULL DEFAULT 0,
    rollup_version INT NOT NULL DEFAULT 0,
    backfill_version INT NOT NULL DEFAULT 0,
    backfill_cursor TEXT,
    backfill_sessions_walked BOOLEAN NOT NULL DEFAULT FALSE,
    backfill_done_at TIMESTAMPTZ
);
INSERT INTO shipped_ledger_meta (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS shipped_commits (
    sha TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    repository TEXT NOT NULL,
    repository_key TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    day DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_shipped_commits_rollup
    ON shipped_commits (day, repository_key, workflow_id);

CREATE TABLE IF NOT EXISTS shipped_pull_requests (
    repository_key TEXT NOT NULL,
    number INT NOT NULL,
    repository TEXT NOT NULL,
    url TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    opened_day DATE NOT NULL,
    merged_at TIMESTAMPTZ,
    merged_day DATE,
    PRIMARY KEY (repository_key, number)
);
CREATE INDEX IF NOT EXISTS ix_shipped_prs_opened
    ON shipped_pull_requests (opened_day, repository_key, workflow_id);
CREATE INDEX IF NOT EXISTS ix_shipped_prs_merged
    ON shipped_pull_requests (merged_day, repository_key, workflow_id);
CREATE INDEX IF NOT EXISTS ix_shipped_prs_number ON shipped_pull_requests (number);

CREATE TABLE IF NOT EXISTS github_pull_request_merges (
    repository_key TEXT NOT NULL,
    number INT NOT NULL,
    repository TEXT NOT NULL,
    repository_id BIGINT,
    merged_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (repository_key, number)
);
CREATE INDEX IF NOT EXISTS ix_merges_number ON github_pull_request_merges (number);

CREATE TABLE IF NOT EXISTS github_repository_aliases (
    repository_key TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    repository_id BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_aliases_id ON github_repository_aliases (repository_id);

CREATE TABLE IF NOT EXISTS shipped_daily (
    day DATE NOT NULL,
    repository_key TEXT NOT NULL,
    repository TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL DEFAULT '',
    commits INT NOT NULL DEFAULT 0,
    prs_opened INT NOT NULL DEFAULT 0,
    prs_merged INT NOT NULL DEFAULT 0,
    prs_opened_merged INT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, repository_key, workflow_id)
);

CREATE TABLE IF NOT EXISTS shipped_backfill_pending (
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    abandoned BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (session_id, execution_id)
);

UPDATE shipped_ledger_meta SET schema_version = 1 WHERE schema_version < 1;
