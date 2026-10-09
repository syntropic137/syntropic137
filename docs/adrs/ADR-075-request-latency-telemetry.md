# ADR-075: Durable Request Latency Telemetry

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

`RequestTimingMiddleware` wraps the app's WHOLE middleware stack, including
Starlette's `ServerErrorMiddleware` (`_TimedFastAPI.build_middleware_stack`).
So a startup-gate 503, a workspace-ingress refusal and the framework's own 500
(a custom exception handler's body and headers, or the debug traceback) are
observed, recorded and stamped with `x-request-id`, never replaced. At
response START it builds a sample, sets `x-request-id` (replacing any the app
set) and calls `RequestLatencyRecorder.offer`. A long-lived stream is
therefore recorded when it answered, not when it closed. Only if nothing was
sent at all does it synthesize a 500, and a sample is then offered when the
request ends. A recorder that raises is logged and ignored, so telemetry never
fails a request and never masks the application's exception.

`offer` appends to a bounded in-memory buffer (10,000) and returns: no I/O and
no await on the request path. A background task drains it with one `COPY` per
batch of up to 500, every second or as soon as a batch fills. Backpressure
drops, never blocks. Every loss is counted in `GET /observability/latency`:

| Counter | Meaning |
|---|---|
| `dropped` | Offered while the buffer was full or the recorder was not running |
| `write_failures` | In a batch that failed or overran `REQUEST_LATENCY_IO_TIMEOUT_S` |
| `discarded` | Still buffered or mid-write (not confirmed written) when `REQUEST_LATENCY_SHUTDOWN_TIMEOUT_S` expired |
| `cleanup_failures` | Batches that WERE written (and counted in `written`) whose connection could not be released in time and was terminated |

Every database step has a deadline from settings, never a literal, and the
steps are separate because `async with pool.acquire()` cannot be bounded:
asyncpg shields the release (and the connection reset inside it) from
cancellation and gives it no timeout, so a stalled reset outlives any timeout
around the block and later holds up `pool.close()`. `run_bounded` therefore
calls `pool.acquire(timeout=)`, runs the operation under `wait_for`, and
releases with `pool.release(conn, timeout=)` under `wait_for`; on any overrun
or cancellation the connection is terminated, so the pending release sees it
closed and finishes at once.
`request_latency_io_timeout_s` (default 5 s) bounds connection acquisition, each
batch write and each attempt to ready the table.
`request_latency_shutdown_timeout_s` (default 10 s) bounds the final flush. A
stalled database can lose samples, counted, but cannot hold up a request, a
startup or a shutdown. Failed batches are not retried.

Readying the table never blocks startup. A supervised background task retries
it with exponential backoff (1 s doubling to 60 s) until it succeeds, so a
database that is slow or down at boot delays recording instead of disabling it
until the next restart. Measured overhead in-process is about 6 us per request
(`test_adr075_request_latency.py` asserts < 1 ms).

### Retention

`api_request_latency` is a TimescaleDB hypertable with one-day chunks and a
30-day retention policy, so old data leaves a whole chunk at a time.

### Provisioning

DDL runs at API startup unless `SYN_SKIP_AUTO_CREATE_TABLES` is set, the same
policy as `agent_events`. **There is no migration runner.**
`projection_stores/migrations/009_api_request_latency.sql` documents the DDL
and nothing applies it. A deployment that sets the flag must apply that file
to the observability database itself. Until then the API serves normally,
records nothing, reports every sample as `dropped`, and logs a warning on each
retry. The deploy notes say the same.

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

`syn observability latency [--window 7d] [--route /evals]` prints the same table.
Request latency is **Observability**, not an Insight: see
`docs/architecture/agent_sessions-ubiquitous-language.md` (Observability) and
`docs/architecture/organization-ubiquitous-language.md` (Words we do NOT use).

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
