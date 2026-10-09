# ADR-073: Durable Request Latency Telemetry

- **Status**: Accepted
- **Date**: 2026-10-08
- **Issue**: #1811 (the evals list took 24.5 s and nothing recorded it), #1070, #1583
- **Related**: ADR-029 (agent events in TimescaleDB), ADR-030 (one observability database), ADR-057 (degradable services)

## Context

The API knew its own latency only in memory. `RequestTimingAggregator` (#1070)
keeps the last 500 durations per route and is lost on restart; the slow-request
log (#1583) names one request at a time. Neither answers "what was the p99 of
`GET /evals` last week, and did the fix move it?". #1811 was found by a person
timing `curl`, which is the failure this ADR closes.

## Decision

Every API request is recorded, durably, in the observability database.

### What is recorded

One row per request in `api_request_latency`:

| Column | Meaning |
|---|---|
| `time` | When the request arrived (UTC) |
| `method` | HTTP method |
| `route` | The matched route TEMPLATE (`/evals/{eval_id}`), or `<unmatched>` |
| `status` | Status sent; 500 when the handler raised before responding |
| `duration_ms` | Arrival to response START, so a long-lived SSE stream that answered promptly is not slow |
| `request_id` | A fresh id per request, returned as `x-request-id` and named on the slow-request log line |

### What is NOT recorded

The raw path, the query string, headers, cookies, the request or response
body, the caller's identity and any auth material. Ids in a path and tokens in
a query pass through this middleware; only the template leaves it. An incoming
`x-request-id` is not trusted or stored: the id is always minted here.

### How it is written

`RequestTimingMiddleware` builds a sample and calls
`RequestLatencyRecorder.offer`, which appends to a bounded in-memory buffer
(10,000) and returns: no I/O and no await on the request path. A background
task drains it with one `COPY` per batch of up to 500, every second or as soon
as a batch fills. Backpressure drops, never blocks: a sample offered while the
buffer is full, or while the recorder is not running, is counted in `dropped`;
a batch whose write fails is counted in `write_failures` and not retried.
Shutdown flushes once before the pool closes. Measured overhead in-process is
about 6 us per request (`test_adr073_request_latency.py` asserts < 1 ms).

Recording is best-effort (ADR-057 spirit): if the table cannot be readied the
API serves anyway and every sample is a counted drop.

### Retention

`api_request_latency` is a TimescaleDB hypertable with one-day chunks and a
30-day retention policy, so old data leaves a whole chunk at a time. DDL runs
at startup unless `SYN_SKIP_AUTO_CREATE_TABLES` says the migrations own it, the
same policy as `agent_events`.

### How p99 is computed

Exactly. `GET /observability/latency?window=1h|24h|7d|30d&route=` runs
`percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY duration_ms)`
over every row in the window, grouped by (method, route), with count and max.
No t-digest or sketch: at this API's volume (a few requests a second, 30 days
is single-digit millions of rows) a sort per route is cheap, and an exact
answer cannot disagree with a raw-row spot check. When a 30-day read stops
being cheap, add a daily rollup (a continuous aggregate of
`percentile_agg` from timescaledb_toolkit, or a table written by a daily job)
and serve windows longer than a day from it; this ADR is updated in place then.

`syn insights latency [--window 7d] [--route /evals]` prints the same table.

### Why Lane 2

Latency is telemetry about the process, not a domain fact. No aggregate
decides anything from it, it is never replayed to rebuild state, and losing a
sample loses nothing the domain needs. So it is written straight to the
observability store, never through the event store or an aggregate, exactly as
token and tool telemetry are (CLAUDE.md, Two-Lane Architecture).

## Consequences

- Every claim like "the evals list is fast now" can be checked against a p99
  over a window instead of a single `curl`.
- `recorder` in the response describes only the process that answered; with
  several API processes each reports its own drops.
- The in-memory `RequestTimingAggregator` stays for now; it is superseded in
  use by this table and can be deleted once nothing reads it.
- Not covered: within-request breakdown (DB vs handler vs serialization) and a
  dashboard panel. Both read this table when they are built.
