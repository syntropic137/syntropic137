# Queued work — dispatch after the VPS restart

> **STATUS: DRAINED as of 2026-09-05. Do not dispatch from this document.**
>
> Every item below has landed. Verified against the live repo, not this file:
>
> | item | state |
> |---|---|
> | PR #1065 launch marker | MERGED 2026-09-04T05:07:30Z |
> | PR #1072 four writers, one contract | MERGED 2026-09-04T01:36:51Z |
> | PR #1076 running-phase reporting | MERGED 2026-09-03T19:30:14Z |
> | PR #1071 live-update tokens/cost | MERGED 2026-09-04T07:47:32Z |
> | ISS #1146 codex brace-leading parser | CLOSED (this unblocked #1071) |
>
> The `#1071 is blocked until #1146 ships` instruction below is **spent**: #1146
> closed and #1071 merged. Kept verbatim for the record, not as guidance.
>
> The content below is retained because the *findings* remain useful reading —
> the marker-proves-nothing and four-writers-one-contract defects are both
> instances of patterns that recur. It is history now, not a queue.

**Date:** 2026-09-03
**Why this exists:** a VPS restart was coordinated by another session; the rework
queue was drained deliberately and `exec-65164f17a350` (the #1065 launch-marker
rework) was cancelled mid-flight rather than left to be orphaned by the reboot.

Deployment at time of writing: `v0.28.0-beta.3`.

## Dispatch these first, in this order

### 1. PR #1065 — the launch marker proves nothing (blocking, re-dispatch)

This was cancelled in flight. The finding, from the cross-model verify at head
`6d29c34a`:

`stream_helpers.py:30` defines

```sh
_ANNOUNCE_THEN_EXEC = 'printf "%s\n" "$1"; shift; exec "$@"'
```

wired in at `:45`. The marker is printed **before** `exec`, and
`agent_launch_observation.py:69-77` records `AgentLaunchedEvent` on first sight
of a line equal to the marker, with no check that anything followed. So a
missing or non-executable agent binary produces byte-identical evidence to a
successful launch — which is exactly the discriminator #1065 exists to make
trustworthy. The reviewer proved it with an adversarial test using a nonexistent
argv.

Fix so the marker cannot be emitted unless `exec` actually succeeded, or so the
observation requires evidence only a running process can produce. Add a test with
a nonexistent binary that fails if the launch is still recorded.

### 2. PR #1072 — four writers, one contract (structural)

Third distinct desync path in three reviews. Four extractors write `tool_name`
and `content_preview`; only the claude branch (`_join_block_column:374`,
`_extract_claude_tool_fields:404`) rewrites the separator. The codex branch
(`_codex_item_fields:465` → `:188`, `:178`) and the generic fallback (`:552-556`)
do not.

Do **not** patch the other three one at a time — that leaves a fifth writer free
to break it again. Enforce the contract at the single point where the two
response fields are set, and drive every extractor branch with a
separator-bearing value.

### 3. PR #1076 — re-review after the concurrency fix

Head `37a1d86a` claims the phase model now keys by execution, so overlapping runs
of the same workflow cannot terminalise each other's phase. Verify with two
concurrent executions. Each of the previous two reviews found a `0.0`-for-running
surface the one before had missed, so assume there is a third.

### 4. PR #1071 — blocked until #1146 ships

Its verify phase reads TSX every run, and the codex parser treats any
`{`-leading line that is not valid JSON as a protocol error. It has failed twice
for that reason. **Do not re-dispatch until #1146 is fixed and deployed** — it
will just burn another run.

## Do not dispatch

- **#1083** — destructive `GETDEL`; design call for the owner.
- **#1026** — the `workspace_image` field is on the dead `WorkspaceAggregate`
  rather than the live `WorkspaceProvisionedForPhase`; mechanical once decided,
  but the owner has it.

## Verify after the restart, before dispatching anything

The restart itself is a live test of #1121, which is in `beta.3`:

