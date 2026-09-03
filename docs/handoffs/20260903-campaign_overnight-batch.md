# Overnight batch: what was dispatched, why, and how to read the results

**Date:** 2026-09-03 (early hours UTC)
**Deployment:** VPS `http://100.114.86.77:8137`
**Purpose:** consume remaining weekly quota on real backlog work, structured so tomorrow's read is a table rather than an archaeology exercise.

## How to read this tomorrow

For each row: find the execution, read its `open_pr` artifact first. That artifact says whether a PR was opened and, if not, why. A run that opened no PR is **not** automatically a failure - the workflow is instructed to stop rather than ship a defect, and that instruction has produced the correct outcome several times today.

Then read the `verify` artifact (codex). Every gate today found something; assume this one did too and look for it.

```bash
export SYN_API_URL=http://100.114.86.77:8137
curl -s -u "admin:$SYN_API_PASSWORD" "$SYN_API_URL/api/v1/executions?page_size=40"
curl -s -u "admin:$SYN_API_PASSWORD" "$SYN_API_URL/api/v1/executions/<id>"
curl -s -u "admin:$SYN_API_PASSWORD" "$SYN_API_URL/api/v1/artifacts/<artifact_id>/content"
```

**The verdict does not reach the PR by itself (#1097).** It has to be posted by hand from the artifact. That is the single highest-leverage unfixed thing in this loop: six gates today, six findings, none of which reached their pull request on their own.

## Configuration in force

```
bootstrap   1200s   claude/sonnet
implement   3600s   claude/opus       <- raised from 2400 this session (#1105)
verify      1800s   codex/gpt-5.6-sol <- the cross-model gate
open_pr      600s   claude/sonnet
```

The prompts now carry design-quality criteria (deep modules, information hiding, special cases designed out) and an explicit anti-dressing-up section, both added in #1096.

## Known conditions that will affect these runs

- **`exit -11`** - docker CLI SIGSEGV, no stderr, recurring, unexplained. Expect one or two.
- **An API restart orphans every in-flight run** (#1103) and `cancel` returns 200 without acting. Do not restart the API while this batch runs.
- **Silent dispatch loss** (#1099) - 10 of 21 vanished in an earlier burst. Count what actually appears rather than trusting the dispatch count.
- **The credential teardown guard** (#1102) can fail a long run at the very end.

## What was dispatched

| Issue | Why it was chosen | What "done" looks like |
|---|---|---|
| 1097 | verdict never reaches the PR — highest leverage in the loop | a gate verdict appears as a PR comment without a human copying it |
| 1094 | model/harness invisible; sonnet ran for hours unnoticed | executions LIST returns the harness/model set |
| 1101 | `.env` settings silently ignored unless compose forwards them | a mechanical check in `just preflight` |
| 1091 | `bump-version` leaves 3 schemas stale; local hook under-reports | bump regenerates, or fails telling you to |
| 1085 | a validation reporting FAILED shows as a green execution | semantic verdict reaches the execution status |
| 1067 | conversations render tool calls as empty columns | transcripts readable without digging into MinIO |
| 1064 | per-tool duration never recorded | duration on `record_tool_completed` |
| 1050 | `requires_repos` inferred three different ways | one source of truth |

## Experiment: is event throughput the constraint?

**Answer: no. Concurrent workspace count is.**

Two arms, six runs each, same model, same timeout, differing only in tool-call volume:

```
                 workspaces   health_s      executions_s   tool calls/run
evt-quiet        17           0.10 - 0.48   0.56 - 6.18    0
evt-chatty       12 - 14      0.03 - 0.22   0.14 - 0.67    40
```

Six runs emitting 240 tool events were FASTER than six emitting none. The arms were not matched on workspace count - the box had not drained - so this is directional rather than controlled. But a confound would have had to work in reverse to produce this result.

Consistent with the peak-load measurement: load average 26.94 on 16 CPUs, individual workspaces at 126% CPU, 20 GB memory free, Postgres at 38 of 100 connections with zero lock waits.

**Implication for scaling:** the path to higher concurrency is horizontal workspace scheduling, not a faster event pipeline. The control-plane work (N+1s, polling) is about keeping the dashboard usable at scale - a separate axis from how many agents can run.

## Concurrency ceiling observed

```
26 concurrent workspaces sustained
16 of 16 dispatches landed in that burst (an earlier burst lost 10 of 21 - load-dependent, #1099)
API degraded at 26: health 4.3s, executions back to 12s
```

So 20+ agents run fine; 20+ agents WITH a usable dashboard needs the sessions N+1 fix and #1095.

## Caution when reading run counts

At one point 20 executions reported `running` while only 11 workspace containers existed - nine orphaned by #1103. **Count `docker ps | grep -c agentic-ws`, not the API**, when measuring capacity.

## Read this before trusting any gate verdict from tonight

**"It succeeded" is not evidence of what it did.** Two things degraded silently in the same hour, and both were caught only by inspecting the artifact rather than the summary:

1. **`syn workflow install --force` printed "Installed 1 workflow(s)" while writing a STALE definition.** Twice. Once from a worktree predating the model-config merge, once from a fetch that raced a merge. No diff, no warning, no `updated_at` to check against (#1107, #1058).

2. **A gate dispatched as cross-model ran all-sonnet**, because of (1). It still found a real defect, and it would have been quoted as an independent check.

So: **verify every gate verdict against `phases[].model` on its execution before weighing it.** A verdict from `sdlc-pr-review-v1` is only cross-model if its `verify` phase reads `codex` / `gpt-5.6-sol`.

```bash
curl -s -u "admin:$SYN_API_PASSWORD" "$SYN_API_URL/api/v1/executions/<id>" \
  -o /tmp/e.json && python3 -c "
import json
d=json.load(open('/tmp/e.json'))
for p in d['phases']: print(p['phase_id'], p.get('model'))"
```

And after any `syn workflow install`, read the live config back and compare field by field. That is not caution; it is the only way to know.

## Phase budgets, set from the measured distribution

```
phase        n    p50     max    overruns   budget now
verify      16    303   1847     6 at 1800  -> 3600
bootstrap   28    510   1223     1 at 1200  -> 1800
implement   23    392   2422     0          -> 3600 (raised earlier, #1105)
open_pr      5    145    498     0             600
investigate  5   1657   1801     -            2400   <- closest to its ceiling, NOT adjusted
```

`investigate` is deliberately untouched: 5 samples is the same thin evidence that produced a wrong call on verify earlier tonight (#1105 argued verify was safe at 1800 based on four runs; sixteen showed 37.5% overrun). It waits for data.

## Dispatch lessons

- **Not every open issue is a fix task.** #1069 was a measurement request whose own text said the cause was unknown. The workflow correctly refused to patch it, at ~$2.50. Separate investigations from fixes before dispatching.
- **Check the issue is still open before dispatching.** A long-running dispatcher works from a snapshot that goes stale underneath it - two of four dispatches in one pass were already dead.
