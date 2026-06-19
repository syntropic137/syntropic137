# 2026-06-18 -- observability -- interactive-tmux OTel parity

## Question

Does interactive `claude` running inside a tmux workspace container export
OTLP metrics/logs to syn-collector (landing in `agent_events`) when
`CLAUDE_CODE_ENABLE_TELEMETRY=1` and `OTEL_EXPORTER_OTLP_ENDPOINT` are set and
the collector is reachable? In other words: is OTel observability parity with
the `claude -p` path a WIRING fix (env + network), or does it require the full
interactive event-capture arc (capture-pane scraping into events)?

Critical infra: observability is a hard requirement for syntropic137 workspaces
and gates the release. The interactive-tmux provider declares `otel_native:false`
and `otel_enabled:false`, and its `docker run` (driver/interactive_tmux.py:726-738)
passes only `-v` mounts, never the `-e` telemetry env that the `-p` path gets via
`_build_workspace_telemetry_env()` (apps/syn-api/.../_wiring.py:110). This probe
decides the size of the fix.

## Hypothesis (committed before any runs/ data)

- H1 (primary, confidence 70%): C1 (interactive claude WITH telemetry env) DOES
  export OTLP; at least 1 OTLP_* record lands in agent_events for the turn, of a
  type that also appears in C0. => OTel metrics parity is a wiring fix.
- H2 (90%): C1 produces 0 plugin-hook-channel events (the interactive image bakes
  no observability plugin). Full three-channel parity needs plugin injection too.
- H3 (95%): C2 (interactive, NO telemetry env = today's state) produces 0 records
  of any channel. Confirms the current interactive path is dark.
- H4 (85%): C3 (curl collector OTLP endpoint from inside C1's container) returns
  a 2xx/4xx HTTP status (route reachable). If H1 is false but H4 holds, the cause
  is the exporter not firing in interactive mode, NOT the network.
- C0 sanity (80%): the -p baseline yields >= 3 OTLP records, proving the pipeline
  (collector + agent_events) works end to end in this stack.

Falsification headline: if C1 yields 0 OTLP records AND C3 is reachable AND C0
works, then interactive claude does NOT export OTLP and parity requires the
event-capture arc (the larger fix). That miss is the high-value outcome.

## Setup

- Stack: live syn-dev-* dev stack on the VPS. syn-collector on docker network
  syn-dev_agent-net. agent_events in syn-db (TimescaleDB).
- Auth: mount the box ~/.claude (read-only) into each workspace container so the
  in-container claude authenticates as the box Max-plan OAuth and can complete a
  real turn. No operator token injection required.
- Image: agentic-workspace-interactive-tmux:2.1.126 (interactive path);
  claude-cli image (or claude -p directly) for C0.
- Telemetry env under test: CLAUDE_CODE_ENABLE_TELEMETRY=1,
  OTEL_EXPORTER_OTLP_ENDPOINT=http://syn-collector:<collector-otlp-port>.
  NOTE: dev .env has COLLECTOR_URL empty, so the run must set the endpoint
  explicitly; that emptiness is itself a finding to record.

## Conditions

- C0 baseline (known-good): claude -p with telemetry env -> collector. Establishes
  the pipeline works and the reference OTLP record types.
- C1 probe: interactive claude in the tmux workspace container, telemetry env
  injected, container joined to syn-dev_agent-net, ~/.claude mounted; drive ONE
  real turn via tmux send-keys; then check agent_events.
- C2 control: identical to C1 but WITHOUT the telemetry env (today's state).
- C3 network: from inside C1's container, curl the collector OTLP endpoint and
  record the HTTP status.

## The turn (frozen)

Prompt sent to the agent in C0/C1/C2: `What is 2+2? Reply with just the number.`
A condition only scores telemetry if the turn actually completed (the pane / -p
output shows the model answered). A turn that did not complete => that condition
is inconclusive (auth/transport confound), not a telemetry verdict.

## Expected signals

- agent_events row counts grouped by event_source / event_type, captured per
  condition within a fixed window (clear or timestamp-bound before each turn).
- The specific OTLP_* event types present (api_request, cost_recorded, session
  count, etc.).
- C3 HTTP status code.

## Out of scope

- codex / gemini telemetry (no OTLP export exists for them; their observability
  is a separate hook/capture question).
- The plugin-hook channel fix and the event-capture arc implementation (this
  probe only MEASURES whether they are needed, it does not build them).
- Performance / latency (covered by the separate scalability profiling pass).