```bash
curl -su admin:$SYN_API_PASSWORD \
  'http://100.114.86.77:8137/api/v1/executions?status=running&page_size=100'
```

Any execution left `running` with no container means reconciliation did not fire.
Before the beta.3 deploy, nine runs sat stranded for a day; the deploy itself
cleared them, which was the first evidence the fix works. A second clean restart
is the confirmation.

Also worth re-checking, since all three ship in beta.3:

| | expected |
|---|---|
| `/api/v1/sessions?limit=50` | ~0.45s, not 2.3s |
| `/api/v1/executions` `total` | 300+, not the page length |
| `docker ps \| grep -c agentic-ws` vs `status=running` | must agree |

## Open platform defects that will bite the next batch

- **#1146** — codex parser fails on any `{`-leading output line. Blocks #1071.
- **#1138** — grpcio segfaults in agent workspaces; three occurrences on 09-03,
  same faulting address. Kills phases at random.
- **#1078** — a live Redis timeout cost a review ~$4.86 mid-run.
- **#1122** — phases cannot record their own model, so every verdict's
  cross-model attribution is supplied by hand.

---

## Update 2026-09-04 ~02:15 UTC

### Landed since this doc was written

- **#1063** merged — decomposition verified over 285,644 + 105,300 sequences, 0 differences.
- **#1155** merged — the port gate rewritten YAML-aware. Every fixture proved against the *pristine* old parser first (each passed at exit 0 before the fix), 5 mutations killed.
- **#1072** merged — see caveat below.
- **#1162** merged then **rolled back on the VPS**. See "the regression" below.

### The regression (read this before deploying beta.5)

`v0.28.0-beta.5` is tagged and its containers are published. **Do not deploy it.**
It defaults codex phases to `--sandbox workspace-write`, and a codex phase cannot
write its deliverable at that level: `Edit` operations fail, no artifact is
produced, and the phase still reports `completed`. That silently removes the
verify gate from every run. Three executions ran ungated between 00:55 and 02:05
UTC (`exec-491d046e8db4`, `exec-89ceaffdb011`, `exec-7773369f9032`).

VPS is on **beta.4**, verified in the running image:
`['codex','exec','--json','--sandbox','danger-full-access','--skip-git-repo-check']`

#1157 is reopened. The per-phase mechanism is correct and stays; only the default
is wrong. The fix worth building is #1167's: let a phase publish its deliverable
without a filesystem write, which is the only route that makes `read-only`
viable for a verifier.

### #1153 is solved — do not re-investigate from scratch

The workspace container was never being killed. Its entrypoint aborts (exit 1)
when the session-store doctor cannot reach `http://100.112.178.5:18090/healthz`,
and the `docker exec` running the clone is then SIGKILLed (137) because its
container vanished. The API only ever recorded the transport's death.

Root cause is a **cold Tailscale DERP relay**: no direct path exists between the
VPS and the macmini, so the first request after idle costs ~7.2s (measured)
against ~0.017s warm. That is the entire intermittency.

Stopgap in place: systemd unit `storewarm` on the VPS pings healthz every 20s.
Zero setup failures since. The real fix is a direct Tailscale path, or a retry
with backoff in the doctor (which lives in agentic-primitives).

### Open, with exact next actions

- **#1065** — head `068efd39`, provenance clean, commit says "settle the launch
  marker on the exit status, not on the line". **Never verified** — its verify
  phase produced no artifact twice, both times due to the regression above. A
  review is running now on beta.4 (`exec-3d7c051f8c08`). Do not merge before it.
- **#1072** — merged. Its falsify phase wrote nothing, so the verdict came from
  the `investigate` phase (opus) via the report phase (sonnet) rather than from
  codex. Still cross-model and the mutation evidence is real, but weaker than
  the merge comment claimed. Noted on the PR.
- **#1154** — held on the experiment writeup overstating an invalid run (all six
  executions violated the pack's own validity rule; no gated run produced a
  final artifact). Also wants `Bash` dropped from `characterize` and `seams`.
