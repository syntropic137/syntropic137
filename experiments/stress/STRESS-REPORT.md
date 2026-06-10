# Interactive-tmux Workspace Provider — Stress Report

**Campaign:** synstress (flywheel kickoff)
**Branch under test:** `feat/interactive-tmux-workspaces` @ `b2b0a28b`
**Tester branch:** `exp/interactive-tmux-stress` (this branch, off feat/…)
**Date:** 2026-06-10 (UTC)
**Stack:** local Syntropic137 with `docker/docker-compose.dev-interactive-tmux.yaml` overlay; API at `http://localhost:9137`.
**Scope:** stress-test the interactive-tmux integration end-to-end (HTTP → workspace provider → tmux-driven Claude REPL → cleanup). Read-only outside `experiments/stress/`.

The report is organized as five scenarios (S1–S5), each with a frozen hypothesis, observed results, and a verdict. A ranked defect list follows. Every defect has a reproduction recipe pointing at scripts under `experiments/stress/scripts/`.

---

## Executive verdict

* **Phase-level integration works.** The send → await → capture loop completes against a real interactive Claude REPL in all 5/5 sequential and 3/3 concurrent runs (S1, S2). Workspace destruction works on the happy path — no new container leaks across 18 executions (S1–S5).
* **Workflow-level path is BROKEN even on the happy path.** ~60% of "successful phase" runs end in `workflow_status=failed` with `error_message='reply'`. The known `KeyError: 'reply'` in `WorkflowExecutionProcessor._handle_collect_artifacts` (plan §9) is intermittent under stress, not a clean 100% fail as the plan suggested.
* **Control-plane cancel is a no-op on this provider.** `POST /executions/{id}/cancel` returns 200 with `message="Cancel signal queued"` but the phase runs to completion (S3b). This is the #1 ship-stopper for operator UX.
* **Long responses break readiness detection and lose content.** A multi-paragraph prompt completes inside Claude (sentinel emitted in the pane scrollback at ~T+15s) but the driver's `is_ready()` heuristic never fires; the phase times out 4 minutes later, the captured `pane_chars` is the truncated visible pane (1834 chars) instead of the full response (5716+ bytes in scrollback) — S4.
* **No quota burn** worth flagging — 18 runs, ~9.9 minutes of total agent wall time, zero `429`/quota/refusal signals in logs (S5).
* **Lane-2 telemetry is dark on this provider** — token counts, tool calls, and cost all report `0` for every interactive-tmux execution, while the phase clearly ran (and consumed Claude OAuth quota).

A reasonable summary: **the workspace primitives are solid; the orchestration glue around them is not ready to ship.**

---

## Pre-existing state (baseline)

Three `interactive-tmux-itws-*` containers were already running when the campaign started, created at 2026-06-10T03:41 UTC — about 14 hours before the campaign. They are **pre-existing leaks** from a prior bring-up session, **not introduced by this campaign**. Their container IDs are pinned in `experiments/stress/results/baseline-leaks.txt`; every per-scenario leak check diffs against this baseline.

```
0ef661555b2f
e2f051dd522d
eb8416735629
```

That these containers survived previous test runs is itself a signal — the cleanup path that worked in this campaign did not work for whichever path created those three. Recorded as defect **D6 (minor)** below.

---

## S1 — Sequential load (5 runs)

**Hypothesis (frozen pre-run):**
- H1.a Each of 5 sequential phases completes in <60s wall-time.
- H1.b No monotonic latency creep across 5 runs (last within ±50% of first).
- H1.c No new `interactive-tmux-*` containers persist after each run (cleanup OK).
- H1.d Workflow-level status may be `failed` due to the known artifact-pipeline `KeyError: 'reply'` — phase completion + cleanup is the success criterion.

**Procedure.** `experiments/stress/scripts/s1_sequential.sh`. Five back-to-back `POST /workflows/reply-ok-interactive/execute` calls, each waited to terminal state, with itmux-container snapshot diff after every run.

