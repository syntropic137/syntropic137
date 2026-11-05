# Plan: first end-to-end remote run, a Scripted Agent on a repo-free workflow, on E2B (#1918)

**Status:** approved 2026-10-27 by syn137_orchestrator with the defaults below, except the items
listed under "Owner questions". Step H of `docs/research/2026-10-08-remote-executor-e2b.md` §5.
Epic #1612, umbrella #350. Sequencing rulings: the next agentic-workspace release (main ->
release) waits until AW#93 (`/opt/agentic/version.json` in every image) and PR 1 land, so one
release and one pin bump carry AW #117, #93 and PR 1. #2150 waits for that pin.

**Read on:** `origin/main` at `fbee4e1bc` (after #2153). Branch-only material, cited by ref:
#2150 (`origin/feat/e2b-docker-template-ref`, open, stacked on open #2149), #2078
(`origin/feat/1916-spool-routing-remote`, draft), AW #117 (open). The AW submodule is pinned at
`fb696fd8`. `file:line` citations drift as PRs land.

---

## Summary

- One execution of a two-phase, repo-free fixture workflow runs on an E2B sandbox built from the
  pinned **scripted-agent** stub image, claimed by the E2B Executor through the Run Queue
  (`workload = 'scripted'`), with no host credential reaching the sandbox.
- **Four PRs.** One in agentic-workspace (the stub becomes E2B-ready) and three in syn137: domain
  truth for a scripted run, the E2B kit proving what it runs, then the acceptance run itself as a
  local `just` target calling a tested Python script.
- Real E2B only in that local target and in `just e2b-template-build`. CI uses `SandboxDouble`
  and the existing recording fakes.
- **Six findings contradict the brief's assumptions** (see "Blockers"). Two are F-scope gaps that
  #2078 as drafted does not close, and they block the acceptance run, not the code PRs.

---

## Acceptance map

| #1918 acceptance item | Delivered by | On `main` | Missing |
|---|---|---|---|
| Run reaches `completed` | E2B Executor claims a `scripted` row (#2143 `can_run`, `postgres.py:46`); agent stream through provider operations (B, #1912; AW `E2BWorkspaceProvider.status/cancel`, `providers/e2b.py:348-363` at `fb696fd8`) | claim clause, executor wiring (`execution_host_runner.py:104-143`), stream | the **producer** of `workload='scripted'` (`run_reservation.py:45` never passes it); `SYN_SCRIPTED_AGENT_PROFILE` injection; an executor that may start outside test (blocker B1) |
| `isolation_type` reported as E2B | `BackendKit.e2b` sets `isolation_type="e2b"` (`backend_kit.py:79-101`); handle carries it (`adapter.py:472`) | on the handle and on `IsolationStartedEvent` of the **never-saved** `WorkspaceAggregate` | not durable on the execution stream and not in execution detail. PR 3 adds it to `WorkspaceProvisionedForPhaseEvent` and the phase detail |
| Output artifacts collected | C (#1913): `copy_from` through `read_files`, pattern `artifacts/output/**/*` (`adapter_copy.py:343`); the stub writes `/workspace/artifacts/output/<phase>.md` (AW `scripted_agent/cli.py:102-104`) | yes | nothing. PR 4 asserts it live |
| Transcript archived through the F path | F (#1916 / #2078): `CaptureSpool.backend='e2b'`, `SandboxSpoolRecovery`, pause until drained | not on main (#2078 draft) | **E2B write side** (blocker B2) and **a transcript to capture** (B4, PR 1) |
| Image manifest on persisted `WorkspaceProvisionedForPhase`, read back after replay, matching the template's expected manifest hash | `WorkspaceProvisionedForPhaseEvent.image_manifest` (`WorkspaceProvisionedForPhaseEvent.py:41`), `ImageManifestReading` (`ImageManifestValueObjects.py`) | the reading (read/absent/unreadable) and its replay | **no image ships `/opt/agentic/version.json`** (AW#93 open, B3); the reading keeps no hash of the bytes and nothing compares with an expected hash (PR 3); the expected hash has no in-repo home (PR 3, D4) |
| No credential observed (D's scan, live path) | D (#1914): `NO_CREDENTIALS`, `test_1914_no_credentials_leaks_nothing.py` | the scan, **as test-local code** (`_Recorder`, `:90`) on fakes | the scan as a production module running on the live E2B client (PR 3, Credential Tripwire) |
| No sandbox with its `syn.execution_id` left in the E2B list | labels to metadata (`adapter.py:186`); `E2BRecoveryKit` list (`recovery_kit.py`) | yes | the live assertion after F's drain-then-kill (PR 4) |
| Negative control: a `HostCredentials` kit fails D's scan on the live path | Tripwire refuses the call | no | a dev-only switch to run the E2B kit under `HostCredentials` with invented credentials (PR 4, D7) |

---

## Dependencies

| Dependency | Status 2026-10-27 | What H needs from it |
|---|---|---|
| A #1911, B #1912, C #1913, D #1914, E #1915 | closed | as on main |
| G #1917 slices 1-2 (#2143, #2153) | merged | `RunWorkload`, `can_run`, E2B Executor, Recovery Kit, Outage Breaker |
| F #1916 (#2078) | **draft**, last push 10-23; assumed to land first | (a) E2B capture **write** side, (b) production `RecoverySandboxes`, (c) removal of `_refuse_unverified_e2b_reap` (`execution_host_runner.py:158-175`). The draft has none of the three (B1, B2) |
| #2149 AW pin `896449c5` + #2150 template reference | **both open**, #2150 stacked on #2149 | `just e2b-template-build`, `template_ref.py`, receipt. PR 3 generalises it |
| AW #117 publish scripted-agent | **open** | a signed `agentic-workspace-scripted-agent` digest. Must publish the PR 1 content (B5) |
| AW#93 version.json | **open** | PR 1 closes it for the stub image only |
| e2b SDK in syn137 | absent from `uv.lock`; ad-hoc `uv run --with e2b==2.52.0` in `test-e2b` | PR 3 (D2) |

---

## Blockers that contradict the brief

- **B1. The E2B Executor cannot start on a durable stack, and #2078 does not change that.**
  `_refuse_unverified_e2b_reap` raises outside `uses_in_memory_stores` (test or offline,
  `config.py:729-731`). Offline means in-memory stores, so no replay is possible. #2078 does not
  touch `execution_host_runner.py`. Its body says the production `RecoverySandboxes` adapter is
  "not in this PR" and `_wiring_inventory.py` passes no `remote_recovery`. **The acceptance run
  (PR 4) waits on a finished F that confirms reaps by recorded sandbox id and deletes the guard.**
  The code PRs do not.
- **B2. Nothing writes an E2B capture spool.** `BackendKit.e2b` "never captures"
  (`backend_kit.py:79-84`, `capture_source_instance_id=None`). #2078 routes **recovery** of
  `sandbox-spool/1` rows and says "the executor that writes such rows is step G". #2153 (G) did
  not write them. The write side is unowned: in-sandbox spool dir and capture env, the
  `CaptureSpool` row with `backend/executor_id/sandbox_id`, and pause-until-drained teardown.
  **Recommendation:** it belongs to F (research §5 F: "pause-until-drained teardown"). Confirm
  with the F agent before PR 4.
- **B3. No workspace image ships `/opt/agentic/version.json`** (AW#93 open; `git grep` at AW
  `origin/main` finds no producer). Every reading on main is `ABSENT`. #2150's
  `DockerBaseImageReader.manifest_hash` `docker cp`s that file, so `just e2b-template-build` fails
  today on toolchain too. C closed without the expected-hash comparison its acceptance named.
- **B4. The stub produces no transcript to capture.** The replayer streams to stdout and writes
  only the artifact (AW `scripted_agent/cli.py`). It writes no native transcript, and claude-cli,
  its base, ships no `apss-session-exporter` (`claude-cli/Dockerfile:383-390`). So a capture of
  the stub would archive nothing.
- **B5. AW #117 publishes the stub as it is today.** If it releases before PR 1, the pin gets an
  image without B3/B4, and a second AW release plus pin bump follows.
- **B6. Decision 5 conflicts with #2150.** The research ties a `NoCredentials` kit to the stub
  digest. #2150 points the E2B kit (`NoCredentials` by construction) at a nested-Docker
  **toolchain** template. Both cannot hold (D5).

---

## Design

### The scripted run is domain truth (PR 2)

- **Contract home (D1).** Move the contract models (`ScriptedAgentProfile`, `ScriptedPhase`,
  `ScriptedStream`, workloads, side effects, `ReviewVerdictName`, the env constant) from
  `packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.py` to
  `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/scripted_agent_profile.py`.
  The event types it, and dependency direction forbids syn-domain importing syn-perf.
  - `for_workflow`, `render_artifact` and `planned_run` depend on `syn_perf.loadtest.handoff` and
    `implement_v3_artifacts`. They stay in syn-perf as free functions over the domain model.
  - The schema JSON moves with the model, and the regenerated schema must be **byte-identical**.
    AW `scripted_agent/contract/PROVENANCE.md` pins its SHA-256 `e16acbe0…`, and only the
    recorded source path changes.
- **Request.** `ExecuteWorkflowRequest.scripted_agent_profile: ScriptedAgentProfile | None`
  (`routes/executions/commands.py:250`).
  - 422 unless the profile's phase ids equal the workflow's.
  - 422 unless `SYN_SCRIPTED_RUNS_ENABLED` (D3).
  - Then `just codegen`.
- **Event.** `WorkflowExecutionStartedEvent.scripted_agent_profile: ScriptedAgentProfile | None =
  None`, written only when set, like `eval_id` (`WorkflowExecutionStartedEvent.py:49`). Carried
  on `ExecuteWorkflowCommand` and `StartExecutionCommand`, and folded into
  `StartPins.scripted_agent_profile` (`start_pins.py:77`), so `run_claimed` reads it back from the
  stream.
- **Workload.** `reserve_run` and `open_start` (`run_reservation.py:28-77`) pass
  `workload=RunWorkload.SCRIPTED` when the pins carry a profile, else `AGENT`. The port already
  takes it (`ExecutionRunQueuePort.py:256`). A resume inherits its parent's profile.
- **Injection.** `WorkspaceProvisionHandler._launch_for` (`:709-746`) adds
  `SCRIPTED_AGENT_PROFILE_ENV` beside `repo_identity_env`. That is the one provider-independent
  point, so codex phases get it too. `phase_workspace.py:270` passes
  `aggregate.start_pins.scripted_agent_profile` to `handle`. The profile is not a credential, so
  `NoCredentials` passes it.

### The E2B kit proves what it runs (PR 3)

- **Stub pin.** Add `SCRIPTED_AGENT_IMAGE` to
  `packages/syn-shared/src/syn_shared/settings/workspace_images.py`. It is a separate pin, never a
  `WorkspaceImageProvider` member, so it cannot be selected as a production workspace image. It
  is `repository@sha256` from the AW release that publishes PR 1 (AW #117's job), with a
  provenance comment block like the existing ones and `check_pinned_image_channels.py` coverage.
- **Expected manifest hash (D4).** Pin `SCRIPTED_AGENT_MANIFEST_HASH`
  (`sha256:` of its `version.json`) beside the digest, written at pin time from the verified
  image. It is a reviewed pin, not an operator setting.
- **Template, reusing #2150.** Generalise `template_ref.py` and `scripts/e2b_template_build.py`
  to a `TemplateImage` (name, ref, digest, expected manifest hash, optional `DockerEngine`):
  - `just e2b-template-build --image scripted-agent` builds with no Docker engine, named
    `syn137-scripted-agent-<digest12>`. The nested-Docker path keeps its name and behaviour.
  - The build **refuses** when the image's `version.json` hash differs from the pin. Today it
    only records the hash. There is no second template path.
- **Stub-only under NoCredentials (D5).** `BackendKit.e2b` refuses to construct unless the
  template equals the derived scripted-agent name. The name carries digest12 of the pinned stub,
  which is research decision 5's tie. The drift guard runs for this template as #2150's runs for
  nested Docker.
- **Manifest comparison.**
  - `ImageManifestReading` gains `file_sha256: str | None`, set exactly when the bytes were read.
    It uses the same function AW `manifest_hash` uses: hash the file, never the parsed fields.
  - `WorkspaceProvisionedForPhaseEvent` gains `expected_manifest_hash: str | None` (from the kit)
    and `isolation_type: str | None` (from the handle). Both default `None` for replay.
  - A mismatch is recorded and flagged, never dropped. Execution detail shows all three per phase.
    That bumps the `get_execution_detail` projection version (`projection.py:200` is v20).
- **Credential Tripwire (D6).**
  - Lift D's recorder and scan out of `test_1914_no_credentials_leaks_nothing.py` into
    `packages/syn-adapters/src/syn_adapters/workspace_backends/credential_scan.py`:
    `HostCredentialSet.from_settings()` (configured values plus the issuer prefixes `sk-ant-`,
    `ghs_`, `ghu_`, `github_pat_`, `syn_pat_`) and `scan(channel, payload) -> list[CredentialHit]`
    (kind and channel, never the value).
  - `test_1914` is re-pointed at it, so D's scan and the live scan are one function.
  - `packages/syn-adapters/src/syn_adapters/workspace_backends/e2b/credential_tripwire.py`:
    `CredentialTripwireE2BClient` wraps the client the way `BreakerE2BClient` does
    (`breaker_client.py`). It scans `create.metadata`, `start` env and command, and `write_bytes`
    content.
  - A hit raises `CredentialObservedError(WorkspaceProvisionError)` **before** the call, so the
    value never leaves the host, and logs to Lane 2.
  - It is wired in `build_workspace_service` (`_wiring.py:325-347`) around the breaker client for
    every E2B workspace. Until #1919 any host credential reaching E2B is a leak.
- **e2b SDK (D2).**
  - Add a `syn-adapters` extra `e2b = ["agentic-isolation[e2b]"]`. AW already pins
    `e2b==2.52.0` exactly (`agentic_isolation/pyproject.toml:31-33`).
  - Add `e2b = "2026-10-02T00:00:00Z"` to root `exclude-newer-package` (`pyproject.toml:62`),
    matching the `--exclude-newer` the just targets use today.
  - The syn-api image installs the extra. #2153's Recovery Kit already ImportErrors without it.
  - `test-e2b` and `e2b-template-build` drop `--with`.

### The acceptance run (PR 4)

- **Fixture.** `workflows/probes/remote-first-run/workflow.yaml`, two claude phases:
  - `requires_repos: false`, and `clone_repos: false` on every phase.
  - `output_artifacts: [markdown]`, explicit `model`, no review verdicts, so there is no
    certified ending.
  - The profile is built by syn-perf's `for_workflow` at `tier="node"`, which gives every phase
    `ReportOnly` (`scripted_agent_profile.py:498-525`). `fixture_repo` is required by the
    contract but never touched: there are no repos and no push.
- **Script.** `scripts/e2b_first_remote_run.py`, tested in `scripts/tests/`, with collaborators
  behind Protocols as in #2150. Steps, each fail-closed:
  1. Preflight: API up; the E2B pool registered (`provider=e2b`, `supplies_credentials=false`);
     `SYN_E2B_TEMPLATE` equals the derived stub name.
  2. Register the fixture and start with the profile. Wait on the execution SSE stream for a
     terminal state, with a deadline.
  3. `GET /executions/{id}`: `completed`; every phase `isolation_type == "e2b"`, one output
     artifact each, `image_manifest.state == read`, and
     `file_sha256 == expected_manifest_hash == SCRIPTED_AGENT_MANIFEST_HASH`.
  4. **Fresh-process replay:** a child process loads the execution aggregate from the event
     store with an empty memory, and finds the same manifest and hashes on every
     `WorkspaceProvisionedForPhase`.
  5. Transcript: the session's archived transcript exists and is non-empty, its model is
     `syn-scripted-agent`, and the spool row is `drained`. This needs F (B2).
  6. `E2BRecoveryKit.list({"syn.execution_id": id})` is empty after the drain.
  7. `--negative-control`: refuses unless every credential env var holds an invented `FAKE`
     marker. It starts the API's E2B kit under `HostCredentials` (D7) and asserts the run
     **fails** with `CredentialObservedError` naming `start.env`.
- **Target.** `just e2b-first-run *ARGS` is one line, `uv run python
  scripts/e2b_first_remote_run.py {{ARGS}}`, with no logic in the justfile. Local only, documented
  in `docs/deployment/e2b.md`.

---

## Ordered PRs

| PR | Repo | Content | Depends on | Size |
|---|---|---|---|---|
| **1** | agentic-workspace | The stub is E2B-ready: `version.json`, a native transcript, the exporter | none; must merge **before** the AW release carrying #117 | S-M (~250 LOC + smoke) |
| **2** | syn137 | A scripted run is domain truth: contract to syn-domain, request, start event, `StartPins`, `workload` at reserve, profile injection, setting, codegen, vocabulary | none (lands dark: the setting defaults off) | M-L (~600 LOC, half tests) |
| **3** | syn137 | The E2B kit proves what it runs: stub pin and manifest hash, generalised template build, stub-only `NoCredentials` kit, manifest hash and `isolation_type` on the event and in detail, Credential Tripwire, e2b extra | 1 (published + pinned), #2150, 2 not required | L (~800 LOC) |
| **4** | syn137 | First remote run: fixture, script, `just e2b-first-run`, negative-control switch, docs, results written back into the research doc §5 H | 2, 3, **finished F (B1, B2)** | M (~450 LOC); one owner run (~$0.10 E2B) |

### Exit tests

Each test is named for what it asserts. "Reverted" names what the test sees when the change is
undone. Each PR carries `.mutations/` (≤20 patches, non-test source, `killers.tsv`). Each patch
is asserted applied, and each killing test passes on clean HEAD.

**PR 1 (agentic-workspace)**

- Dockerfile: `version.json` from build args (`AGENTIC_BUILD_COMMIT`, manifest version) plus
  `manifest_digest = sha256(manifest.yaml)`. COPY the `apss-session-exporter` pinned by digest
  and cosign-verified, as omni does (D8).
- Replayer: writes the replayed stream as the harness's native transcript. For claude that is
  `$CLAUDE_CONFIG_DIR/projects/<cwd-slug>/<session>.jsonl`, for codex its sessions file. The
  model is rewritten to `syn-scripted-agent`. This is harness knowledge, so it lives in AW (CLAUDE.md
  boundary).
- Tests:
  - `test_the_image_carries_a_version_manifest_the_platform_can_read`: the smoke parses
    `/opt/agentic/version.json` into syn137's `ImageManifestContent` field set, and
    `manifest_hash` is stable across two reads. Reverted: file missing, smoke fails.
  - `test_a_replayed_claude_phase_leaves_a_native_transcript_in_the_spool`: with
    `AGENTIC_SESSION_STORE_SPOOL` set, the partition holds one JSONL equal to the replayed
    stream. Reverted: empty partition.
  - `test_a_replayed_codex_phase_leaves_a_native_transcript` (same, codex).
  - `test_the_session_store_doctor_passes_in_the_stub`: `exporter_present` is true and the
    capability is not degraded. Reverted (no exporter): `degraded`.
  - Existing `test_contract_parity.py` unchanged and green.

**PR 2**

- `test_a_start_request_with_a_profile_records_it_on_the_start_event`: real handler, in-memory
  store; the event round-trips the profile byte-equal. Reverted: `None`.
- `test_a_start_event_written_before_the_field_replays_with_no_profile`: frozen v1 JSON.
- `test_a_claimed_run_reads_its_profile_back_from_the_stream`: `run_claimed` with empty memory
  injects the same JSON. Reverted (read from request, not pins): missing.
- `test_a_scripted_start_reserves_a_scripted_row` (Postgres): `execution_runs.workload =
  'scripted'`. Reverted: `'agent'`.
- `test_a_no_credentials_executor_claims_a_scripted_start_end_to_end` (Postgres): `reserve`
  through the real processor, then a `supplies_credentials=false` pool claims it.
- `test_every_phase_of_a_scripted_run_is_launched_with_the_profile_env`: claude and codex phases
  both. Reverted (injected inside `build_agent_env`): the codex phase lacks it.
- `test_the_profile_env_reaches_a_no_credentials_workspace_and_no_credential_does`: extends the
  `test_1914` channels.
- `test_a_profile_whose_phases_differ_from_the_workflow_is_refused_with_422`.
- `test_a_profile_is_refused_unless_scripted_runs_are_enabled`.
- `test_the_moved_contract_generates_the_vendored_schema_byte_for_byte`: SHA-256 equals AW's
  `PROVENANCE.md`. Reverted (any field drift): the digest differs.
- `test_a_resume_inherits_its_parents_profile_and_workload`.

**PR 3**

- `test_a_no_credentials_e2b_kit_refuses_a_template_not_named_for_the_pinned_stub`, including
  the #2150 nested-Docker name. Reverted: it constructs.
- `test_the_stub_template_name_carries_the_pinned_stub_digest` and
  `test_the_nested_docker_template_name_is_unchanged` (no rename of live templates).
- `test_the_template_build_refuses_an_image_whose_manifest_hash_differs_from_the_pin` (fake
  reader). Reverted: a receipt is written.
- `test_the_provisioned_event_records_the_manifest_bytes_hash_and_the_expected_hash`.
- `test_an_altered_manifest_is_recorded_and_flagged_not_dropped`.
- `test_the_manifest_hashes_and_isolation_type_survive_a_fresh_process_replay` (real event
  store, `integration`): the C acceptance shape. Reverted (field dropped from the command):
  `None`.
- `test_an_event_written_before_the_fields_replays_with_none`.
- `test_execution_detail_shows_isolation_type_and_manifest_match_per_phase`.
- `test_the_tripwire_refuses_a_start_whose_env_carries_a_host_credential`: the value is never
  passed to the wrapped client, and the error names kind and channel but not the value.
  Reverted: the double receives it.
- `test_the_tripwire_scans_write_bytes_and_create_metadata`.
- `test_d_scan_and_the_tripwire_are_one_function`: `test_1914` imports `credential_scan.scan`.
- `test_production_wiring_wraps_every_e2b_client_in_the_tripwire`: constructs the real
  `build_workspace_service` with `SYN_E2B_ENABLED`. Reverted: an unwrapped client.
- `test_a_host_credentials_e2b_kit_is_caught_by_the_tripwire` (`SandboxDouble`): the CI shape of
  the negative control.
- `test_the_recovery_kit_imports_with_the_e2b_extra_installed` (replaces the ImportError note in
  #2153).

**PR 4**

- `scripts/tests/test_e2b_first_remote_run.py`, fakes only:
  - `test_the_run_passes_only_when_every_acceptance_item_holds`, table-driven, one row per item.
    Each row flips one fact (status, isolation, artifact count, a hash, replay, transcript,
    leftover sandbox) and the script exits 1 naming it.
  - `test_the_negative_control_refuses_real_looking_credentials`.
  - `test_the_negative_control_passes_only_when_the_run_fails_on_a_credential`.
  - `test_the_replay_check_runs_in_a_fresh_process`: a child pid, not the script's.
- `test_the_host_credentials_switch_is_refused_outside_development` (settings validator).
- `test_the_fixture_workflow_clones_nothing_and_needs_no_repo`: parses the YAML. Every phase is
  `clone_repos: false`, and `for_workflow` gives `ReportOnly` everywhere.
- **Owner run (local, real E2B):** `just e2b-template-build --image scripted-agent`, then
  `just e2b-first-run`, then `just e2b-first-run --negative-control`. Output is pasted into the
  PR and written back into research §5 H.

---

## Decisions (defaults recommended; ruled 2026-10-27)

Ruled by syn137_orchestrator: D1-D8, D10, D11 accepted as recommended. D5 accepted: a
`NoCredentials` E2B executor runs only the stub template, and the nested-Docker template
(#2150) is for brokered-credential agents after #1919. D9 is an owner question (below).

1. **D1 Contract home.** ★ Models in syn-domain `aggregate_execution/`, builders stay in
   syn-perf. Alt: syn-shared, which has no domain types.
2. **D2 e2b SDK.** ★ A `syn-adapters[e2b]` extra pinned `e2b==2.52.0`, a per-package
   `exclude-newer`, installed in the syn-api image. Alt: a dev group only, which keeps #2153's
   Recovery Kit broken in the image.
3. **D3 Who may start a scripted run.** ★ `SYN_SCRIPTED_RUNS_ENABLED` (default false). A scripted
   profile claimed by a credentialed Docker pool runs the real image and spends tokens while
   labelled scripted. #2143 lets credentialed pools claim `scripted` rows.
4. **D4 Expected manifest hash.** ★ Pinned in repo beside the stub digest. Alt: an operator
   setting copied from the template receipt.
5. **D5 NoCredentials E2B kit runs only the stub template.** ★ Yes (research decision 5). The
   nested-Docker toolchain template (#2150) becomes runnable only under `BrokeredCredentials`
   (#1919). This must be settled before #2150 merges.
6. **D6 Tripwire mode.** ★ Refuse the call (fail closed). Alt: record only.
7. **D7 Negative-control switch.** ★ `SYN_E2B_KIT_CREDENTIAL_POLICY=host` refused by the settings
   validator unless `APP_ENVIRONMENT=development`. The script refuses unless every credential is
   an invented `FAKE` value.
8. **D8 Stub exporter.** ★ COPY the pinned exporter into the stub, which keeps AW #117's
   claude-cli base. Alt: rebase the stub on omni-agent.
9. **D9 GHCR visibility** of `agentic-workspace-scripted-agent`. ★ Public. A private-GHCR
   template build is unproven (Q5), and #117 warns it may default private.
10. **D10 Isolation value.** ★ Record the handle's `"e2b"` now, and add
    `IsolationBackendType.E2B` (research §8 item 4) in the same PR.
11. **D11 B2 owner.** ★ F writes E2B spools. H does not absorb it.

### Owner questions (not ruled by the orchestrator)

Anything about spend, the E2B account, data leaving our systems, or deleting templates.

1. **D9 GHCR visibility.** Make `agentic-workspace-scripted-agent` public (★), as the other
   workspace images are? The image holds recorded replays only, no credentials.
2. **E2B spend for PR 4.** The acceptance run and its template build spend E2B credit on the
   owner's account (two sandboxes of a few minutes per run, bounded by the breaker and
   `SYN_E2B_TIMEOUT_SECONDS`). Run it locally with the owner's key: yes or no, and any cap.
3. **Test templates.** Builds create E2B templates that nothing deletes. Keep, or delete after
   each verified run?

---

## Risks

- **AW release ordering (B5).** PR 1 must be in the release that first publishes the stub.
  Otherwise there are two AW releases and two pin bumps. Per memory, an AW pin bump needs a live
  run.
- **Projection rebuild.** The `get_execution_detail` version bump in PR 3 rebuilds that
  projection on deploy. Group it with other projection-version changes in the next beta.
- **Schema parity drift.** Any model edit while the contract moves changes AW's vendored digest.
  PR 2 moves the contract only and changes no fields.
- **List lag.** The final listing trusts E2B's metadata list, the limit #2153 documents. F's
  recorded-id confirmation is what closes it. Until then PR 4 also asserts `lookup(sandbox_id)`
  is gone for each recorded sandbox.
- **Cost.** One run is two sandboxes of a few minutes each. The breaker and
  `SYN_E2B_TIMEOUT_SECONDS` bound spend.

## Out of scope

- Credentials for remote (#1919), egress (#1794), the unpushed-work guard (scripted runs push
  nothing), and the AW#93 producer for the claude-cli, omni and toolchain images.
- Load tests on E2B at N > 1, and the syn CLI flag for profiles (the API field is enough for H).

## Verification

- `just qa-ci` after the last edit of each syn137 PR. Mutation evidence per PR. Codex review,
  two passes max.
- PR 4's owner run is the only real-E2B step. Its output is the acceptance record for #1918.
