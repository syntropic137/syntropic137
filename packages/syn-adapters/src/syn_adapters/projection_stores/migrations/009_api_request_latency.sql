-- Migration: 009_api_request_latency
-- Description: Per-request API latency, Lane 2 telemetry (ADR-075)
-- Date: 2026-10-08
-- PR: #1816

-- WHO RUNS THIS. Nothing in this repository: there is no migration runner for
-- this directory, these files document DDL. A deployment that leaves
-- SYN_SKIP_AUTO_CREATE_TABLES unset never needs it: the API creates the table
-- at startup (syn_adapters/request_latency/schema.py, retried in the
-- background until it succeeds). A deployment that SETS the flag must apply
-- this file to the observability database (SYN_OBSERVABILITY_DB_URL) itself;
-- until it does, the API serves normally, records nothing, counts every sample
-- as dropped in GET /observability/latency, and logs a warning on each retry.
--
-- MUST MATCH syn_adapters/request_latency/schema.py.

CREATE TABLE IF NOT EXISTS api_request_latency (
    time TIMESTAMPTZ NOT NULL,
    method TEXT NOT NULL,
    route TEXT NOT NULL,
    status SMALLINT NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL,
    request_id TEXT NOT NULL
);

SELECT create_hypertable(
    'api_request_latency', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS ix_api_request_latency_route_time
    ON api_request_latency (route, time DESC);

SELECT add_retention_policy('api_request_latency', INTERVAL '30 days', if_not_exists => TRUE);