**Results (per run):**

| Run | execution_id        | workflow_status | phase_status | phase_dur (s) | wall (s) | new leaks |
|-----|---------------------|-----------------|--------------|---------------|----------|-----------|
| 1   | exec-7440adb89bbb   | completed       | completed    | 18.11         | 20.34    | 0         |
| 2   | exec-11e8566e1069   | **failed**      | completed    | 19.03         | 22.52    | 0         |
| 3   | exec-68b9615270aa   | **failed**      | completed    | 19.74         | 22.12    | 0         |
| 4   | exec-4d3257aae962   | **failed**      | completed    | 17.04         | 19.15    | 0         |
| 5   | exec-672b90bebe02   | completed       | completed    | 17.95         | 20.26    | 0         |

(Run 1's exec_id from the run is recorded in `results/s1-runs.ndjson`; the table above is reconstructed from that file.)

**Latency:** phase duration min 17.04s, max 19.74s, avg ≈18.4s. No monotonic creep. **H1.a + H1.b ✓**.

**Cleanup:** 5/5 runs ended with the post-run container set identical to the baseline. **H1.c ✓**.

**Workflow-level:** 2/5 completed, 3/5 failed with `error_message='reply'`. The integration plan §9 framed this as a deterministic gap but in practice it is **non-deterministic** under identical inputs — runs 1 and 5 succeeded, runs 2–4 failed. This raises the defect from "predictable known-gap" to "intermittent failure that operators cannot anticipate." Logged as **D1 (blocker)**.

**S1 verdict:** Phase integration ✅. Workflow-level orchestration ❌ (intermittent, defect D1).

---

## S2 — Concurrency (3 simultaneous)

**Hypothesis (frozen pre-run):**
- H2.a All 3 phases complete; no cross-execution capture.
- H2.b Each execution provisions its own container; 3 coexist mid-flight; 0 leak after.
- H2.c Total wall time for the 3 concurrent runs is <40s (sub-linear vs ~20s sequential).
- H2.d Distinct session_ids per run.

**Procedure.** `experiments/stress/scripts/s2_concurrency.sh`. Three concurrent `execute` calls fired with `bash &` job control. Mid-flight container snapshot at T+6s, post-run snapshot after all 3 reach terminal state.

**Results:**

| execution_id        | workflow_status | phase_status | phase_dur (s) | session_id (head)        |
|---------------------|-----------------|--------------|---------------|--------------------------|
| exec-dc2bf66a480c   | **failed**      | completed    | 29.59         | 7c757b88-…               |
| exec-c26bff4bd809   | completed       | completed    | 27.32         | 863b2dea-…               |
| exec-906cf4661d47   | completed       | completed    | 21.52         | 9de4669d-…               |

- **3 distinct session_ids** → isolation primitive works at the session layer. **H2.d ✓**.
- **3 distinct workspace IDs** in syn-api logs (`itws-602e1f43`, `itws-4dfe0334`, `itws-09b6293f`) — also distinct. **H2.a ✓** (no cross-talk).
- **Mid-flight container count at T+6s: 2, not 3.** syn-api logs show the three `Running setup phase with secrets` log lines were emitted at 17:48:56.932 / 17:48:57.264 / 17:48:57.472 — staggered ~200–300ms apart. The mid-flight snapshot at T+6s caught a moment when only 2 containers had been registered with the docker daemon. Not a leak, but it is **evidence that workspace provisioning is not fully parallel** — there is a serialization point inside `WorkspaceService.create_workspace`. Logged as **D5 (minor — perf / observability)**.
- **Phase duration under load: 21.5 / 27.3 / 29.6s** vs ~18s sequential. That is a **+47% to +65%** latency hit at 3-way concurrency. The shared docker-socket-proxy and the per-phase setup-secrets step are the obvious candidates.
- **Total wall time:** 36.3s < 40s budget. **H2.c ✓**.
- **Post-run leaks:** 0. **H2.b ✓** (modulo the staggered provisioning above).
- **Workflow-level non-determinism repeats:** 1/3 failed with the same `'reply'` KeyError. Same D1.

**S2 verdict:** Isolation ✅; provisioning has a serialization tax worth understanding; D1 repeats under load.

---

## S3 — Lifecycle resilience

Split into S3a (kill the workspace container mid-flight) and S3b (control-plane cancel).

**Hypothesis (frozen pre-run):**
- H3.a Killing the workspace surfaces as a typed failure; no hang >60s past kill.
- H3.b Control-plane cancel works on an interactive execution; the engine routes through the existing CancelExecution path; workspace is destroyed.

### S3a — `docker kill` mid-execution

**Procedure.** `experiments/stress/scripts/s3_resilience.sh` § S3a. Submit; wait for the new itmux container to appear; `docker kill <ctr>` it; measure time-to-terminal and the resulting error payload.

**Results:**
- `final_status = failed` within **1375 ms** of the kill. No hang. **H3.a (no-hang) ✓**.
- `phase_status = "running"` while `workflow_status = "failed"`. **Phase record is stranded in `running`** — the workflow rolled up to failed but the inner phase never received the "failed" event. **D3 (major — state inconsistency)**.
- `error_message =`
  ```
  Command '['docker', 'exec', 'interactive-tmux-itws-3cef84e7-86b6c920',
            'tmux', 'capture-pane', '-p', '-t', 'agents:claude']'
   returned non-zero exit status 137.
  ```
  This is the raw Python `subprocess.CalledProcessError.__str__`. Exit code 137 = SIGKILL (expected); the leakage is the **shape of the message**: it exposes internal container names, the literal docker-exec arglist, and the tmux pane address. **No typed domain error** (e.g. `WorkspaceTerminated`, `WorkspaceDisappeared`). Operators reading the dashboard get raw shell. **D2 (major — typed error contract)**.
- **No orphan container** after the kill. **H3.a (cleanup) ✓**.

### S3b — Control-plane Cancel

**Procedure.** `experiments/stress/scripts/s3_resilience.sh` § S3b, then a retry recorded in `experiments/stress/results/s3-cancel-retry.json`. Submit; wait for itmux container to appear; sleep 1.5s so cancel lands inside the agent loop; `POST /executions/{id}/cancel`; measure cancel→terminal and assert final status.

**Run 1 (in the resilience harness):**
- `POST /executions/exec-766bdb7dc2e0/cancel` returned **404 `{"detail":"Execution not found: exec-766bdb7dc2e0"}`** for a valid execution that the `execute` endpoint had just returned.
- Root cause: the cancel route resolves the execution id through `prefix_resolver.resolve_or_raise(mgr.store, "workflow_execution_details", …)` (`apps/syn-api/src/syn_api/routes/executions/control.py:31`). The `workflow_execution_details` projection had not caught up at the moment of the call.
- **Projection visibility lag measured at 4535 ms** in the retry harness (poll `GET /executions/{id}` until 200). For ~4.5s after `execute`, the cancel endpoint is unreachable. **D4 (major — control-plane race window)**.

**Run 2 (visibility-aware retry):**
- After waiting for `GET /executions/{id}` to return 200, `POST .../cancel` returned:
  ```
  { "success": true, "execution_id": "exec-e45a95f159e1",
    "state": "running", "message": "Cancel signal queued" }
  ```
- The phase nonetheless **ran to natural completion**: 18.4s duration, `phase_status = completed`, `workflow_status = failed` (same `'reply'` KeyError). Time from cancel-call → terminal: 17875 ms — i.e. the cancel had **zero effect on wall time**.
- **The cancel signal is acknowledged at the HTTP layer but never reaches the interactive-tmux agent loop.** The `workspace._handle.send_message → await_completion → capture_response` blocking call in `AgentExecutionHandler.handle` does not appear to honor `interrupt_requested`. **D-block-1 (blocker — cancel is a no-op on interactive-tmux)**.

**S3 verdict:** S3a kill: typed-error contract violated (D2), phase status stranded (D3), but no hang and no orphan. S3b cancel: BLOCKER. Cancel cannot be exercised on interactive-tmux phases (D-block-1), and even when it can be addressed by the cancel route, there is a 4.5s race window where it 404s (D4).

---

## S4 — Long conversation capture

**Hypothesis (frozen pre-run):**
- H4.a Phase completes (Claude does answer).
- H4.b Capture completeness: the pane contains the sentinel `[END-OF-LONG-REPLY-SENTINEL]` the prompt demands.
- H4.c Captured response is not silently truncated mid-word.

**Procedure.** `experiments/stress/scripts/s4_long.sh` registers a new template (`experiments/stress/workflows/reply-long.yaml`) that asks for 5 paragraphs + numbered list ending with the literal sentinel. While the phase runs, the harness `docker exec`s into the workspace container every second and grabs `tmux capture-pane -p -S -10000` to checkpoint actual pane state.

**Results:**

| Metric                                  | Value                                                          |
|-----------------------------------------|----------------------------------------------------------------|
| Workflow status                         | **failed**                                                     |
| Workflow error                          | `Agent execution failed for phase reply-long (exit_code=124) (tokens=0+0)` |
| Phase status                            | **`running`** (stranded — same shape as D3)                    |
| Reason (driver log)                     | `timeout_never_ready`                                          |
| Phase wall time                         | **250.7 s** (driver timed out at the YAML `timeout_seconds: 240`) |
| `pane_chars` captured at exit           | **1834**                                                       |
| Largest pane dump grabbed externally    | **5716 bytes** (with `capture-pane -S -10000`)                 |
| Sentinel present in external dump #15   | **YES** (i.e. ~15 s into the run)                              |
| Sentinel present in pane_chars=1834     | **NO** (truncated)                                              |
| New container leaks after               | 0                                                              |

**Interpretation.**

1. **The model finished its answer within ~15 seconds.** The sentinel appears in the live `capture-pane -S -10000` dumps from `dump-15.txt` onward — that is, content the model emitted ~15 s into the phase.
2. **The driver's `is_ready()` never fired.** It kept waiting another ~225 s until the workflow-side timeout exhausted at 240 s. The whole phase therefore lasted **~16× longer than necessary**, and the workspace held container + tmux + a live Claude REPL captive that whole time. **D-block-2 (blocker — readiness detection broken for non-trivial responses)**.
3. **The captured response is incomplete.** `capture-pane -p` (driver's call at `interactive_tmux.py:177`) defaults to the visible pane only; the scrollback (where the sentinel lives) is not in `pane_chars=1834`. So even if the workflow succeeded, the artifact downstream consumers see would be silently truncated. **D-block-3 (blocker — capture completeness)**.
4. **Phase status stranded at `running`** while workflow rolled up to `failed` — same D3 shape as S3a.
5. **`phase_model` reports `haiku` though the YAML specifies `sonnet`.** Same as S1. **D7 (minor — model selection signal not respected, or telemetry misreport)**.

**S4 verdict:** FAIL. The two ship-stopper problems are the readiness heuristic and the visible-pane capture; either one alone makes the path unusable for any prompt that elicits more than a one-word reply.

---

## S5 — Budget / wall-time reality

**Hypothesis (frozen pre-run):**
- H5.a Total Claude OAuth quota burn across the 18-ish executions in the campaign is unremarkable (no `429`, no refusals).
- H5.b Wall-time distribution mirrors what S1–S4 individually reported.

**Procedure.** `experiments/stress/scripts/s5_budget.py` reads `/executions`, restricts to executions with `started_at >= 2026-06-10T17:42` (the campaign cutoff), aggregates wall time, and scrapes `docker logs syn-api` for quota/refusal patterns.

**Results:**

| Metric                           | Value     |
|----------------------------------|-----------|
| Executions in campaign           | **18**    |
| Min duration                     | 2.18 s (the S3a kill)        |
| Max duration                     | 249.84 s (the S4 long)       |
| Median duration                  | 19.11 s                      |
| Average duration                 | 33.14 s                      |
| `status=completed`               | 7         |
| `status=failed`                  | 11        |
| `status=cancelled`               | **0** (corroborates D-block-1) |
| Total tokens observed (sum)      | **0** (corroborates D-obs-1)   |
| `429` / rate-limit signals       | none      |
| Quota refusal in syn-api logs    | none      |

The only Anthropic-shaped log line in the campaign window is `ANTHROPIC_API_KEY not configured — agent execution disabled. Set it in .env or 1Password to enable workflow runs.` — which is **expected** on this path (interactive-tmux uses OAuth on the mounted credentials, not the injected env var). This is also confirmation of the Envoy ext_authz bypass the plan §3.4 committed to.

**Cost-per-stress-pass estimate.** The campaign ran 18 executions in ~16 wall minutes. Most are short (the median is ~19 s) and reply with a one-word answer. Even at retail Sonnet rates this is well under a dollar of OAuth-billed time. **A nightly stress run is operationally cheap.** What it does NOT cost in Anthropic dollars, it costs in **infrastructure dollars** when long-tail phases like S4 hold a workspace + container for 4 full minutes after the model is done — that is the real budget concern.

**Tokens-observed = 0 across all 18 runs.** Lane-2 observability (token counting, cost, tool traces) is dark on the interactive-tmux path. This is the headline observability defect. **D-obs-1 (major — Lane-2 telemetry missing)**.

**S5 verdict:** Quota fine; cost-per-pass fine; the missing telemetry (D-obs-1) makes "budget reality" hard to monitor in dashboards today.

---

## Defect list (ranked)

Severity rubric:
- **blocker** — ship-stopper; an operator using this path will hit it on a real workflow.
- **major** — likely to surface in production but a workaround exists or the impact is narrow.
- **minor** — annoyance, polish, or an observability gap.

### Blockers

#### D-block-1 — Control-plane Cancel is a no-op on interactive-tmux executions

- **Symptom:** `POST /executions/{id}/cancel` returns 200 with `success=true` and `message="Cancel signal queued"`, but the interactive-tmux phase runs to its natural completion. No `cancelled` status is ever produced.
- **Evidence:** `experiments/stress/results/s3-cancel-retry.json`. `phase_duration_seconds=18.45 s`, identical to an uncancelled run; total executions in the campaign with `status=cancelled` = **0**.
- **Reproduction:**
  ```sh
  bash experiments/stress/scripts/s3_resilience.sh
  cat experiments/stress/results/s3-resilience.json
  cat experiments/stress/results/s3-cancel-retry.json
  ```
- **Likely cause:** `AgentExecutionHandler.handle` blocks on `workspace._handle.await_completion(agent, timeout=…)` on the interactive-tmux path; the `CancelExecution` command propagated through `ExecutionController` is not observed by that loop (no shared `asyncio.Event`, no signal into the tmux send/await primitives). The plan §3 advertises piggy-backing on the existing control plane but the wiring is incomplete.

#### D-block-2 — `is_ready()` heuristic fails for multi-paragraph Claude responses

- **Symptom:** A prompt asking for 5 paragraphs + a numbered list + a literal sentinel produced the sentinel in the live pane scrollback within ~15 s, but the driver kept waiting until `timeout_seconds=240` and exited with `exit_code=124, reason=timeout_never_ready`.
- **Evidence:** `experiments/stress/results/s4-long.json` + the 60 per-second dumps under `experiments/stress/evidence/s4-pane-dumps/`. Sentinel appears starting at `dump-15.txt`; the phase nonetheless burned 250 s of wall time.
- **Reproduction:** `bash experiments/stress/scripts/s4_long.sh`.
- **Likely cause:** the claude adapter's `is_ready()` (under `lib/agentic-primitives/.../driver/interactive_tmux.py`) looks for marker strings that get pushed off the visible 200×50 pane when the response is long. The driver's own readiness check uses the same `capture-pane -p` (no `-S`) that the user-facing capture does — so the longer the answer, the less likely the readiness marker is visible.

#### D-block-3 — Captured response is silently truncated to the visible pane

- **Symptom:** Driver's `_tmux_capture()` calls `tmux capture-pane -p` with no `-S` flag (`lib/agentic-primitives/.../driver/interactive_tmux.py:177`). For a long Claude reply, the captured `pane_chars` is the visible-pane subset (200×50 ≈ 1834 chars in S4) while the actual model output is several KB and includes content (incl. our test sentinel) that scrolled off.
- **Evidence:** S4: `pane_chars=1834` from driver vs `largest_dump_bytes=5716` from external `capture-pane -S -10000`. Sentinel absent in the former, present in the latter.
- **Reproduction:** `bash experiments/stress/scripts/s4_long.sh`; compare `experiments/stress/results/s4-long.json` to the largest dump under `experiments/stress/evidence/s4-pane-dumps/`.
- **Likely cause:** intentional simplification in the driver — but as currently shipped it makes interactive-tmux unusable for any phase whose intended artifact is the model's answer.

#### D1 — Workflow-level orchestration intermittently fails with `KeyError: 'reply'` even on the happy phase path

- **Symptom:** ~60% of phase-completed reply-ok-interactive runs roll up to `workflow_status=failed` with `error_message="'reply'"`. The plan §9 documented this but framed it as deterministic; **it is intermittent** under stress.
- **Evidence:**
  - S1: runs 1 and 5 succeeded, runs 2–4 failed (40% completed).
  - S2: 2/3 succeeded, 1/3 failed.
  - Campaign-wide: 7/18 = 39% workflow-level success.
- **Reproduction:** `bash experiments/stress/scripts/s1_sequential.sh`; observe non-deterministic `workflow_status` across 5 runs of identical input.
- **Already known:** plan §9 attributes this to `WorkflowExecutionProcessor._handle_collect_artifacts` re-dispatching `COLLECT_ARTIFACTS` when `artifact_ids=[]`. The "intermittent" wrinkle is the new evidence here — the to-do projection occasionally **does** advance to `COMPLETE_PHASE`. Race in the in-process projection advancing.

### Majors

#### D2 — Raw Python `CalledProcessError.__str__` leaks as the user-facing error message

- **Symptom:** Killing the workspace container yields `error_message = "Command '['docker', 'exec', 'interactive-tmux-itws-3cef84e7-86b6c920', 'tmux', 'capture-pane', '-p', '-t', 'agents:claude']' returned non-zero exit status 137."`.
- **Impact:** Operators reading the execution-failed banner see literal Python repr of internal docker-exec invocations. No typed domain error (e.g. `WorkspaceDisappeared` or `AgentTransportFailed`) is produced.
- **Reproduction:** `bash experiments/stress/scripts/s3_resilience.sh`; see `s3a_kill.error_message` in `experiments/stress/results/s3-resilience.json`.

#### D3 — Phase status stranded at `running` while workflow rolls up to `failed`

- **Symptom:** When the agent execution fails out-of-band (S3a kill, S4 timeout), the workflow aggregate marks itself failed, but the inner phase record remains `phase_status="running"` with `phase_duration_seconds=0.0` in `S4` (and the original phase metadata in S3a).
- **Impact:** UIs / queries that pivot on `phase_status` will believe a non-existent phase is still in flight indefinitely. Observability + retention queries get false positives.
- **Reproduction:** `experiments/stress/results/s3-resilience.json` (S3a sub-object) and `experiments/stress/results/s4-long.json` (`phase_status: "running"` on a workflow that has long since terminated).

#### D4 — Cancel route returns 404 for ~4.5 s after submit (projection visibility race)

- **Symptom:** Right after `POST /workflows/{id}/execute` returns an `execution_id`, `POST /executions/{execution_id}/cancel` returns `404 {"detail":"Execution not found: ..."}` for several seconds until the `workflow_execution_details` projection catches up.
- **Measured window:** 4535 ms in `experiments/stress/results/s3-cancel-retry.json`.
- **Impact:** "I changed my mind right after I hit go" — the most common operator cancel pattern — is silently 404'd. Operators have to poll `GET /executions/{id}` until 200 before they can cancel. (And then D-block-1 hits.)
- **Reproduction:** submit, immediately POST cancel; see 404.

#### D-obs-1 — Lane-2 telemetry (tokens, tools, cost) is uniformly zero on the interactive-tmux path

- **Symptom:** Every execution in the campaign (18/18) reports `total_tokens=0`, `total_input_tokens=0`, `total_output_tokens=0`, `total_cost_usd=0`, `tool_call_count=0`, regardless of whether the phase succeeded.
- **Impact:** Cost dashboards report `$0.00` for every Claude OAuth call; tool-use observability is dark; tokens-per-phase invariants used elsewhere will misbehave. Plan §7 declared "authoritative token / cost accounting" out of scope, but the dashboard does not have a "this provider is dark" indicator, so the zero is indistinguishable from "actual zero."
- **Evidence:** `experiments/stress/results/s5-budget.json` (`total_tokens_observed: 0`).
- **Reproduction:** every script in this campaign.

### Minors

#### D5 — Workspace provisioning is staggered, not fully parallel; concurrent submits take ~50% longer per phase

- **Symptom:** Three concurrent submits at T+0 produced `Running setup phase with secrets` log lines at T+0.93, T+1.26, T+1.47 s respectively — ~200–300 ms apart. Mid-flight container snapshot at T+6 s caught only 2 of 3 containers. Phase wall time per execution rose ~50% (~18 s sequential vs ~21–30 s under 3-way concurrency).
- **Impact:** capacity planning for "N concurrent stress runs" can't assume linear scaling; expect a per-phase tax on top of sublinear total throughput.
- **Reproduction:** `bash experiments/stress/scripts/s2_concurrency.sh`; inspect `experiments/stress/results/s2-concurrency.json` and the syn-api timestamps in `experiments/stress/evidence/s2.log`.

#### D6 — Three pre-existing leaked workspace containers from previous bring-up

- **Symptom:** Three `interactive-tmux-itws-*` containers (`0ef661555b2f`, `e2f051dd522d`, `eb8416735629`) were running before the campaign started, created at 2026-06-10T03:41 UTC (14 hours before campaign start). The campaign's cleanup paths work (zero new leaks across 18 executions) — but **whatever produced those three originally also went through the same cleanup paths in a previous test session, and the cleanup didn't fire.** Failure-path cleanup is therefore not as robust as happy-path cleanup.
- **Reproduction:** none reliable from this campaign (the conditions that produced the original leak are not currently triggered). Suspect: an exception during destroy that left the docker handle behind. Worth a dedicated retry-during-destroy test.

#### D7 — `phase_model` reports `haiku` even when the workflow YAML specifies `sonnet`

- **Symptom:** Both `reply-ok-interactive.yaml` and `experiments/stress/workflows/reply-long.yaml` set `agent.model: sonnet`, but every execution's phase reports `model: "haiku"` and `cost_by_model: {"haiku": "0.0"}`.
- **Impact:** Either the model selection is being silently downgraded to haiku (a real bug), or the telemetry is reporting the wrong model (a labeling bug). Either way, dashboards lie about which model ran.
- **Reproduction:** any execution in the campaign.

---

## What worked

- **HTTP → workspace adapter → driver round-trip** is solid for short phases: 100% phase-level success across S1 (5/5) and S2 (3/3).
- **Workspace isolation** is genuine: distinct session_ids, distinct itws-* container IDs, no cross-talk in captures.
- **Workspace destroy on the happy path** is reliable: 0 new leaks across 18 executions.
- **Time-to-terminal on hard kill** is fast (<1.5 s).
- **Envoy ext_authz bypass is real** — `syn-token-injector` shows zero traffic for any campaign execution; no `ANTHROPIC_API_KEY` injection. OAuth-on-disk is the actual authn path.
- **Sequential latency is stable** (~17–19 s per phase; no creep across 5 runs).

## What didn't

- **Workflow-level happy path** (D1 — intermittent `KeyError: 'reply'`, 60%+ failure rate).
- **Control-plane cancel** (D-block-1 — no-op).
- **Long-response capture** (D-block-2, D-block-3 — readiness + truncation).
- **Typed error contract** (D2 — raw Python repr leaks).
- **Lane-2 telemetry** (D-obs-1 — uniformly zero).
- **Inner-phase state machine** (D3 — phase stuck at `running` when workflow has failed).

---

## Suggested next steps (for the owning agent on `feat/interactive-tmux-workspaces`)

These are the smallest moves that unstick the report's blockers without redesigning the integration:

1. **D-block-3 first.** Change the driver's `_tmux_capture()` to call `tmux capture-pane -p -S -` (or `-S -10000`) so the captured `pane_chars` includes scrollback. This is a one-line change in agentic-primitives.
2. **D-block-2 next.** The readiness heuristic needs to look at the **scrollback-included** capture (same fix as #1 applied to `_wait_for_text` / `is_ready` callsites), or it needs to anchor on a tail-of-pane regex that survives scroll.
3. **D-block-1 last (but most important).** Wire `CancelExecution` into the interactive-tmux agent loop. Minimum viable: an `asyncio.Event` shared between the `ExecutionController` and the `await_completion` blocking loop, polled between tmux-capture iterations, that breaks the loop and dispatches a cancel-shaped failure event.
4. **D1.** Investigate the to-do projection's transition from `COLLECT_ARTIFACTS` → `COMPLETE_PHASE` when `artifact_ids=[]`. The intermittent shape suggests an in-process projection race, not a clean YAML-level bug.
5. **D-obs-1.** Decide whether interactive-tmux phases should emit synthetic token/cost events from a downstream observability extractor (the integration plan punted on this; the dashboard's `$0.00` problem is real).
6. **D2 / D3.** Catch `CalledProcessError` in `AgentExecutionHandler` and translate into a typed `WorkspaceTransportFailed`; emit a `PhaseFailed` event whenever the workflow aggregate transitions to failed so the inner phase record stops being stranded.

The two minor defects (D5 staggered provisioning, D6 pre-existing leaks, D7 model label) are interesting tells but should NOT gate the integration ship.

---

## Reproduction summary

```sh
# from repo root, with the dev stack up (overlay loaded), on this branch:
bash experiments/stress/scripts/s1_sequential.sh
bash experiments/stress/scripts/s2_concurrency.sh
bash experiments/stress/scripts/s3_resilience.sh
bash experiments/stress/scripts/s4_long.sh
python3 experiments/stress/scripts/s5_budget.py

ls experiments/stress/results/        # per-scenario JSON
ls experiments/stress/evidence/           # raw logs + S4 pane dumps
```

Each script registers / submits idempotently and writes:
- `experiments/stress/results/sN-*.json` — structured findings
- `experiments/stress/evidence/sN-transcript.txt` — raw transcript