- **#1071** — still blocked on #1146.
- **#1083 / #1026** — owner design calls. Do not dispatch.

### New issues filed tonight

#1157 (reopened), #1158, #1159, #1160, #1161, #1164, #1165, #1166, #1167.

The three that matter most for a stable v0.28.0, in order:

1. **#1167** — a phase producing no declared output artifact reports `completed`,
   silently removing the gate. Four occurrences. The `Edit success=False`
   signal existed in Lane 2 the whole time and nothing acted on it.
2. **#1161** — a verify phase wrote and pushed the change it certified. Still
   unmitigated in production, because the rollback restores the grant.
3. **#1164** — a timed-out phase records 0 tokens and $0.00 after reporting a
   real cost while running, so failed runs are free in the ledger.

### Measured, so nobody re-derives it

Per-workspace memory (n=398, `/root/ws-mem.csv`, sampler `wsmem`):
p50 281 MiB, p90 413 MiB, **max 1009 MiB against a 4 GB cap**.
Host 62 GB / 16 cores. Memory ceiling ~40+ concurrent; CPU ceiling 8-16.
**CPU binds first by ~3x** — the "~14, memory-bound" figure is wrong.
Recorded on #1126.

---

## Update 2026-09-04 ~06:00 UTC — beta.6 in flight

### Merged since the last update

- **#1065** — launch marker, after five rounds. The winning shape: mint the
  expected wrapper name BEFORE the stream exists and thread it to the command
  builder's `$0`, so the observer never learns authority from the stream.
- **#1168** — `#1146` fix. A `{`-leading line the agent echoed is no longer a
  protocol fault. **This is what unblocks #1071**, but only once DEPLOYED.
- **#1169** — sandbox default back to `full-access`, deliberately, with the
  reason in the code. Also fixed a real bug the review predicted from the test
  shape: `_build_phase_defs` never mapped `sandbox`, so any workflow created
  through the API lost its declared level.

Seven merges are now on main and NOT deployed: #1063 #1155 #1072 #1154 #1065
#1168 #1169. `v0.28.0-beta.6` is being cut to ship them.

### The beta.5 post-mortem, so nobody repeats it

beta.5 defaulted codex phases to `workspace-write`. A codex phase publishes its
deliverable by WRITING under `artifacts/output/`; the write was denied, no
artifact was produced, and the phase still reported `completed` — silently
removing the verify gate for ~70 minutes across three executions.

Root cause of MY error: the sandbox levels were validated on macOS. The sandbox
is the host's native engine (Seatbelt vs Landlock), so a level that permits a
write on Darwin can deny it in the Linux container. **Validating a sandbox on a
different OS than it runs on is not validation.**

#1170 is the same class, found while checking this: a launch-evidence test
asserts exit 127 for a bad shebang, which is Linux-only — macOS gives 1, so
main is red on any Mac while CI stays green.

### DEPLOY CHECKLIST — do not skip step 4

