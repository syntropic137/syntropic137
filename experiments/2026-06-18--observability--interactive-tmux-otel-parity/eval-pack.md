# Eval pack (FROZEN at hypothesis commit)

Reproducible probe set. Connection details (DB creds, collector port) are
runtime-discovered; the conditions, the turn, and the scoring rule are frozen.

## Pre-flight (read-only, no telemetry)
P0. Discover: syn-db POSTGRES_USER/DB/PASSWORD (from `docker exec syn-collector env`
    or syn-db env or .env); the columns of agent_events that tag channel/source
    (event_source, event_type); the collector OTLP listen port (observability.mdx
    says :8080 with /v1/metrics + /v1/logs); confirm network syn-dev_agent-net.
P1. Record the baseline agent_events count and max(timestamp) so each condition
    can be measured as a delta after its turn.

## Conditions
C0 BASELINE (-p): start a claude container (claude-cli image or any image with
   claude) with -e CLAUDE_CODE_ENABLE_TELEMETRY=1 -e OTEL_EXPORTER_OTLP_ENDPOINT=
   http://syn-collector:<port>, joined to syn-dev_agent-net, ~/.claude mounted ro.
   Run `claude -p "What is 2+2? Reply with just the number."`. Confirm it answered.
   Wait <=20s for OTLP flush. Query agent_events for new OTLP_* rows since P1.
   Record count + types.

C1 PROBE (interactive + env): docker run -d the interactive-tmux image with the
   SAME telemetry env, joined to syn-dev_agent-net, ~/.claude mounted; the driver
   pattern is `... sleep infinity` then docker exec tmux new-session launching
   claude. Send the frozen turn via tmux send-keys; confirm the pane shows the
   answer. Wait <=20s. Query agent_events for new OTLP_* rows. Record count+types.

C2 CONTROL (interactive, no env): identical to C1 but OMIT the telemetry env.
   Drive the turn, confirm answered, query delta. Expect 0.

C3 NETWORK: from inside C1's container,
   `curl -s -o /dev/null -w '%{http_code}' -X POST http://syn-collector:<port>/v1/metrics`
   (or GET on a health/route). Record the status code.

## Scoring rule (frozen)
- H1 PASS iff C1 OTLP_* delta >= 1 with >=1 type shared with C0.
- H2 PASS iff C1 plugin-hook-channel delta == 0.
- H3 PASS iff C2 total delta == 0.
- H4 PASS iff C3 status is a real HTTP response (2xx or 4xx, not connection-refused/timeout).
- C0 sanity PASS iff C0 OTLP_* delta >= 3.

## Verdict mapping (frozen)
- go (parity = wiring fix): C0 sanity PASS and H1 PASS.
- no-go-for-now (needs event-capture arc): C0 sanity PASS and H1 FAIL and H4 PASS.
- inconclusive: any turn did not complete, or C0 sanity FAIL (pipeline broken),
  or C3 unreachable in a way that masks H1.

## Cleanup (mandatory)
Name all probe containers otelprobe-*; trap-remove on exit
(`docker ps -aq --filter name=otelprobe- | xargs -r docker rm -f`).
Never touch syn-* or scaleprobe-* containers.
