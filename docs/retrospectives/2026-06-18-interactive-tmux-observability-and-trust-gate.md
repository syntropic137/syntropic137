# 2026-06-18 interactive-tmux observability and trust-gate

Status: verdict inconclusive, but two release-gating findings established.
Experiment: experiments/2026-06-18--observability--interactive-tmux-otel-parity/
Commits: b6038b86 (hypothesis), 2ca5751f (run, inconclusive).
Sibling evidence: ~/swarm-tasks/tmux-scale-findings.md (scalability profiling).

## Why we ran it

Observability is a hard requirement for syntropic137 workspaces and gates the
release of the interactive-tmux integration. The provider declares
otel_native:false / otel_enabled:false, and its docker run injects only -v
mounts, never the -e telemetry env the claude -p path gets via
_build_workspace_telemetry_env (apps/syn-api/.../_wiring.py:110). The question:
is OTel parity a wiring fix (env + network) or does it need the interactive
event-capture arc? The answer sizes the fix and the release timeline.

## What happened

Verdict: inconclusive, under the frozen mapping. Two independent blockers
prevented a clean telemetry verdict, and each is itself a finding.

1. The claude -p BASELINE produced zero OTLP rows. C0 completed a real turn
   (answered "4") with CLAUDE_CODE_ENABLE_TELEMETRY=1 +
   OTEL_EXPORTER_OTLP_ENDPOINT=http://syn-collector:8080, collector reachable
   (C3 returned HTTP 200), yet agent_events gained zero rows in the 20s flush
   window. The predicted "C0 >= 3 OTLP" was WRONG. We cannot currently
   demonstrate OTel landing even from the supposedly-native path in this stack.

2. The INTERACTIVE turns never completed. C1 and C2 both stalled at the Claude
   Code workspace trust prompt ("Is this a project you trust? > 1. Yes"), after
   first stalling at first-run onboarding when only .claude (not .claude.json)
   was mounted. No unattended interactive turn can complete until that gate is
   cleared. The -p path does not hit this gate.

C3 (collector reachability from inside the workspace container) passed: HTTP 200.
So the network is not the blocker.

## The miss is the headline

The hypothesis assumed a working -p OTel baseline as the comparative anchor.
That anchor did not hold (C0 = 0 OTLP). Likely causes, in order:
- The dev stack ships observability OFF: COLLECTOR_URL is empty in .env, so the
  normal path injects no telemetry env at all; the experiment set the endpoint
  by hand but the stack was never wired to expect it.
- The env set was incomplete. Claude Code OTLP export typically also needs
  OTEL_METRICS_EXPORTER=otlp, OTEL_LOGS_EXPORTER=otlp,
  OTEL_EXPORTER_OTLP_PROTOCOL=http/json, and a short OTEL_METRIC_EXPORT_INTERVAL
  (default export interval is ~60s, far longer than the 20s flush window used).
- Possible record-shape / event_type mismatch in the query, though the TOTAL
  delta (not just OTLP_*) was zero, which points at "nothing exported/persisted"
  rather than a filter miss.

This is a useful falsification: do not assume the -p OTel pipeline works. It must
be established end to end in a correctly-configured stack before interactive
parity is even a meaningful question.

## What this changes about the release

Observability parity is NOT a simple one-env-var wiring fix, and it is not yet
shown to need the full event-capture arc either. Two prerequisites land first:

- GATE A: prove -p OTel lands in agent_events with the FULL Claude Code OTel env
  set and a correctly-wired collector (set COLLECTOR_URL, the exporter/protocol
  vars, and a short export interval). Until GATE A is green there is no baseline.
- GATE B: clear the interactive onboarding + workspace trust gate for unattended
  runs (e.g. --dangerously-skip-permissions or a pre-trusted /workspace, mounting
  .claude.json as well as .claude). This blocks ALL unattended interactive
  workflows, not just observability.

Only after A and B can a sharper v2 probe answer the original parity question and
the plugin-hook channel gap.

## Follow-up: sharper probe v2

experiments/<date>--observability--interactive-tmux-otel-parity-v2 with:
- Full OTel env set + COLLECTOR_URL wired + export interval <= 10s.
- Trust gate pre-cleared so C1/C2 produce real turns.
- Re-score H1/H2/H3 against a now-valid C0 baseline.

## Cross-link: scalability profiling (same day)

Independent profiling of the same workspace model found the interactive-tmux
driver is docker-exec-poll-latency bound, not RAM bound: idle claude workspace
~130 MiB (memory headroom for ~335), but the 2 Hz docker exec capture-pane poll
fails the all-execs-under-500ms criterion at N=8, giving a strict ceiling of ~4
concurrent claude workspaces on this loaded VPS. Top lever: replace 2 Hz docker
exec polling with tmux control-mode / pipe-pane. See ~/swarm-tasks/tmux-scale-findings.md.