1. Merge the bump PR, tag `v0.28.0-beta.6 --prerelease --target main`.
2. `Release Beta` will report failure. Check WHICH job: the npm CLI publish
   fails every time (#1156, ENEEDAUTH) while all seven containers succeed.
   Container success is what matters.
3. On the VPS, `/root/.syntropic137/docker-compose.syntropic137.yaml` pins
   `syn-api` and `syn-gateway` by TAG (the other four are digest-pinned). Back
   the file up, bump both tags, `docker compose pull api gateway`, `up -d`.
4. **VERIFY IN THE RUNNING IMAGE, NOT BY TAG.** Dispatch a real workflow with a
   codex phase and confirm the phase produced an ARTIFACT:
   ```bash
   curl -su admin:$PW '.../executions/<id>' \
     | jq -r '.phases[] | "\(.name) \(.status) artifact=\(.artifact_id)"'
   ```
   A codex phase that runs 60-70s with ~100-175k tokens and `artifact=None` is
   the beta.5 signature. A healthy one runs minutes with 0.8-2.4M tokens and
   writes an artifact. The tag being green tells you nothing.

### VPS watchers (systemd units, restart if `inactive`)

- `storewarm` — pings the session store every 20s. **Load-bearing**: without it
  the cold Tailscale DERP relay costs ~7.2s on first request, the workspace
  entrypoint's healthz check times out, and the container exits 1 mid-clone
  (#1153). Zero setup failures since it went in; three in the hour before.
- `wsmem` — per-workspace memory to `/root/ws-mem.csv`.
- `wsdeath` — captures dying containers WITH their logs, in the window between
  the `die` event and removal. This is what solved #1153.

### Still open, ranked for the release

1. **#1167** — a phase producing no output artifact reports `completed`.
   Four occurrences. This is what let beta.5 run ungated for 70 minutes
   without anyone noticing.
2. **#1161** — a verify phase wrote and pushed the change it certified.
   Unmitigated: the rollback restored the grant.
3. **#1164** — a timed-out phase records 0 tokens and $0.00 after reporting a
   real cost while running.

**#1167 and #1161 have ONE fix between them**: give a phase a way to publish its
deliverable without a filesystem write. That makes `read-only` viable for verify
phases, which is the actual goal of #1157.

---

## Update 2026-09-04 ~09:00 UTC — backlog cleared, one deploy gap

### The queued backlog is done

Every item from this document is merged: #1063, #1155, #1072, #1154, #1065,
#1168, #1169, #1071, #1173. `#1083` and `#1026` remain owner design calls and
were never dispatched, as instructed.

### DEPLOY GAP — read this before assuming the VPS is safe

`v0.28.0-beta.6` is deployed and healthy, but **two merges landed after it was
tagged and are NOT on the box**:

```
#1173  the #1167 enforcement (a phase with no artifact now FAILS)
#1071  execution-detail live update, four blockers fixed
```

So on the VPS right now, a phase that produces no output artifact **still
reports `completed`**. The top release blocker is fixed in code and not in the
running system. Any run dispatched against this box is still exposed to the
silent-gate failure that made the beta.5 outage invisible.

Two ways forward, and the choice is the owner's:

1. **Cut beta.7 and deploy before promoting.** #1173 changes failure behaviour -
   phases that previously completed will now fail - and that is worth observing
   on a beta rather than discovering in a stable release. Validate the same way
   beta.6 was validated: dispatch a run and confirm a codex phase writes an
   artifact, then confirm a deliberately artifact-less phase FAILS.
2. **Fold it into v0.28.0** and validate at promotion.

### Release readiness, measured

`#1057` (main -> release, draft) on current main: **46 pass, 2 fail, 0 pending.**
Both failures are one thing, counted twice:

```
##[error] Refusing to merge prerelease version '0.28.0-beta.6' into 'release'.
```

`version-check` itself reports `OK: All 11 files at v0.28.0-beta.6` and
`OK: 0.28.0-beta.6 > 0.27.0`. Every substantive gate - changelog, codegen-sync,
docker-dry-run, osv-scan, pip-audit, dependency-review - passes. The only
blocker is the version bump, which is the owner's step. 276 commits ahead of
`release`.

### Known defects shipping with v0.28.0 unless addressed

- **#1161** — a codex verify phase can still write and push the change it
  certifies. Unmitigated: rolling back beta.5 restored the grant. Closing it
  needs a deliverable channel that does not require a filesystem write, which
  is the same fix that would let a verify phase run `read-only`.
- **#1172** — a projection version bump blackouts execution visibility for
  ~9 minutes on deploy. Runs are uncancellable during it and `/health` reports
  `healthy` with `is_catching_up` and `lag` both null.
- **#1164** — a timed-out phase records 0 tokens and $0.00 after reporting a
  real cost while running. In flight.
- **#1166** — a phase prompt names an input path no phase produces. NOT closed
  by #1173's validator: that is an artifact-TYPE check, and this is a phase-ID
  reference in prose.
- **#1170** — a launch-evidence test asserts a Linux-only exit code, so the
  suite is red on macOS while CI is green. In flight.

### The pattern worth carrying forward

Three of tonight's defects are the same habit: **the platform asserts a property
it does not check.**

- #1167 — a phase reports `completed` without producing its declared output
- #1161 — a "verifier" writes the change it certifies
- #1094/#1107 — a "cross-model" gate cannot see which model ran any phase

Each was invisible from inside the system claiming the property. #1173 closed
the first. The other two are open.

---

## Update 2026-09-04 ~13:10 UTC — beta.7 deployed AND verified

### The release blocker is now fixed, deployed, and proven in production

`v0.28.0-beta.7` carries #1173, #1071, #1174, #1175. Both validation checks
were run against the running image, not inferred from the tag:

**1. A codex phase still writes its artifact** (the beta.5 regression check):
7m39s, 2,548,968 tokens, artifact written, while reading `.tsx` throughout.
The beta.5 failure signature was 60-70s, ~100-175k tokens, `artifact=None`.

**2. The #1173 enforcement actually fires**, tested by invoking it inside the
deployed container rather than reading the code:

```
DECLARED+EMPTY -> raised PhaseProducedNoDeclaredOutputError   OK
NODECL+EMPTY   -> no raise                                    OK (true negative preserved)
```

Both halves matter: the gate fires when a phase declares output and produces
none, AND stays silent for a phase that legitimately declares nothing. An
over-enforcing fix would have broken every phase without declarations.

No projection version changed on this deploy, so #1172's blackout did not fire
- all 25 checkpoints converged at 9136. That confirms the blackout is specific
to version bumps, not to every deploy.

### #1179 — I orphaned two executions deploying, and it cost more than time

`docker compose up -d api gateway` killed two in-flight runs (~45 min of agent
work). Reconciliation handled it correctly, marking both `failed` with an
accurate cause rather than leaving them stranded.

But one of them had already **pushed a commit and opened PR #1178** before
dying, and its verify phase never ran. So a deploy can leave an open PR that
carries real code, looks finished, and has had no review. Nothing on the PR
distinguishes it from a completed one.

**Check the queue before deploying.** There is no drain and no warning:

```bash
curl -su admin:$PW '.../api/v1/executions?status=running&page_size=10' | jq .total
```

### Release readiness

`main` is now identical to what is deployed. `#1057` gates: 46 pass, 2 fail,
both being the prerelease guard refusing `0.28.0-beta.7` into `release`. The
only remaining step is the version bump to `0.28.0`, which is the owner's.

### Still open, in the order I would rank them

1. **#1161** — a codex verify phase can still write and push the change it
   certifies. Ships with v0.28.0 unless addressed. Its fix is the same one
   #1167 wanted: a way for a phase to publish its deliverable without a
   filesystem write, which is also what makes `read-only` viable for a verifier.
2. **#1179** — deploys orphan in-flight work, no drain, no warning.
3. **#1172** — projection-rebuild visibility blackout (~9 min, measured). The
   observability half is in flight; the architectural half is a design call.
4. **#1166** — a phase prompt can name an input path no phase produces.
5. **#1176** — the workflow-detail API omits artifact declarations. In flight.

### The pattern worth keeping

Four defects this batch were one habit: **a proxy standing in for a fact.**

| defect | proxy | fact |
|---|---|---|
| #1065 | exit code | did the process exist |
| #1065 | a nonce read from the stream | who is the wrapper |
| #1159 | a count | how many exist, vs one page |
| #1164 | token magnitude | did a terminal result arrive |
| #1176 | a missing key read as null | does the phase declare nothing |

And three more were a second habit: **the platform asserting a property it does
not check** — #1167 (`completed` without output), #1161 (a "verifier" that
writes), #1094/#1107 (a "cross-model" gate blind to which model ran).

---

## Update 2026-09-04 ~23:10 UTC — the release blocker is the query fix

### The owner's release gate

v0.28.0 will not be cut until the executions and sessions list pages can show
all of history. Everything else on this document is done.

**Acceptance criterion, corrected.** My first version was wrong and verification
caught it. I said "the number of visible rows must change when the window
widens". With a 50-row page and more than 50 matches in BOTH windows, widening a
lower bound correctly leaves the newest first page IDENTICAL. A test built to my
criterion fails on correct software.

The real criterion:

```
fixture: more than one page of matches in BOTH windows (e.g. 120 executions, 80 within 7d)
mount ?timeWindow=7d, widen to All
  total MUST change            80 -> 120
  first page rows MAY match    <- correct; do NOT assert they differ
  paging to the last page MUST reach a row outside the 7d window
```

That last line is what proves history beyond page one is reachable.

### State of the work

- **#1186 MERGED** - the API half. One shared contract on both endpoints:
  `page`, `page_size`, `started_after`, `started_before`, `statuses`, `q`;
  `total` = matching rows; `status_counts` facets; `limit` kept as a deprecated
  alias on `/sessions`. Verified through `create_app()`, not a bare harness.
- **#1190 OPEN** - the dashboard half. Behaviour verified (both required
  mutations killed, 194 dashboard tests, 4006 python tests). **Red on
  Architectural Fitness**: `useServerList` at cognitive 19/15, cyclomatic 11/10,
  116/100 LOC, and `SessionList` at 104/100. A decomposition run is in flight.
  Do NOT raise a threshold or add an exception.

