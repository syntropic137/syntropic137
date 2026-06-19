# Results

Headline table (each row cites a runs/ artifact):

| Condition | OTLP_* delta | types | hook delta | turn completed? | evidence |
|---|---|---|---|---|---|
| C0 baseline | 0 | none | - | yes, answer `4` | `runs/c0-claude-answer.txt`, `runs/c0-exit-status.txt`, `runs/c0-before.tsv`, `runs/c0-after-delta.tsv` |
| C1 probe | 0 | none | 0 | no, stalled at workspace trust prompt | `runs/c1-pane-final.txt`, `runs/c1-turn-completed.txt`, `runs/c1-before.tsv`, `runs/c1-after-delta.tsv` |
| C2 control | 0 | none | 0 | no, stalled at workspace trust prompt | `runs/c2-pane-final.txt`, `runs/c2-turn-completed.txt`, `runs/c2-before.tsv`, `runs/c2-after-delta.tsv` |
| C3 network | HTTP 200 | - | - | - | `runs/c3-http-code.txt`, `runs/c3-curl-exit-status.txt` |

## Pre-flight

- Collector container was reachable on the Docker network `syn-dev_agent-net`; `docker ps` shows `syn-collector` publishing `8080/tcp`. Evidence: `runs/preflight-docker-ps.txt`.
- Collector DB config was `SYN_OBSERVABILITY_DB_URL=postgres://syn:syn_dev_password@timescaledb:5432/syn`. Evidence: `runs/preflight-syn-collector-env.txt`.
- `agent_events` has `time`, `event_type`, `session_id`, `execution_id`, `phase_id`, and `data`; there is no separate `event_source` column in this stack. Evidence: `runs/preflight-agent-events-current.tsv` and the run-time DB queries.
- Probe image user is `agent`, with `HOME=/home/agent`, and the image contains `claude`, `tmux`, and `curl`. Evidence: `runs/preflight-image-inspect.txt`.

## Per-condition detail

### C0 baseline

- Command path: `claude -p 'What is 2+2? Reply with just the number.'`
- Auth/config mounted read-only into `/home/agent`: `/home/ubuntu/.claude` and `/home/ubuntu/.claude.json`.
- Turn completed: yes. `runs/c0-claude-answer.txt` contains `4`; `runs/c0-exit-status.txt` contains `0`.
- Before snapshot: `31`, max time `2026-06-16 22:14:55.635253+00`. Evidence: `runs/c0-before.tsv`.
- After 20 second flush, total delta was `0`; no `OTLP_*` types were present. Evidence: `runs/c0-after-delta.tsv`.

### C1 probe

- Image: `agentic-workspace-interactive-tmux:2.1.126`.
- Env: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://syn-collector:8080`. Evidence: `runs/c1-container-inspect.txt`.
- Network: `syn-dev_agent-net`.
- Auth/config mounted read-only into `/home/agent`: `/home/ubuntu/.claude` and `/home/ubuntu/.claude.json`.
- Turn completed: no. The final pane remained at the workspace trust confirmation screen and no model answer appeared within the 90 second polling window. Evidence: `runs/c1-pane-final.txt`, `runs/c1-turn-completed.txt`, `runs/c1-poll-log.txt`.
- After 20 second flush, total delta was `0`; no `OTLP_*` types were present. Because the turn did not complete, this condition does not score a telemetry verdict. Evidence: `runs/c1-after-delta.tsv`.

### C2 control

- Image and network matched C1, but telemetry env was omitted. Evidence: `runs/c2-container-inspect.txt`.
- Auth/config mounted read-only into `/home/agent`: `/home/ubuntu/.claude` and `/home/ubuntu/.claude.json`.
- Turn completed: no. The final pane remained at the workspace trust confirmation screen and no model answer appeared within the 90 second polling window. Evidence: `runs/c2-pane-final.txt`, `runs/c2-turn-completed.txt`, `runs/c2-poll-log.txt`.
- After 20 second flush, total delta was `0`; no `OTLP_*` types were present. Because the turn did not complete, this condition does not score telemetry. Evidence: `runs/c2-after-delta.tsv`.

### C3 network

- From inside C1, `POST http://syn-collector:8080/v1/metrics` returned HTTP `200`.
- Curl exit status was `0`.
- Evidence: `runs/c3-http-code.txt`, `runs/c3-curl-exit-status.txt`.

## Confounds captured

- Initial C1/C2 attempts with only `/home/ubuntu/.claude` mounted stalled at Claude login/onboarding. Evidence: `runs/auth-mount-rerun-note.txt` and `runs/c1-trustprompt-initial-authconfound-*`, `runs/c2-trustprompt-initial-authconfound-*`.
- Reruns with `/home/ubuntu/.claude.json` also mounted got past auth/config but stalled at the workspace trust prompt. Evidence: `runs/trust-prompt-rerun-note.txt` and `runs/c1-trustprompt-*`, `runs/c2-trustprompt-*`.
