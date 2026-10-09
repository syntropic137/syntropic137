# North star: concurrent agents at scale

Syntropic137 exists to run many AI agents at once, safely and observably, so
that software can be built by fleets of agents rather than one at a time.
Concurrency is the product. Every design decision is judged against it.

## The targets

| Tier | Concurrent executions | Status | Where it runs |
|---|---|---|---|
| **Now** | **20** | not yet met; 9 saturated the host on 2026-10-05 | one self-hosted node (flywheel: 16 cores, 62 GB) |
| **Next** | **100** | the near-term goal, as soon as possible | one large node or a few nodes, executors split from the API |
| **Production** | **1,000** | the bar for "production ready" | many nodes and/or cloud sandboxes (Firecracker/E2B) behind `IsolationBackendPort` |

"Concurrent" is checked by a load run:
- **Workload:** `sdlc-implement-v3`-shaped executions, all admitted within 5 minutes, each with an agent actively working in a phase. A phase waiting in a queue does not count, and neither does a slot that is idle.
- **Duration:** sustained for at least 30 minutes.
- **The pass bar:**
  - p95 of the dashboard list and detail reads under 500 ms during the run;
  - zero executions lost or orphaned by load, or by a deploy made during the run;
  - every event the agents produced reconciled as captured (the [#1550](https://github.com/syntropic137/syntropic137/issues/1550) detector reports no dropped starts, and the per-run event counts match the recorded transcripts).
- **Model tokens:** a recorded-playback or stub agent may stand in for the model, so the check can run on every beta.

A number reached by queueing everything, or by letting the control plane fall over, does not count.

Long-range sizing for 10k agents is in [scaling-to-10k.md](scaling-to-10k.md). It predates the measurements below; treat its numbers as estimates.
What it takes to reach 100 and 1,000, with the 2026-10-08 observations: [research/2026-10-08-scale-to-100.md](research/2026-10-08-scale-to-100.md).

## Where we are (observed, 2026-10-05 to 2026-10-07)

From [the 2026-10-04 retrospective](retrospectives/2026-10-04-dogfood-orchestrator-day.md), [#1600](https://github.com/syntropic137/syntropic137/issues/1600) and the operator:

- **Peak:** 9 concurrent executions on flywheel pushed load to 21 on 16 cores. One `/sessions` read took 55 s (2026-10-05).
- **Today's baseline** (operator report, 2026-10-07; not re-measured by the capacity-model phase): 5 workspaces, load 17 on 16 cores, 10 of 62 GB RAM in use, `SYN_WORKSPACE_CPU_LIMIT=2` and an 8 GB memory override. The code default for memory is 4096 MB (`packages/syn-shared/src/syn_shared/settings/workspace.py:39`).
- **2026-10-08 observation** (operator report, not re-measured here): on the VPS (16 cores, 62 GB) with `SYN_EXECUTION_MAX_CONCURRENT=10`, each running execution adds about 2.7 to the host load average. The host is CPU-bound while memory sits near 15% in use. Load average counts runnable tasks, not CPU-seconds, so it is an upper-side proxy for CPU demand, not a measurement of it. The event store runs v0.17.0, the same as the ESP pin on `main`.
- **Fixed since the 2026-10-05 snapshot:**
  - the control plane is no longer capped at 0.5 CPU: API and Postgres default to 2 CPU with a 4x CPU weight ([#1602](https://github.com/syntropic137/syntropic137/issues/1602); `packages/syn-shared/src/syn_shared/settings/infra.py:183-221`);
  - one admission budget covers starts, resumes and triggers, and a queued start is visible ([#1557](https://github.com/syntropic137/syntropic137/issues/1557), [#1574](https://github.com/syntropic137/syntropic137/issues/1574));
  - workspace limits are applied at the adapter ([#1606](https://github.com/syntropic137/syntropic137/issues/1606));
  - preflight fails fast ([#1585](https://github.com/syntropic137/syntropic137/issues/1585));
  - deploy drain is bounded ([#1699](https://github.com/syntropic137/syntropic137/issues/1699));
  - pausing no longer waits on queued resumes ([#1617](https://github.com/syntropic137/syntropic137/issues/1617)).
- **Still open:**
  - a deploy kills in-flight runs ([#1310](https://github.com/syntropic137/syntropic137/issues/1310));
  - a graceful shutdown skips work preservation ([#1381](https://github.com/syntropic137/syntropic137/issues/1381));
  - transient errors fail whole runs ([#1593](https://github.com/syntropic137/syntropic137/issues/1593));
  - the API was OOM-killed at its former 512 MB default; the code default is now 2 GB, sized from the incident, not from a load test ([#1552](https://github.com/syntropic137/syntropic137/issues/1552));
  - a deployed event store can lag the ESP pin ([#1708](https://github.com/syntropic137/syntropic137/issues/1708)); nothing yet prevents it, although on 2026-10-08 the VPS ran v0.17.0, matching the pin (operator report).

## Capacity model

> **Status: incomplete. The measured half is outstanding.** The task asked for last-seven-days p50/p90 tokens and cost per phase type and model, quota per run, and measured workspace usage. None of these could be obtained when this was written (2026-10-07). The phase had no reachable deployment: `/api/v1/executions` returned no HTTP response on every candidate address, and there was no Docker CLI. Everything below is therefore a **conditional model**: each "binds" verdict holds only if its stated input holds. Replace the inputs with the measurement in [Measuring the inputs](#measuring-the-inputs), then re-derive the tiers.

**Scope of every figure here.** The workload is `sdlc-implement-v3`-shaped executions on flywheel (16 cores, 62 GB). The per-run inputs come from the capacity plan on [#1310](https://github.com/syntropic137/syntropic137/issues/1310) (exec-ada7853eb9b3, 2026-10-05), which labels each one as an estimate or one sample. **None is a measured distribution.** Code limits are code defaults on `main`. Deployed overrides are named as operator reports.

### Measuring the inputs

This is how to fill the unmeasured rows. It is tracked in [#1716](https://github.com/syntropic137/syntropic137/issues/1716).

- **Selection and window:** `GET /api/v1/executions?page_size=100`, paged, keeping executions of `sdlc-implement-v3` whose start falls in a stated window of 7 x 24 h ending at a stated UTC instant. Then `GET /api/v1/executions/{id}` for each. Record the execution count, and list the IDs or the exact query.
- **Per phase type** (premise, implement, verify, fix and `fix_2`/`fix_3`, reverify and `reverify_2`/`reverify_3`, finalize) **and per model:** n, p50 and p90 of input, output and cache tokens and of cost. Failed or missing phases are counted separately, not dropped. A phase whose model is not recorded is reported as "model unknown", not attributed.
- **Workspace usage:** the `Workspace resource usage` log lines (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:340-360`) for the same executions, on the host. Report CPU-seconds / phase wall and peak memory, as p50/p90 per phase type.
- **Active-run duration:** wall time from admission to the terminal state, as p50/p90. This replaces the duration assumption below.
- **Quota:** Claude Max weekly and session %, and Codex weekly %, read before and after a counted set of runs, with the source named (provider dashboard or CLI). Report % per run.
- **GitHub:** `X-RateLimit-Limit` and `X-RateLimit-Used` from the installation's own responses, sampled hourly over the window. Those headers state the real limit.

### Per-run inputs

| Input | Value | Status |
|---|---|---|
| Phase deadlines summed | 14,400 s with one repair round (premise 1200, implement 3600, verify 3600, fix 3600, reverify 1800, finalize 600); 25,200 s with all three rounds (`fix_2`/`reverify_2`/`fix_3`/`reverify_3` reuse the round deadlines) | `workflows/sdlc/implement-v3/workflow.yaml:72-268`. A **maximum**, not an observed duration |
| Active-run duration *D* | assumed 1-4 h | **assumption**, not measured. Starts/h needed to hold N concurrent = N / *D* (Little's law), so N / 4 to N / 1 |
| CPU demand of an active run | about 1.2 CPU: 1.5-2.2 CPU while gating x about 0.65 gate duty | **estimate** ([#1600](https://github.com/syntropic137/syntropic137/issues/1600), [#1585](https://github.com/syntropic137/syntropic137/issues/1585)). The operator's 2026-10-08 observation of about 2.7 load per run (see above) is a load-average proxy, not CPU-seconds, but it suggests the estimate is low |
| Workspace CPU cap | 2.0 per workspace | code default, `packages/syn-shared/src/syn_shared/settings/workspace.py:42` |
| Workspace RAM | 0.5-1 GB used | used: **estimate**. Cap: 4096 MB code default (`workspace.py:39`); 8 GB on the VPS by **operator report** |
| Workspace disk | 1-3 GB per phase (clone, deps, caches; five of six phases start cold) | **estimate** |
| API memory | 443 MB at the OOM with 8 runs, during artifact collection, with the process baseline included | **one sample** ([#1552](https://github.com/syntropic137/syntropic137/issues/1552)). It gives neither a baseline nor a per-run slope. Per-run RSS is **unmeasured** |
| Model requests per Claude agent | 0.03-0.1 req/s | **estimate** |
| GitHub requests per run | formula below | read from code. Retries and agent-side calls **unmeasured** |
| Tokens and cost per phase and model | - | **unmeasured** ([#1716](https://github.com/syntropic137/syntropic137/issues/1716)) |
| Quota per run, Claude Max weekly and session | - | **unmeasured**. The orchestrator observed about 68% of the weekly limit left after a heavy day (2026-10-07, operator report) |
| Quota per run, Codex weekly | - | **unmeasured**. 2 capacity failures at a peak of 7 or fewer (retrospective) |

### GitHub requests, counted from code

*R* = repositories in the run, *I* = distinct installations behind them, *P* = phases (6 with one repair round, 10 with three). Each phase gets its own workspace.

A **credential mint** is one call to `SetupPhaseSecrets.create`, which does two things:
- one `GET /repos/{r}/installation` per repository (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/setup_phase_secrets.py:388-427`, `packages/syn-adapters/src/syn_adapters/github/client_endpoints.py:195-216`);
- one `POST /app/installations/{id}/access_tokens` per installation (`setup_phase_secrets.py:431-454`, `client_token.py:330`).

So a mint costs *R* + *I* requests. Both are **app-JWT** requests, not installation-token requests.

Mints per phase:

| When | Count | Source |
|---|---|---|
| Workspace setup | 1 | `setup_phase_secrets.py` |
| Quarantine rehearsal at phase start | 1, more on retry | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/quarantine_rehearsal.py:88-96` |
| Credential keeper while the agent runs | floor(*T* / 40 min), more on retry every 3 min | `packages/syn-adapters/src/syn_adapters/workspace_backends/service/credential_keeper.py:46-51,113-131`. 0 for phases of 40 min or less, at most 1 for a 3600 s phase |
| Quarantine push at teardown | 0 or 1 | `.../execute_workflow/unpushed_work_guard.py:904` |
| Revocation at teardown | one `DELETE /installation/token` per unexpired token minted, **installation-token** auth | `packages/syn-adapters/src/syn_adapters/github/client_token.py:351-371`, `.../service/managed_workspace.py:328` |

Without retries or quarantine, the platform mints per run are:
- **one repair round:** 2*P* + renewals = 12 to 15, because implement, verify and fix can each renew once;
- **three rounds:** 20 to 25.

Those mints cost (12 to 25) x (*R* + *I*) app-JWT requests, plus at most (12 to 25) x *I* installation-token revocations. For *R* = *I* = 1, that is 24 to 50 app-JWT requests and at most 25 installation requests per run.

Two pollers run independently of runs and also spend installation-token requests:
- **Events API:** per watched repository, a conditional `GET /repos/{o}/{r}/events` every 60 s in active polling or 300 s in safety net, and, when that first page is a 200, up to 9 more pages through its `Link` header (`packages/syn-adapters/src/syn_adapters/github/events_api_client.py:33,100-120,168-205`; `packages/syn-shared/src/syn_shared/settings/polling.py:34-47`). HTTP requests per repository = polls/h x pages/poll, with pages in [1, 10]:
  - safety net (300 s): 12 polls/h, so **12-120 requests/h**;
  - active polling (60 s): 60 polls/h, so **60-600 requests/h**.

  12-60 requests/h is only the single-page case. Not every HTTP request is charged: the first page carries `If-None-Match`, and an authenticated 304 does not count against the limit. Pages 2-10 are sent without an ETag (`events_api_client.py:205`), so each one is charged. **Charged** requests per repository are therefore 0 (every poll a 304) up to the HTTP figure. The real charge fraction is **unmeasured**. These figures are per watched repository and do not scale with executions. Every repository behind one installation adds its own share to that installation's budget.
- **Check-runs:** per *pending SHA*, one request every 30 s (webhooks stale) or 120 s (healthy), only while an active `check_run` trigger exists, for up to 2 h (`packages/syn-domain/src/syn_domain/contexts/github/services/check_run_ingestion.py:165-185`, `polling.py:60-82`). That is 30-120 requests/h per pending SHA. Pending SHAs are PR heads, **not** executions. The tier tables assume **one pending SHA per active execution as a scenario**.

Agent-side `git`/`gh` calls use the installation token and are **unmeasured**.

The limit is per installation, and **5,000 req/h is GitHub's documented minimum** for an installation, not a fixed maximum ([GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). This model keeps 5,000 as the conservative scenario until the installation's `X-RateLimit-Limit` header is read. App-JWT traffic (lookups, mints) is accounted separately from the installation budget.

### Platform limits

| Limit | Value | Source |
|---|---|---|
| Execution budget | 4 by code default, a hand-set constant not derived from the host ([#1715](https://github.com/syntropic137/syntropic137/issues/1715)); overridable with `SYN_EXECUTION_MAX_CONCURRENT`. The VPS runs 10 (operator report, 2026-10-08) | `packages/syn-shared/src/syn_shared/settings/execution.py:23,46-49` |
| API process | one uvicorn process, stdlib event loop, no `--workers` | `infra/docker/images/syn-api/Dockerfile:135,182` |
| API container | 2 CPU, 2 GB code default (was 512 MB; raised from the #1552 incident numbers, not a measured slope) | `packages/syn-shared/src/syn_shared/settings/infra.py:183-184` |
| Postgres (event store tables, projections, observations) | 2 CPU, 1 GB, one instance | `infra.py:201-209` |
| Event store process | 2 GB code default (was 512 MB, which OOM'd on replay: [#1553](https://github.com/syntropic137/syntropic137/issues/1553)); stable at 749 MB on a 46k-event store | `infra.py:220-221` |
| Envoy model-proxy bucket | 100 burst, 10 req/s refill, global, on the shared proxy that Claude traffic takes (`workspace_service.py:259-262`) | `docker/sidecar-proxy/envoy.yaml:156-158` |
| Trigger dispatch guards | 50 per hour, and 10 per 60 s | `packages/syn-shared/src/syn_shared/settings/polling.py:86-107` |
| GitHub App | 5,000 req/h per installation, the documented minimum | GitHub docs, above. The real limit is unread ([#1719](https://github.com/syntropic137/syntropic137/issues/1719)) |
| Deploy, forced or API restart | kills in-flight runs | [#1310](https://github.com/syntropic137/syntropic137/issues/1310), [#1381](https://github.com/syntropic137/syntropic137/issues/1381) |
| Deploy, `scripts/pit_stop.sh` | closes admission and drains for up to 2,700 s. On expiry it aborts and reopens admission without cancelling runs | `scripts/pit_stop.sh:30,318-331,469-471`; [#1699](https://github.com/syntropic137/syntropic137/issues/1699) |

### 20 concurrent, one node (flywheel)

Starts/h to hold 20 at *D* = 1-4 h: 5-20.

| Resource | Need at 20 | Limit | Binds? |
|---|---|---|---|
| Host CPU | 20 x 1.2 = 24 CPU, plus about 4 for the control plane | 16 cores | **hypothesis: yes**, about 1.75x, *if* the 1.2 CPU estimate holds. The operator observations (load 17 at 5 workspaces on 2026-10-07; about 2.7 load per run, CPU-bound, on 2026-10-08) point the same way, and at 2.7 per run 16 cores would saturate near 6 runs, but load average does not measure per-run CPU demand ([#1714](https://github.com/syntropic137/syntropic137/issues/1714)) |
| Admission | 20 slots | 4 by code default, 10 on the VPS (operator report) | yes, by configuration. Sizing it needs the CPU figure ([#1715](https://github.com/syntropic137/syntropic137/issues/1715)) |
| API memory | **unmeasured.** Linear extrapolation of the one 443 MB / 8 sample gives about 1.1 GB, an **unvalidated scenario** and not a minimum | 2 GB code default (was 512 MB) | **possible**; 2 GB is an incident-derived limit, not a validated one. The slope is still unmeasured, outstanding in the load test ([#1717](https://github.com/syntropic137/syntropic137/issues/1717)) ([#1552](https://github.com/syntropic137/syntropic137/issues/1552)) |
| Host RAM | 10-20 GB in use (estimate) plus the platform | 62 GB; caps overcommit (20 x 4 GiB = 80 GiB at the default) | not on the estimate. Caps can overcommit |
| Disk | 20-60 GB (estimate) | 63 GB free on 2026-10-05 ([#1310](https://github.com/syntropic137/syntropic137/issues/1310) plan); not re-measured | possible at the upper end |
| Codex, one account | up to 20 parallel verify/reverify phases | unknown; 2 capacity failures at 7 or fewer | **hypothesis: likely** ([#1718](https://github.com/syntropic137/syntropic137/issues/1718)) |
| Claude Max, one token | 20 parallel agents | unknown | unknown ([#1718](https://github.com/syntropic137/syntropic137/issues/1718)) |
| Envoy bucket | 0.6-2 req/s (estimate) | 10 req/s | no, on the estimate |
| GitHub installation | 5-20 starts/h x at most 25 revocations = at most 500 req/h. Check-runs, scenario of 1 pending SHA per run: 600-2,400 req/h. Events API, per watched repository on the installation: 12-120 HTTP req/h in safety net, 60-600 in active polling (pages 1-10 per poll), charged 0 up to that. Total with one watched repository and every upper end: 500 + 2,400 + 600 = 3,500 req/h. Agent calls unmeasured | 5,000 req/h (minimum) | **no on these scenarios**, but up to about 70% of the minimum with one watched repository before agent calls, and each further repository on the installation adds up to 600 ([#1719](https://github.com/syntropic137/syntropic137/issues/1719)) |
| Trigger guard | 5-20 starts/h, only if all starts are trigger-driven | 50/h | no |
| Transient failures | a dropped connection fails the run | - | yes, for reliability rather than capacity ([#1593](https://github.com/syntropic137/syntropic137/issues/1593)) |

**First bottleneck at 20 (hypothesis): host CPU,** from cold gates. This rests on the 1.2 CPU estimate and becomes a finding only once [#1716](https://github.com/syntropic137/syntropic137/issues/1716) measures it. If the estimate holds, raising the budget only turns the deficit into deadline failures. The fix would be cheaper runs ([#1714](https://github.com/syntropic137/syntropic137/issues/1714)), then a budget sized from measured demand ([#1715](https://github.com/syntropic137/syntropic137/issues/1715)).

### 100 concurrent

Starts/h to hold 100 at *D* = 1-4 h: 25-100.

| Resource | Need at 100 | Limit on flywheel | Binds? |
|---|---|---|---|
| Host CPU | 120 CPU on the estimate, plus the platform | 16 | **hypothesis: yes, 7.5x.** Even an 8x cut in per-run CPU only just fits one node |
| Disk | 100-300 GB (estimate) | about 63 GB free | yes across the whole estimated range |
| Host RAM | 50-100 GB (estimate) | 62 GB | **possible**: the estimate straddles the limit |
| API process | 100 `docker exec` streams and every projection in one process; memory unmeasured (a linear extrapolation of the one sample gives about 5.5 GB, an unvalidated scenario) | one process, 2 GB code default (an incident-derived stopgap, not validated at 20 or 100) | **hypothesis: yes**. The executors would need to split from the API ([#1310](https://github.com/syntropic137/syntropic137/issues/1310)) |
| Model providers | 100 parallel agents on one Claude and one Codex account | unknown caps | **hypothesis: the first external limit** ([#1718](https://github.com/syntropic137/syntropic137/issues/1718)) |
| Envoy bucket | 3-10 req/s (estimate) | 10 req/s | possible at the upper end ([#1720](https://github.com/syntropic137/syntropic137/issues/1720)) |
| GitHub installation | check-runs at 1 pending SHA per run: 3,000-12,000 req/h; revocations at most 2,500 req/h; Events API up to 600 req/h per watched repository with pagination included (does not scale with runs) | 5,000 req/h (minimum) | **exceeded at the upper end of the scenario**, *if* check-run polling is active and webhooks are stale ([#1719](https://github.com/syntropic137/syntropic137/issues/1719)) |
| Trigger guard | 25-100 starts/h, if trigger-driven | 50/h | exceeded for *D* < 2 h with all starts trigger-driven ([#1721](https://github.com/syntropic137/syntropic137/issues/1721)) |
| Postgres and event store | 10-30 observation rows/s plus events (estimate) | one Postgres at 2 CPU / 1 GB | unknown; measure ([#1722](https://github.com/syntropic137/syntropic137/issues/1722)) |
| Deploys | runs survive a deploy | a forced or API restart kills in-flight runs; a pit stop holds admission up to 45 min | **yes** for forced restarts ([#1310](https://github.com/syntropic137/syntropic137/issues/1310), [#1381](https://github.com/syntropic137/syntropic137/issues/1381)) |

**First bottleneck at 100 (hypothesis): host capacity.** CPU exceeds one 16-core node on the estimate, and disk exceeds it across the whole estimated range. Next is the single API process. **The first external limit is hypothesised to be model-provider quota** ([#1718](https://github.com/syntropic137/syntropic137/issues/1718)), which no host purchase fixes.

### 1,000 concurrent

Starts/h to hold 1,000 at *D* = 1-4 h: 250-1,000.

| Resource | Need at 1,000 | Limit | Binds? |
|---|---|---|---|
| Hosts | 1,200 CPU on today's estimate | one node, one Docker host | **yes, by construction**: there is no multi-host executor ([#1734](https://github.com/syntropic137/syntropic137/issues/1734)) |
| Credentials off-host | remote sandboxes must hold no raw credential | every credential is inside the sandbox today | **yes**: gates the remote tier ([#1735](https://github.com/syntropic137/syntropic137/issues/1735); [#724](https://github.com/syntropic137/syntropic137/issues/724) is only the Claude API-key spike) |
| Remote sandbox provider | overflow off the owned hosts | none behind `IsolationBackendPort` | yes ([#350](https://github.com/syntropic137/syntropic137/issues/350)) |
| Model providers | 1,000 parallel agents | per-account limits | **hypothesis: yes**. Multiple accounts and per-tenant quota ([#1718](https://github.com/syntropic137/syntropic137/issues/1718)) |
| GitHub installation | check-runs at 1 pending SHA per run: 30,000-120,000 req/h; Events API up to 600 req/h per watched repository with pagination included (does not scale with runs) | 5,000 req/h (minimum) | **yes on the scenario**, unless polling is batched or spread across installations ([#1719](https://github.com/syntropic137/syntropic137/issues/1719)) |
| Event store and projections | 10x the 100-run event rate | one Postgres | unknown, and there is no baseline rate yet ([#1722](https://github.com/syntropic137/syntropic137/issues/1722)) |

**First bottleneck at 1,000: there is no multi-host executor** ([#1734](https://github.com/syntropic137/syntropic137/issues/1734)). This one is structural, not an estimate: every run is placed on one Docker host. Next are off-host credentials ([#1735](https://github.com/syntropic137/syntropic137/issues/1735)) and quota per account.

### Ordered path

Each step's issue states the measurement that closes it. Issues that predate this model carry it as a "Scaling acceptance measurement" comment.

1. **Measure:**
   - per-phase usage, tokens and cost, p50/p90 ([#1716](https://github.com/syntropic137/syntropic137/issues/1716));
   - the token-free load test ([#1717](https://github.com/syntropic137/syntropic137/issues/1717)).
   Every later number is re-derived from these, and the hypotheses above are confirmed or dropped.
2. **20, platform side:**
   - API memory slope measured and sized for 20 ([#1552](https://github.com/syntropic137/syntropic137/issues/1552));
   - transient-error retry ([#1593](https://github.com/syntropic137/syntropic137/issues/1593));
   - shutdown preserves work ([#1381](https://github.com/syntropic137/syntropic137/issues/1381));
   - deployed images match the pin ([#1708](https://github.com/syntropic137/syntropic137/issues/1708)).
3. **20, node side:**
   - cheaper gates through a warm read-only dependency seed ([#1714](https://github.com/syntropic137/syntropic137/issues/1714));
   - then a budget sized from measured host capacity ([#1715](https://github.com/syntropic137/syntropic137/issues/1715));
   - then prove N=20 with the load test ([#1717](https://github.com/syntropic137/syntropic137/issues/1717)).
4. **100:**
   - executors split from the API, so a deploy no longer touches running work ([#1310](https://github.com/syntropic137/syntropic137/issues/1310));
   - per-provider budgets and quota telemetry ([#1718](https://github.com/syntropic137/syntropic137/issues/1718));
   - GitHub call accounting and batched check-run polling ([#1719](https://github.com/syntropic137/syntropic137/issues/1719));
   - a configurable Envoy bucket ([#1720](https://github.com/syntropic137/syntropic137/issues/1720));
   - a trigger guard sized to throughput ([#1721](https://github.com/syntropic137/syntropic137/issues/1721));
   - the host-spec decision: more nodes, or cheaper runs.
5. **1,000:**
   - no credential inside a remote sandbox ([#1735](https://github.com/syntropic137/syntropic137/issues/1735));
   - multi-host placement, heartbeat and fencing ([#1734](https://github.com/syntropic137/syntropic137/issues/1734));
   - the remote sandbox provider ([#350](https://github.com/syntropic137/syntropic137/issues/350));
   - event store and projections load-tested at 10x the 100-run rate ([#1722](https://github.com/syntropic137/syntropic137/issues/1722));
   - per-tenant cost and quota controls.

Every bottleneck issue above carries the `scaling` label and sits under the epic [#1612](https://github.com/syntropic137/syntropic137/issues/1612).

## How to use this

- **Before a design or a review:** ask "does this still work at 100 concurrent? At 1,000?" If not, say what breaks and file it.
- **Measure before you size.** Record the observed figure and its source, as above.
- **A concurrency limit that is a hard-coded constant is a defect.** It belongs in settings, sized from measurement.
- **When a run fails under load,** the paper cut names the tier it blocks.