### The timezone contract, decided

A caller's timezone-less bound is **rejected with 422**. A stored naive row is
**coerced to UTC**. Same input shape, opposite treatment, and the reason is in
the code: *"This is only defensible because there is a caller to tell.
Timestamps already IN the store get the opposite treatment for the opposite
reason, where nobody is around to be asked."*

`/sessions` returned 500 for a naive bound on beta.7 and earlier - that was a
live production defect (#1183), not something this work introduced.

### Also merged since the last update

#1173 #1071 #1174 #1175 #1178 #1180 #1181(pending owner) #1186 #1189, plus the
beta.6 and beta.7 bumps. Fifteen substantive PRs in 24 hours.

**#1189 is the one worth knowing about**: `agent_session_ids` now reaches the
execution read path, so an execution can finally be traced to the agent
transcripts it produced. Before it, an audit of agent behaviour was impossible -
the transcripts were in the session store and simply not addressable. The
`null` (exporter did not report) versus `[]` (confirmed none) distinction is
preserved and is the thing to not break.

### Awaiting the owner

- **#1181** - the pre-deploy guard. Touches `infra/`, which CODEOWNERS assigns
  to the owner, and the ruleset requires code-owner review. Do NOT `--admin`
  past it: it gates deploys, which is exactly what that control is for.
- **v0.28.0 promotion** - `#1057`, main->release. 46 of 48 gates pass; both
  failures are the prerelease guard refusing `0.28.0-beta.7` into `release`.
  One version bump from promotable.
- **#1161's publish channel** - the one design decision that closes both #1161
  and completes #1157. How should a phase publish its deliverable without
  writing a file? Do not pick one inside a bug fix; that is how beta.5 happened.

### New issues filed today worth reading

- **#1184** - a phase can commit without pushing and still report `completed`.
  Decided approach: push to `refs/syn/lost/<execution>/<phase>` then FAIL, so the
  work survives without landing half-done code on a reviewed branch.
- **#1187** - `open_pr` fails in ~30% of runs: shortest timeout (600s) on the
  phase with the most setup-to-work overhead. It provisions a whole workspace
  and clones the repo to read one file and call `gh`.
- **#1188** - the untyped-dict ratchet counts a literal regex, so
  `Mapping[str, object]` satisfies it without typing anything.
- **#1185** (fixed by #1189), **#1183** (timezone 500), **#1176** (fixed).
