# Plan (final): provider operation contract (plan steps B1 + B2 design)

This is the revised plan for the docs-only PR that adds
`docs/plans/20261013_provider-operation-contract.md` to syntropic137. It stands alone: it carries
the problem, every decision, the contract map, the schema delta, the protocol delta, the recipe
design, the ordered PR list with exit tests, and how each cross-model review finding was disposed.

## 0. Baseline and how evidence was gathered

| Tree | Commit | Source |
|---|---|---|
| syntropic137 `origin/main` | `fd8ffd7a6aef524522884f9022009350d4b341da` (the review's baseline). The research used `5a1ef5bf8`. | Every syntropic137 line cited below was re-read in the working tree in this phase. Each one I cross-checked against the review's citations matched, e.g. `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:225`, `:342`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:176` |
| `lib/agentic-workspace` (AW) gitlink | `5c4e5595e6ff55ca0d07e94776bb2237786e2b16` | Unchanged between both baselines (research, review) |
| APSS spec | rev `18d55b231e7d06b509386b2599f925195b63ba0c`, pinned at `lib/agentic-workspace/Cargo.toml:24` | The research established that the EXP-V1-0006 directory is identical at the pin and in the checked-out APSS |
| Parent plan and dossiers | `origin/docs/runtime-research-20261012` @ `80d1423a2c7015a039c633771f3cd90b2962a9ee` | Read by the review phase via `git show`. It raised no contradiction with B1/B2 scope |

This phase had Read/Grep/Glob only and no git. **Before committing, the document PR must run
`git rev-parse origin/main` and spot-check that the cited lines still hold at that SHA.** Citations
inside submodules are written `lib/<submodule>/<path as the submodule's git ls-files prints it>`, so
a reader can open them from the syntropic137 root.

New facts established in this phase. Each one changes the plan:

1. **The image-manifest private reach is dead code in production.** `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:164-172` reads `service._isolation._provider._active_workspaces` and calls a Docker SDK `container.exec_run`. No class defines `_active_workspaces`; the only hits for it are that line and its test mock (`packages/syn-adapters/tests/workspace_backends/test_version_manifest_extraction.py:65`). The Python Docker provider's registry is `self._workspaces` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:115`). So `getattr(..., {})` always yields `{}`, and the manifest recorded at `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:220-226` is always `None`. Installed-tool discovery therefore has no working production path today (affects §4).
2. **The recipe standard is EXP-V1-0005 v0.3.0, and AW implements a stale shape.** `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/recipe.py:3-4` claims "EXP-V1-0003-agent-recipe v0.1.0" and has `agent:` (`recipe.py:62`). The APSS checkout has `lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0005-agent-recipe/experiment.toml:7` `version = "0.3.0"`, which renames `agent` to `harness` and is marked breaking (`experiment.toml:9`). It already standardises a **tools allowlist** (`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0005-agent-recipe/docs/01_spec.md:252-260`) and an **MCP server/method policy** with monotonic narrowing (`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0005-agent-recipe/docs/01_spec.md:412-470`). It keeps credentials, provisioning and limits out of the recipe (`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0005-agent-recipe/docs/01_spec.md:21`, `:42`). The previous plan's "MCP is unmodelled, add new AgentRecipe fields" was wrong at the standards level. §4 is rebuilt on these two standards.
3. **Production capture already exists and is fail-open by design.** `SessionCaptureService` is wired at `apps/syn-api/src/syn_api/_wiring.py:283`, called from `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_delegate_import.py:392` while the container is up. It states "a capture that did not happen is telemetry, not a phase failure" (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/session_capture_service.py:101-103`, also `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/capture_probe.py:22-27`). The research's open Q5 is settled: required-capture-fails-the-run is deliberately not implemented.
4. **Teardown failure is swallowed into a log line; the primary failure survives.** `cleanup_workspace` runs in the `finally` of `create_workspace` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:532-551`). `_destroy_isolation` catches, logs a warning and returns `None` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:273-277`). Open Q6 is settled: "MUST NOT replace the primary failure" holds; "MUST be reported" is met only by a log line.
5. **A credential rides in the agent's streamed environment.** `ManagedWorkspace.stream` merges `platform_grant.env`, the agent's API token, into `environment` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:176-178`). AW itself documents `WorkspaceConfig.environment` as secret-bearing (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:494-504`). Environment overlays and credentials must therefore be separate fields (§2, §3).
6. **No syntropic137 domain code branches on the provider brand.** The only non-test comparison on a backend enum under `packages/` is adapter wiring, `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:252`, choosing a security profile. `IsolationHandle.isolation_type` is a declared, recorded field (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/value_objects.py:268`, recorded at `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:224`), not a decision.

## 1. Problem

An agent's whole run exists only as one `docker exec` child process of the API. That process is
built by syntropic137 itself, not by the provider:

- `_build_exec_command` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:44-73`) is spawned at `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:176-182`.
- The file's own docstring admits the split: "TWO DOCKER EXEC PATHS EXIST" (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:150-153`).

Consequences:

- **The output can be read once, live, by that process only.** No other process can ask whether the run is still going or how it ended.
- **Cancel and timeout kill the client, not the workload.** For the agent, `_cleanup_process` terminates the local `docker exec` client (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_helpers.py:101-112`). For setup commands, `_run_exec` does `proc.kill()` on the client (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:601-603`). `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/skill_install.py:79-81` states the consequence: the deadline kills the client and the installer keeps running.
- **Results are read from a host bind mount** (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:578-585`, which delegates to `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py`). `ManagedWorkspace.path` prefers the host path and falls back to a fabricated `/tmp` path (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:115-122`).
- **The provider is reached through a private attribute** (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:263`).

So no provider whose processes or filesystem live off the API host can run a phase. That is the
1,000-tier seam (`docs/north-star.md:13`, `:184`). The 100-tier "100 `docker exec` streams in one
process" hypothesis is this exact path (`docs/north-star.md:166`).

EXP-V1-0006 v0.1.0 requires cancellation, status and logs
(`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:147-148`),
but its only schema is the launch manifest
(`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0006-workspace/schemas/workspace-launch.schema.json`).
No status, result, error, observation or reference shape exists. Two more gaps follow:

- The Python provider that production runs has no conformance suite. `lib/agentic-workspace/tests/conformance/COVERAGE.md:3-18` covers only Rust Local and Docker.
- The Rust crates that do have a suite have no production caller. The only `agentic-isolation` dependencies are the Python path deps (`pyproject.toml:85`, `packages/syn-adapters/pyproject.toml:14`).

## 2. Decision D1: the contract surface is APSS JSON Schema, implemented first by the production Python provider; Rust follows for promotion

The review accepted D1. The evidence:

- **Production path.** `apps/syn-api/src/syn_api/_wiring.py:292` → `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:257` (`AgenticIsolationAdapter`) → `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:225` (Python `WorkspaceDockerProvider`) → `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:342` (`self._provider.create`). Short commands go through `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:521`. Teardown goes through `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:469`.
- **The Rust trait is the wrong shape and has no caller.** It is synchronous and returns buffered `Vec<u8>` stdout/stderr (`lib/agentic-workspace/crates/workspace-core/src/lib.rs:349-355`, trait at `:363-384`). It has no cancel, status, logs or observe. Extending only it is the parallel path the brief forbids.
- **The language-neutral artifact APSS already uses is JSON Schema** (`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:28-30`). The schemas, plus shared **behaviour fixtures** (scripted call sequences with expected states, not only accept/reject documents), are the single source. Python implements them now. Rust implements them before promotion, which needs Local, Docker and one remote provider (`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:204`, `:212-213`).

Rejected alternatives:

- **Rust-first.** Nothing would run it.
- **PyO3 bindings.** They add a native build to the API image, cargo is absent from agent workspaces, and they inherit the blocking shape.
- **A syn-only port.** It puts provider mechanics in syn, against CLAUDE.md "Where does this change belong?", and leaves remote providers nothing to conform to.
- **Widening `WorkspaceProvider`.** The module documents why optional capabilities are separate protocols (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:241-246`).
- **A parallel `OperationProvider` interface.** The brief forbids it.
- **A new operation queue or persisted refs on the run queue.** `ExecutionRunQueue` is the queue (`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:97`), and there is no reattach (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:58`).

## 3. Section 1 of the document: contract map

### 3.1 Rules for the map

- **One row per independently falsifiable clause**, each with a stable id `W-<section>-<letter>`. §7 requires a mapping to test identifiers, and the ids are what `COVERAGE.md` will key on.
- **Three columns, mapped separately.**
  - **Py** is the production path: AW Python provider plus the syn adapter. When the behaviour lives only in syn, it is marked *(syn)*. That counts as **missing for provider conformance**, with the note kept.
  - **Rust** is `workspace-core` plus `implementations/{docker,local}`.
  - **Cov** is the `lib/agentic-workspace/tests/conformance/COVERAGE.md` row.
- **Status vocabulary.**
  - **IT** means implemented, with a named test.
  - **IU** means implemented, but no test identifier was read.
  - **M** means missing.
  - **M(refused)** means the feature is missing and the provider refuses it explicitly. That refusal is conformant for W-3.6-b and W-3.8-d. Everywhere else it is a missing feature.
  - **NE** means not established. Nobody investigated, which is not the same as absence.
- **COVERAGE area labels are not test evidence.** `COVERAGE.md:9` (file hydration) is PARTIAL, and an area PASS row is not converted into IT for every clause under it. Where only an area label backs a Rust clause, the cell reads `IU (area PASS, COVERAGE.md:N)`. **The document PR must replace each such cell with a named Rust test id or leave it IU.**
- **"No manifest is consumed" is kept separate from "a boundary violates the rule".** The Python provider consumes no `apss.workspace-launch/v1` manifest at all (research grep; `WorkspaceConfig` is a plain dataclass at `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:468-469`). So every manifest-validation clause is **M (no manifest boundary)** for Py, and that is not a violation claim.

### 3.2 The map

Abbreviation used only inside this table: `SPEC:n` means
`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:n`.
The document PR must spell it out in full the first time it is used and in the table header.

| id | SPEC | Clause | Py | Rust | Cov | Debt or schema gap |
|---|---|---|---|---|---|---|
| W-2-a | :32 | Unknown manifest fields rejected | M (no manifest boundary) | IU: `deny_unknown_fields` on manifest structs plus re-validation through the APSS crate (`lib/agentic-workspace/crates/workspace-core/src/lib.rs:167-177`) | :5 PASS (area) | debt |
| W-3.1-a | :39 | `execution_id` non-empty, stable | M at provider; IU (syn) `IsolationConfig.execution_id` | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:179`, `:196-202` | :5 | debt |
| W-3.1-b | :40 | `execution_id` on logs | IU (syn): label and log lines in `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:364-367` | IU (Docker label, per research) | none | debt |
| W-3.1-c | :40 | `execution_id` on results | M: provider `ExecuteResult` has no id | M: `ExecutionResult` has no id (`lib/agentic-workspace/crates/workspace-core/src/lib.rs:350-355`) | none | **gap**: no result shape (§4.2 `workspace-result`) |
| W-3.1-d | :40 | `execution_id` on cleanup diagnostics | IU (syn) `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:348-353` | NE | none | debt |
| W-3.2-a | :44 | `working_directory` relative | M (no manifest boundary). syn hard-codes `/workspace` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:328`) | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:180`, `:259-274` | :8 PASS (area) | debt |
| W-3.2-b | :44-45 | No parent traversal | M (no manifest boundary). Separately, AW `write_file` joins without containment (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:688-698`), a traversal defect in a non-manifest API | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:259-274` | :8 | debt |
| W-3.2-c | :45-46 | Not interpreted as a host path | M (no manifest boundary). **Not** evidenced by `Workspace.path` alone. The real consumer host-path dependencies are `packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:115-122` and `copy_from` via the host (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:584-585`). They are blast radius, tracked in PR 9 | NE: handle has `root: PathBuf` (`lib/agentic-workspace/crates/workspace-core/src/lib.rs:337`); interpretation not traced | none | debt plus **gap** (opaque `WorkspaceRef`, §4.2) |
| W-3.2-d | :50-51 | insecure-local needs explicit enablement | IU (syn) `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py` `_create_local_impl` guard (research `:326-329`). AW Python Local: M | IU (area) | :7 PASS (area) | debt |
| W-3.2-e | :51 | insecure-local rejected in production | as W-3.2-d | IU (area) | :7 | debt |
| W-3.2-f | :52-54 | Isolated conformance covers fs/process/credential/network/resource/teardown | M: no Python suite | IU partial (area) | :17 PASS, :18 PARTIAL | debt |
| W-3.2-g | :57 | Core does not branch on provider brand | **IU, holds (no branch found)**: only adapter wiring compares a backend (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:252`), which is legitimate inside an adapter. `isolation_type` (`packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workspace/value_objects.py:268`) is a recorded label | IU (generic harness) | none | none. The fitness check in PR 9 makes it IT |
| W-3.3-a | :62-63 | Resolve repo revision before harness | IU (syn), not provider | M(refused) (`lib/agentic-workspace/implementations/docker/src/lib.rs:322-326`) | :13 PENDING | debt |
| W-3.3-b | :63-64 | Report resolved commit | IU (syn) `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/source_commits.py:47` | M(refused) | :13 | debt plus **gap** (result field) |
| W-3.3-c | :67 | Verify supplied SHA-256 before launch | M: `copy_to` takes bytes, no hash (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:569-576`) | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:302-310` | :9 PARTIAL | debt. The content-ref design (§4.2) supplies the size and locator v0.1.0 lacks |
| W-3.3-d | :68 | Fail before agent when required hydration fails | IU (syn): setup precedes stream | IU (lifecycle order) | :9 PARTIAL | debt |
| W-3.3-e | :70 | No raw secret values **in a manifest** | **N/A for Py**: no manifest. `WorkspaceConfig.secrets` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:492`) is implementation-owned configuration, which SPEC:71-72 permits to carry references. Its raw values, and the secret-bearing `environment` (`config.py:494-504`), are a **least-privilege credential delivery risk, tracked under W-6.3-a**, not a W-3.3-e violation | IU: launch schema has no secret field | none | none for this clause |
| W-3.4-a | :80-81 | Report effective model when revealed | IU (syn) `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/EventStreamProcessor.py:698` | M | none | **gap** (result field) |
| W-3.4-b | :81-82 | Never invent an effective model | NE | M | none | gap |
| W-3.5-a | :86 | Skill entry has name/source/revision/digest | (syn) has `resolved_sha` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/resolved_skill.py:24`); not a manifest | IU schema (`workspace-launch.schema.json:126-136`) | :14 PENDING | debt |
| W-3.5-b | :87 | Skill names unique | NE | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:209-212` | :14 | debt |
| W-3.5-c | :87-88 | Fail before launch on materialize/digest mismatch | NE: no re-check found after injection (research Q3) | M(refused) | :14 | debt |
| W-3.6-a | :95-96 | allow ∩ deny = ∅ | M: no deny concept (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:394`) | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:216-225` | :15 PENDING | debt |
| W-3.6-b | :96-98 | Reject a policy the adapter cannot honour | IU (syn): Codex + allowed_tools refused (`workflow_definition.py:615-625`, `apps/syn-api/src/syn_api/_wiring_agent_command.py:114-120`) | IT-eligible M(refused) (`lib/agentic-workspace/implementations/docker/src/lib.rs:303-311`); test id not read | :15 | debt (ownership moves to AW, §6) |
| W-3.6-c | :100-101 | Report unsupported required capabilities before launch | NE (research Q4) | M(refused) `lib/agentic-workspace/implementations/docker/src/lib.rs:312-316` | none | debt plus **gap** (descriptor) |
| W-3.6-d | :101-102 | Capability init/health/finalize fail loudly | NE. Capture finalize is deliberately fail-open (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/capture_probe.py:22-27`), so "loud" here means a typed verdict, not a failed phase (§4.4) | M | none | gap (finalization outcome) |
| W-3.7-a | :109 | Captured output conforms to APS-V1-0004 | IU (AW harness transcripts plus syn capture) | M | :16 PENDING | debt |
| W-3.7-b | :110-111 | `required` + missing conformant envelope ⇒ result unsuccessful | **M by policy.** Fail-open (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/session_capture_service.py:101-103`). Conformant only if syn declares `required: false`, see §4.4 and decision H3 | M | :16 | gap (result envelope ties the verdict to success) |
| W-3.8-a | :116 | No collection outside root | IU (syn) fd-relative `O_NOFOLLOW` walk (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/workspace_walk.py:35`); test id not read | IU (area) | :11 PASS (area) | debt |
| W-3.8-b | :119 | `timeout_seconds > 0` | M at provider (`ResourceLimits.timeout_seconds` unused; `execute` uses `timeout or 3600`, `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:580`) | IU `lib/agentic-workspace/crates/workspace-core/src/lib.rs:204-208` | :10 PASS (area) | debt |
| W-3.8-c | :119-120 | Supported CPU/memory/disk enforced | IU CPU/memory only (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:333-336`) | IU (area) | :18 PARTIAL | debt |
| W-3.8-d | :120-121 | Reject an unenforceable hard limit | **M: `disk` accepted and ignored** (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/config.py:404`; no reader in the provider). Latent: syn never sets it | M(refused) `lib/agentic-workspace/implementations/docker/src/lib.rs:317-321` | :18 | debt |
| W-3.8-e | :123-124 | Metadata preserved in result | M (no result) | M | none | gap |
| W-3.8-f | :124 | Metadata never executable | NE | NE | none | debt |
| W-4-a | :138-139 | Cancel/timeout lead through finalize and destroy | IU (syn): cleanup in `finally` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:532-551`). **No finalize step on that path**: capture runs before it (`phase_delegate_import.py:392`), and the workload is not killed first (client-only kill) | M (no finalize) | :12 | debt plus gap (finalization outcome) |
| W-4-b | :139 | Teardown idempotent | IT (AW): per-workspace single-flight lock (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:808-832`), tests in `lib/agentic-workspace/lib/python/agentic_isolation/tests/test_staged_teardown.py` (ids to be named in the document) | IU (area) | :12 PASS (area) | none |
| W-4-c | :139-140 | Failed teardown is reported | **M: log line only** (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:273-277`) | NE | none | gap (`teardown` field of the result) |
| W-4-d | :140 | Failed teardown does not replace primary failure | IU (syn): swallowed, the primary propagates (`workspace_lifecycle.py:273-277`, `workspace_service.py:526-530`) | NE | none | gap (separate fields) |
| W-5-a | :144-145 | DI; core depends on the port, not Docker | IU partial: port `IsolationBackendPort` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:33`), **but** the private reaches at `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_service.py:263` and `packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:164`, and the syn-built `docker exec` at `stream_helpers.py:66` | IU | none | debt |
| W-5-b1 | :147 | Port: provision | IU | IU | :8 | none |
| W-5-b2 | :147 | Port: hydration | IU (syn `copy_to` plus setup) | IU | :9 | debt |
| W-5-b3 | :147 | Port: execution | IU, blocking only | IU, blocking only | :10 | **gap**: non-blocking start, `OperationRef` |
| W-5-b4 | :147 | Port: cancellation | **M**: client-only kill (`stream_helpers.py:101-112`, `docker.py:601-603`) | M | none | gap (operation semantics) |
| W-5-b5 | :148 | Port: status | M: only `health_check` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:565-567`) | M | none | gap (status envelope) |
| W-5-b6 | :148 | Port: logs | IU provider-side `SupportsWorkspaceLogs` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:237-281`); not on the syn port | M | none | debt for workspace logs; **gap** for per-operation paged observation |
| W-5-b7 | :148 | Port: file collection | IU via host mount (`adapter.py:584-585`) | IU | :11 | debt (through the provider, PR 9) |
| W-5-b8 | :148 | Port: destruction | IU | IU | :12 | none |
| W-5-c | :148-150 | Interactive ops discoverable | IT: `BaseProvider.interactive_session` returns None when unsupported (`base.py:451`), tests in `lib/agentic-workspace/lib/python/agentic_isolation/tests/test_interactive_session_protocol.py` | M | none | none |
| W-6.1-a | :156-157 | Functional suite passes (lifecycle, hydration, manifest, result, artifact boundary, cancellation, timeout, teardown) | M: no Python suite | partial, no cancellation test | :5-12 | debt |
| W-6.2-a..d | :161-163 | Local identifies insecure / opt-in / refuses production / never implicit fallback | AW Python Local: M (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/local.py`); syn guard IU | IU (area) | :7 | debt |
| W-6.3-a | :167-169 | Isolated proves fs/process containment, least-privilege creds, network, resources, abnormal-termination cleanup | partial. **Least-privilege creds at risk**: raw values via `docker exec -e` argv (`stream_helpers.py:67-69`) and `docker run -e` (research) | IU partial | :17-18 | debt (credential bindings, §4.2) |
| W-7-a | :173-174 | Each requirement mapped to test ids | M for Py | M: 14 area rows, not per-MUST ids | n/a | debt |
| W-7-b | :174-175 | Fixtures, round trips, provenance, matrix, discrepancies | M for Py | IU (fixtures, `PROVENANCE.md`, `DISCREPANCIES.md` exist) | n/a | debt |
| W-7-c | :177-178 | No conformance claim below 95% | holds (no claim) | holds (`COVERAGE.md:20`) | n/a | none |
| W-8-* | :182-188 | Security restatements | alias rows: :182→W-3.3-e, :183→W-3.2-b, :184→W-3.3-c, :185→W-3.6-b/W-3.8-d, :186→W-6.2, :187 (isolated never degrades to Local) IU (syn) `workspace_service.py:250-254`, :188→W-4-a | | | |
| W-9-a | :197 | APSS does not depend on Syntropic | holds | holds | n/a | none |

## 4. Section 2 of the document: implementation debt vs genuine schema gaps, and the minimal delta

### 4.1 Classification

- **Implementation debt** means v0.1.0 already requires it, so closing it changes no schema. That covers every row marked *debt* above, notably:
  - W-2-a and W-3.2-a/b/c: Python consumes no manifest.
  - W-3.3-c, W-3.5-c, W-3.6-a/b and W-3.8-b/d.
  - W-5-a: the private reaches.
  - W-5-b4/b5 as *requirements*. The shape of what they return is the gap.
  - W-6.1, W-6.2, W-6.3 and W-7: the Python suite.
- **Genuine schema gaps** have no field or schema in v0.1.0:
  1. Operation identity and idempotency scope (W-5-b3).
  2. Typed status, result and error envelopes (W-3.1-c, W-3.3-b, W-3.4-a, W-3.7-b, W-3.8-e, W-4-c/d, W-5-b5).
  3. A bounded observation page with cursor, retention and gap (W-5-b6, per operation).
  4. A provider capability and security descriptor (W-3.6-c, W-3.8-d checkable from data).
  5. Immutable content and environment references (W-3.3-c lacks size/locator semantics; no environment identity exists at all).
  6. A finalization outcome (W-3.6-d, W-4-a).

### 4.2 Minimal versioned delta: EXP-V1-0006 0.2.0, purely additive

The delta adds new schema files and a new spec section, §5.1 "Operation contract". It leaves
`apss.workspace-launch/v1` byte-identical, so no strict v1 reader breaks
(`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:32-33`).
Every object is `additionalProperties: false`. Out of APSS entirely: scheduling, budgets,
placement, attempt numbering and the queue fence (`01_spec.md:19-20`).

| Schema file (`schemas/`) | Discriminator | Shape | Normative rules (new §5.1 MUSTs) |
|---|---|---|---|
| `workspace-ref.schema.json` | `apss.workspace-ref/v1` | `WorkspaceRef {provider: nonEmpty, resource_id: nonEmpty}` | Opaque. A consumer MUST NOT parse it or derive a path from it. Equality is the only operation |
| `content-ref.schema.json` | `apss.content-ref/v1` | `ContentRef {digest: "sha256:<64hex>", size_bytes: int≥0, media_type?: string, locator: nonEmpty, authority?: CredentialRef}` | Identity is `digest`. `locator` is opaque to core consumers and resolved only by the provider. A provider MUST verify digest and size before the content is visible to the workload, and MUST fail hydration on mismatch (this is how W-3.3-c becomes testable). `authority` is a reference, never a value |
| `environment-ref.schema.json` | `apss.environment-ref/v1` | `EnvironmentRef {kind: nonEmpty, identifier: nonEmpty, digest?: string}` | `kind` is an open, provider-interpreted namespace (for example an OCI image, a template version or a snapshot id). Core consumers MUST treat the ref as opaque and compare by equality only, so no consumer learns a brand. A provider MUST report the **effective** environment in the result. When it was given a requested ref and cannot run exactly that, it MUST refuse, not substitute |
| `credential-ref.schema.json` | `apss.credential-ref/v1` | `CredentialRef {name: nonEmpty, scope: nonEmpty}`, and `CredentialBinding {ref: CredentialRef, delivery: "env" \| "file", target: nonEmpty}` | A credential value MUST NOT appear in any APSS artifact. The provider resolves refs through implementation-owned configuration (SPEC:71-72). A binding MUST NOT be persisted into results or observations |
| `workspace-operation.schema.json` | `apss.workspace-operation/v1` | `OperationSpec {execution_id, operation_key, argv: [string]+, working_directory: relativePath, environment: {string: string}, credential_bindings: [CredentialBinding], launch_marker?: {argv0: nonEmpty, line: nonEmpty}, timeout_seconds: int≥1, metadata: {string: string}}`; `OperationRef {workspace: WorkspaceRef, operation_id, operation_key}` | See "Operation rules" below |
| `workspace-status.schema.json` | `apss.workspace-status/v1` | `OperationStatus {ref, state: pending\|running\|succeeded\|failed\|cancelled\|timed_out\|lost, exit_code?, signal?, started_at?, ended_at?, execution_id, metadata}`; `OperationError {kind, message, ref?}` | See "Status and error rules" below |
| `workspace-observation.schema.json` | `apss.workspace-observation/v1` | `ObservationPage {ref, cursor: Cursor, next_cursor: Cursor, data_b64, gap?: {lost_bytes: int≥1 \| null}, complete: bool}`; `Cursor {generation: nonEmpty, offset: int≥0}` serialised as an opaque string | See "Observation rules" below |
| `workspace-provider.schema.json` | `apss.workspace-provider/v1` | `ProviderDescriptor {provider, security_profile, enforceable_limits: {cpu, memory, disk, network, timeout: bool}, capabilities: [nonEmpty], observation: {retention_bytes, max_page_bytes, integrity: "exact" \| "continuity_detected"}, interactive: bool, environment_kinds: [nonEmpty]}` | Published before launch. A request outside it MUST be refused with `unsupported_capability` or `rejected_policy` (W-3.6-c and W-3.8-d become data checks) |
| `workspace-finalization.schema.json` | `apss.workspace-finalization/v1` | `FinalizationOutcome {state: completed\|retained\|failed, stage?: while_running\|before_delete, error?: OperationError, retained?: WorkspaceRef}` | See "Finalization rules" below |
| `workspace-result.schema.json` | `apss.workspace-result/v1` | `WorkspaceResult {execution_id, metadata, process: OperationStatus (terminal), effective_model?, effective_environment?: EnvironmentRef, resolved_commits: [{destination, commit}], artifacts: [ContentRef], capture: {required: bool, state: captured\|incomplete\|failed\|unknown\|disabled, needs_backfill: bool}, finalization: FinalizationOutcome, primary_failure?: OperationError, teardown_failure?: OperationError, success: bool}` | See "Result rules" below |

**Operation rules**

- `start` returns once the operation is accepted, without waiting for it to end. The workload's environment is exactly the provider defaults plus `environment` plus resolved `credential_bindings`.
- `environment` MUST NOT carry credentials. Credentials go in `credential_bindings`, which is what lets `OperationSpec` be persisted and logged.
- When `launch_marker` is present, the provider MUST emit `line` on the observation stream from a process that precedes the workload and is replaced by it, under the name `argv0`. Neither value may be readable by the workload through its environment, files or argv after it starts. The marker is opaque to the provider.
- **Idempotency scope is one workspace.**
  - The same `(workspace, operation_key)` with an equal spec returns the same ref and launches nothing.
  - Concurrent same-key starts MUST yield exactly one launch.
  - The same key with a different spec is the error `conflict`.
  - The idempotency record lives at least as long as the workspace.
  - After an accepted start whose response was lost, a retried start with the same key returns the original ref.

**Status and error rules**

- `state` comes from a channel the workload cannot write. Terminal states are sticky.
- `lost` only when the provider has *positively established* that the resource or process is gone with no recorded outcome.
- When the provider merely cannot answer, `status` returns `OperationError{kind: provider_unavailable}`, not an `OperationStatus`. An unknown ref returns `OperationError{kind: unknown_operation}`.
- `cancel` is idempotent. It returns `cancelled` only after the process and its descendants are confirmed gone. If the provider cannot confirm, it MUST escalate to terminating the workspace's processes, and reports that.
- `error.kind` is closed for v1: `rejected_policy`, `unsupported_capability`, `hydration_failed`, `conflict`, `unknown_operation`, `timeout`, `cancelled`, `resource_lost`, `provider_unavailable`, `internal`.

**Observation rules**

- Cursors are opaque to consumers, monotonic within a generation, and foreign or expired cursors are typed.
  - A cursor from another generation or another ref is `OperationError{kind: unknown_operation}`.
  - A cursor older than retention returns the oldest retained data plus `gap`.
- A serialised page MUST NOT exceed `max_page_bytes`, base64 and envelope included. That holds the decoded payload to at most `floor((max_page_bytes - envelope_overhead) * 3/4)`.
- Data lost to retention is reported as `gap`, never silently skipped. `lost_bytes` is exact when `integrity: exact`. It is `null` (loss detected, extent unknown) when `integrity: continuity_detected`.
- `complete` is true only when status is terminal **and** every retained byte up to the terminal offset has been returned. A late read after a terminal state returns the remaining bytes.

**Finalization rules**

- A cancel or timeout MUST pass through finalization before destroy.
- `retained` means a `before_delete` failure left the data in place and gives the ref to retry against. Deletion MUST NOT occur in that state.
- Process completion and capture success are separate facts.

**Result rules**

- `success = process.state == succeeded ∧ (¬capture.required ∨ capture.state == captured)`. This is how W-3.7-b becomes data.
- `teardown_failure` never overwrites `primary_failure`.
- `capture.state` is mapped from the existing authoritative verdict, not re-judged (§4.4).

**Versioning boundary documented now, adopted later: `apss.workspace-launch/v2`.** Requested
environment (`environment: EnvironmentRef`) and content as `ContentRef` in `content.inputs` belong
on the launch manifest. Adding them is a new strict-reader version (`01_spec.md:32-33`). 0.2.0
defines the two ref schemas and uses them **only in results and in `OperationSpec`-adjacent
hydration**. Spec text reserves `workspace-launch/v2` as "launch/v1 plus `environment` and
ContentRef inputs". Adoption is deferred until a remote provider needs it (decision H2). syn's
cosign verification (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:313-323`)
is a Docker implementation fact. It becomes the Docker provider's `effective_environment`
`{kind: "oci-image", identifier, digest}` report, not a portable rule.

**Behaviour fixtures** ship beside the JSON fixtures as scripted scenarios: a sequence of calls
plus the expected states, pages and errors. Examples:

- "start, start same key, one launch".
- "cancel twice, terminal once".
- "cursor after retention, gap".
- "required capture unknown, success false".

They are what keep Python and Rust runtime semantics aligned, which schema acceptance alone cannot do.

### 4.3 What the operation key is (no new queue)

`operation_key` is an opaque string the orchestrator composes. syn builds it from four parts:

- `execution_id`
- `phase_id`
- the `ClaimedRun.token` fence (`packages/syn-domain/src/syn_domain/contexts/orchestration/ports/ExecutionRunQueuePort.py:52-59`)
- a purpose suffix (`agent`, `setup:<n>`)

The fence is syn's attempt guard. The provider-side dedup is the provider's own record (§5.3).
APSS never learns what an attempt is. Nothing is persisted on `ExecutionRunQueue`. Reattach stays
out (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:58`), and adopting it is C1
and would amend ADR-072.

### 4.4 Finalization and capture: reuse the existing verdict

- Finalization runs through the existing `SupportsStagedTeardown.teardown(workspace, *, while_running, before_delete)` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py:284-343`), using **both** hooks.
  - `while_running` is the host-invoked exporter probe. That is today's `capture_and_record` call, **moved** from `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/phase_delegate_import.py:392` into the hook, not duplicated.
  - `before_delete` is the durable archive of the spool. Docker already runs it after removal and before directory deletion, and skips deletion on any exception (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:867-874`).
- **Typed receipt.** `teardown` today returns `None` (`base.py:323`, `docker.py:802`), while the adapter already expects a report (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:465-470`). The delta makes `teardown` return a `TeardownReport` carrying `finalization: FinalizationOutcome` and the existing usage. `destroy` stays the unhooked case.
- **Retention and retry ownership.**
  - Today, both registries drop the workspace before teardown can fail: the adapter pops its handle first (`adapter.py:459`), and Docker pops `_workspaces` before `before_delete` (`docker.py:864-865`).
  - The delta: on a `before_delete` failure, Docker reports `retained` with the `WorkspaceRef` and keeps a retained-registry entry. The adapter pops its handle only after a non-`retained` report.
  - **Retry owner is syn**, using the existing paths: capture backfill (`AuthoritativeCapture.needs_backfill`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/capture_result.py:160-172`) and orphan reaping (`packages/syn-adapters/src/syn_adapters/workspace_backends/orphaned.py`). Retry calls `teardown(ref)` again. The provider's single-flight lock (`docker.py:808-832`) makes that safe.
  - Remote durable storage is C3's implementation, but the *guarantee* (retain, report, retry by ref) is in the 0.2.0 contract now.
- **Capture verdict mapping.** `capture.state` maps one-to-one from `AuthoritativeCapture.state` / `CaptureState` (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/capture_result.py:130-172`). That is the existing authoritative judgement, over a channel the agent cannot write.
  - syn declares `transcript.required = false` for its phases, which makes its deliberate fail-open policy (`session_capture_service.py:101-103`) **conformant** with W-3.7-b rather than a violation.
  - Whether any phase should require capture is decision H3. The contract makes either answer expressible.
- **Teardown failure reporting.** `_destroy_isolation` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/workspace_lifecycle.py:265-281`) returns the report, including `teardown_failure`, instead of `None`. The primary failure continues to propagate from `create_workspace` (`workspace_service.py:526-530`).

## 5. Section 3 of the document: Python provider protocol delta

### 5.1 Protocol

Module: `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/base.py`, in
the existing optional-capability style (`runtime_checkable` Protocol tested by `isinstance`, as at
`base.py:237` and `:284`). Models live in a new `agentic_isolation/contract/` package generated
against the vendored APSS schemas: Pydantic, `frozen=True`, `extra="forbid"`.

```python
@runtime_checkable
class SupportsOperations(Protocol):
    def describe(self) -> ProviderDescriptor: ...
    async def start(self, workspace: Workspace, spec: OperationSpec) -> OperationRef: ...
    async def status(self, ref: OperationRef) -> OperationStatus: ...          # raises OperationFailure(OperationError)
    async def observe(self, ref: OperationRef, *, cursor: Cursor | None,
                      max_bytes: int, wait_seconds: float = 0) -> ObservationPage: ...
    async def cancel(self, ref: OperationRef, *, grace_seconds: float) -> OperationStatus: ...
```

- **Finalize is not a method.** It is `SupportsStagedTeardown.teardown`, now returning `TeardownReport` (§4.4). That is one place that enforces the order.
- **`SupportsWorkspaceLogs` stays as it is.** It is workspace-wide, tail-only, diagnostic and untrusted (`base.py:256-263`). `observe` is per-operation, cursor-paged and integrity-declared. The document carries a two-row table saying so.
- **`Workspace` gains `provider_reference: WorkspaceRef`.** This mirrors Rust `WorkspaceHandle.provider_reference` (`lib/agentic-workspace/crates/workspace-core/src/lib.rs:339`) as a typed opaque value. `_handle: Any` (`base.py:115`) becomes provider-private. `Workspace.path` is documented as provider-local and is never read by the contract.
- **`execute` and the provider's own `stream`** (`docker.py:555-580`, `:629-679`) become one `BaseProvider.run_to_completion(...)` helper built on start, observe and status. Every existing caller keeps its API. Callers include `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:404` and `:521`, and the setup handlers listed in the research: `skill_install.py`, `WorkspaceProvisionHandler.py`, `instruction_imports.py`, `codex_sandbox_probe.py`, `workspace_git.py`, `ExecuteCommandCommand.py`, all under `packages/syn-domain/src/syn_domain/contexts/orchestration/`.
- **Wiring.** syn checks `isinstance(provider, SupportsOperations)` once, at wiring, and fails fast otherwise (ADR-060 no-silent-fallback). It injects the typed provider into the stream adapter, which replaces `set_provider(isolation._provider)` (`workspace_service.py:262-263`).

### 5.2 Docker implementation (PR 3). The design that answers B3 and I2

- **Owner-controlled spool, not an agent-writable one.**
  - `start` launches an attached `docker exec` client as a provider-owned task. The task appends combined output (`2>&1`, which keeps ADR-043, `stream_adapter.py:134-148`) to a per-operation, append-only spool **on the host side, outside every bind mount**. The workload has no handle on it, so truncate-and-regrow is impossible by construction.
  - The descriptor declares `integrity: exact`, and `gap.lost_bytes` is exact, because the only loss is the provider's own retention eviction, which it counts.
  - The generation is the spool's identity, fresh per operation. A foreign cursor is detected by generation mismatch.
  - Honest cost: this is still one `docker exec` client per running operation in the hosting process, the north-star:166 hypothesis. It is no worse than today, and the contract is what lets #1310 move it out of the API.
- **Status from the client's daemon-reported exit code**, which the workload cannot write. A spool marker written by the workload is never read as status. `lost` is set only when the container is confirmed gone. An unreachable daemon is `provider_unavailable`.
- **Launch marker.** The constant `_ANNOUNCE_THEN_EXEC` (`stream_helpers.py:41`) moves into the Docker provider. It is invoked as `sh -c <script> <argv0> <line> <argv...>`, identical to `stream_helpers.py:72`. syn's `AgentLaunchEvidence` keeps minting `argv0` and `line` (`mint_wrapper_name` / `announce_as`, imported at `stream_helpers.py:14`). The provider never computes them, which keeps the forgery defence documented at `stream_adapter.py:124-129` and `AgentExecutionHandler.py:490-493`.
- **Credentials off argv.** Today values appear in the client argv (`stream_helpers.py:67-69`). Bindings resolve through an injected `CredentialResolver` that syn implements over token vending. They are passed as `docker exec -e NAME`, with the value only in the client process's environment. The test asserts the value is absent from the client argv.
- **Cancel: a trusted target, a group, and confirmation.**
  - The wrapper prints the in-container pid on the marker line before `exec`, when no workload exists yet to forge it.
  - The workload starts under `setsid`, so pid = pgid.
  - `cancel` sends TERM to the group via a fresh exec, waits `grace_seconds`, sends KILL, then confirms with `kill -0`.
  - PID reuse is bounded by checking that the pid's start time equals the one recorded at start.
  - A descendant that left the group, or a group that will not die, escalates to stopping the container. That is reported, and `cancelled` is never claimed falsely.
  - **"No image change" is contingent.** PR 3a must first prove that `setsid` and `kill` exist in every pinned workspace image. If not, the fallback is the container-stop escalation, and an image change goes through the AW release channel.
- **Idempotency record.** An in-process map `(workspace_id, operation_key) → (spec_hash, ref)` under an `asyncio.Lock`, living as long as the workspace.
  - This is *infrastructure state*, in the same category as active container handles, which CLAUDE.md says is lost on crash, not domain state. It is not an `InMemoryAdapter` under ADR-060 s5, because it backs no port and has no durable alternative: the workspace it describes dies with the process (no reattach). The document states this so a reviewer can disagree explicitly.
  - Remote providers must persist it. The contract requires that it survive as long as the workspace.

### 5.3 The syn side of the migration (PR 7)

`AgenticEventStreamAdapter.stream` keeps its port signature
(`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:198-227`) and becomes:

1. `start(OperationSpec(environment=…, credential_bindings=…, launch_marker=…))`.
2. Loop over `observe` pages through an incremental UTF-8 decoder and a line buffer. A page boundary may split a code point or a line; the final unterminated line is flushed on `complete`.
3. Read `status` for the exit code.

Signal-death evidence (`stream_adapter.py:201-212`) is derived from the terminal status's
`signal` / `exit_code >= 128`. `_build_exec_command` and the `set_provider` pass-through are deleted.
The platform grant (`managed_workspace.py:176-178`) becomes a `CredentialBinding`.

## 6. Section 4 of the document: recipe tool requirements

There are three concepts. Each lives in the standard that already owns it, rather than in new
`AgentRecipe` fields. The recipe stays credential-free and provisioning-free
(`lib/agent-paradise-standards-system/standards-experimental/v1/EXP-V1-0005-agent-recipe/docs/01_spec.md:21`, `:41-42`;
`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/recipe.py:9-10`).

| Concept | Declared where | Enforced by | Fails as |
|---|---|---|---|
| **1. Installed binaries and services** (what the environment must contain and run) | Not the recipe. The EXP-V1-0006 launch `capabilities` request (`workspace-launch.schema.json:63-67`), plus commands implied by recipe-provided tools (`EXP-V1-0005-agent-recipe/docs/01_spec.md:348-357`; that standard explicitly does not check that `command` exists, `:375`) | The provider, against its `ProviderDescriptor.capabilities` and the effective `EnvironmentRef`. **Two separate checks.** (a) Static discovery: the provider reads the environment's version manifest via its own channel. Today's syn read is dead code (§0 fact 1) and is deleted, not promoted. (b) Runtime readiness: a provider-run probe per required service after start, failing loudly (W-3.6-d), because a manifest proves installation, not health | `unsupported_capability` before launch; readiness failure as `hydration_failed` |
| **2. MCP access** (which servers and methods the agent may use, and with what credential) | Grant: EXP-V1-0005 §7 `mcp.servers.<id>.include/exclude`, with package/agent/`from:`/run narrowing (`EXP-V1-0005-agent-recipe/docs/01_spec.md:412-470`). Credential: a run-tier `CredentialBinding` in `OperationSpec` (§4.2), refs only | The AW harness launch adapter compiles the effective method set into harness config. syn applies the run-tier narrowing (§7.2 leaves it to the consumer) | `rejected_policy` if the harness cannot restrict at method granularity (W-3.6-b) |
| **3. Harness allow/deny policy** | Recipe tier: EXP-V1-0005 §4.6 `tools` allowlist (absent means unrestricted; empty means none; `null` rejected; `01_spec.md:252-256`). Run tier: EXP-V1-0006 launch `tools.allow/deny` (`workspace-launch.schema.json:54-62`), which may only narrow | One compiler per harness in AW: a new `launch_policy` module inside `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/harnesses/{claude,codex}/`, a sibling of the transcript plugin. `HarnessPlugin` **stays transcript-only** as its docstring requires (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/harnesses/__init__.py:10-15`). Each compiler declares which of allow and deny it can honour and refuses the rest | `rejected_policy` |

**One command authority.** After PR 11, the AW compiler returns the harness argv fragment, and syn
places it into `OperationSpec.argv`. Two pieces of syn code are then deleted:

- The `--tools` construction (`apps/syn-api/src/syn_api/_wiring_agent_command.py:89-90`).
- The duplicated Codex refusal (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:615-625`, `apps/syn-api/src/syn_api/_wiring_agent_command.py:114-120`).

The definition-time check in syn then asks the AW compiler instead of re-deriving its answer.
Every other harness flag stays in syn as filed boundary debt.

**Recipe version migration (prerequisite, PR 10).** AW's `AgentRecipe` implements the 0.1.0
single-file shape under a stale id. Bringing it to EXP-V1-0005 0.3.0 is a **breaking** change
(`experiment.toml:9`: `agent` becomes `harness`, `tools` becomes an enforced allowlist, `mcp` is
added). AW has already recorded one failed attempt to unify `AgentRecipe.agent` with `AgentName`
(`harnesses/__init__.py:30-40`). The migration is therefore its own PR with its own decision (H4).
The AW recipe has no syn production consumer (research §1.4), so the blast radius is
`workspace_run.py` and AW tests.

**Vocabulary.** `operation`, `operation key`, `finalization`, `MCP grant`, `deny` and
`credential binding` must be added to `docs/architecture/orchestration-ubiquitous-language.md`
(the file exists) in the PR that introduces each term in syn code. Each is a domain-language
change, so it carries decision H5.

## 7. Section 5 of the document: ordered PRs with exit tests

APSS goes first because AW vendors from a merged APSS commit. AW Python changes reach production
with a submodule pointer bump, without an image release: `agentic_isolation` appears in workspace
Dockerfiles only in comments (`lib/agentic-workspace/implementations/docker/images/claude-cli/Dockerfile:20`).
The one exception is the PR 3a contingency.

Every exit test listed below **fails if its change is reverted**, unless it is labelled *regression*.

| # | Repo | Content | Depends on | Exit tests |
|---|---|---|---|---|
| 0 | syntropic137 | This document (docs only) | none | `just preflight-agent`. A reviewer opens every cited `file:line` at the stated SHA |
| 1 | APSS | EXP-V1-0006 0.2.0: the ten schemas in §4.2, spec §5.1, the launch/v2 reservation text, success/failure fixtures, **behaviour fixtures**, `experiment.toml` bump | 0 accepted, H1 | `just check`; `cargo run -p aps-cli --bin apss-dev -- v1 validate repo`. `tests/schema_conformance.rs`: each success fixture round-trips; each failure fixture is rejected (unknown field; `succeeded` with an error; `gap` with `lost_bytes: 0`; `complete: true` on a non-terminal status; a credential value field anywhere; descriptor missing `enforceable_limits`). **All launch/v1 fixtures are run through both the 0.1.0 and the 0.2.0 validator, with identical verdicts** (not just byte equality) |
| 2 | AW | `agentic_isolation/contract/` models, vendored schemas and fixtures, pin-parity test | 1 merged | The vendored rev equals `lib/agentic-workspace/Cargo.toml:24`. Pydantic and `jsonschema` agree on every fixture. Setting a model to `extra="allow"` fails the unknown-field fixture |
| 3a | AW | Cancel feasibility spike (test only) | 2 | In each pinned image: `setsid` and `kill` present. A workload that forks a grandchild, and one that traps TERM, are both gone after the group kill. If this fails, PR 3 uses container-stop escalation and files the image change |
| 3 | AW | `SupportsOperations` + Docker (§5.2) + `run_to_completion` + Python conformance suite + per-MUST ids and a Python column in `COVERAGE.md` | 2, 3a | (a) `start("sleep 30")` returns in < 2 s with state `running`. (b) **50 concurrent** same-key starts give one ref and one process. (c) Same key with a different argv gives `conflict`. (d) The workload's `env` contains the overlay and the resolved binding, and the binding value is absent from the client argv and from every page. (e) The marker line is first on the stream; a workload printing a forged marker is not counted (replays the existing `AgentLaunchEvidence` forgery test through the provider). (f) The workload truncates and rewrites the host spool path (not reachable) and an in-workspace decoy; observed bytes still equal the output exactly. (g) A cursor older than retention returns `gap.lost_bytes` equal to the evicted count. (h) A foreign-generation cursor gives `unknown_operation`. (i) Every serialised page is ≤ `max_page_bytes`. (j) A read after the terminal state drains the rest, and only then `complete`. (k) After `cancel`, the pid, a grandchild and a TERM-trapping child are gone. **(k) fails on today's code.** (l) Destroyed container gives `lost`; stopped daemon gives `provider_unavailable`. (m) A workload writing a fake exit file still gets its true status. *Regression:* the existing execute and staged-teardown tests pass via `run_to_completion` |
| 4 | AW | Local: `SupportsOperations` + insecure opt-in guard | 3 | The PR 3 suite parametrised for Local, with `integrity` per its descriptor. Constructing without opt-in raises (W-6.2) |
| 5 | AW | Debt: refuse `disk` (W-3.8-d), contain `write_file` (W-3.2-b), honour `timeout_seconds` (W-3.8-b), replace `WorkspaceConfig.secrets` and secret-bearing `environment` entries with `CredentialBinding` (W-6.3-a) | 2 | `disk="1g"` raises before `docker run`. `write_file("../x")` raises. `timeout_seconds=1` on `sleep 5` ends `timed_out`. A config holding a credential *value* fails validation, and the resolved value never appears in `docker run` argv |
| 6 | AW | Finalization: `teardown` returns `TeardownReport{finalization, usage}`; on `before_delete` failure the outcome is `retained`, registration is kept, and retry by ref works | 3 | `before_delete` raising gives `retained`, directory present, ref resolvable. A second `teardown(ref)` with a succeeding hook gives `completed`, directory gone. A `while_running` failure leaves the container intact and reports `stage: while_running` |
| 7 | syntropic137 | Bump AW; stream adapter on operations (§5.3); delete `_build_exec_command` and `set_provider(isolation._provider)` | 3 | `just preflight-agent`; `uv run pytest -m unit -q`. A recording test double (inheriting `InMemoryAdapter`, ADR-060) records the provider calls and asserts **no `asyncio.create_subprocess_exec` is reached from the stream path**. Environment, the platform-grant binding, the launch marker, exit status and signal-death all survive. Pages split mid-code-point and mid-line decode to the same lines. A recorded run produces an identical event sequence before and after, including embedded hook JSONL (ADR-043) |
| 8 | syntropic137 | Real cancel on timeout and cancellation before teardown; finalize via staged teardown (move `capture_and_record` from `phase_delegate_import.py:392` into `while_running`; archive in `before_delete`); `WorkspaceResult` mapping; `_destroy_isolation` returns `teardown_failure` | 6, 7 | Docker-backed: on phase timeout, the agent pid is gone before `destroy`. A failing teardown leaves the primary failure recorded *and* `teardown_failure` set. A failed archive keeps the handle and the backfill retries it. `transcript.required=false` with capture `unknown` gives `success` from the process alone. A forced `required=true` with `unknown` gives `success=false` |
| 9 | syntropic137 | `IsolationHandle.provider_reference`; `copy_from` through the provider; delete the dead `_read_image_manifest` reach; then `host_workspace_path` and the `/tmp` fallback | 7 | Fitness check in `ci/fitness/` with a ratchet: no `._provider` and no `host_workspace_path` under `packages/` and `apps/`, and no domain comparison on `isolation_type`. `copy_from` passes against a provider whose `Workspace.path` does not exist on the host |
| 10 | AW | Migrate `AgentRecipe` to EXP-V1-0005 0.3.0 (`harness`, `tools` allowlist with absent/empty/null semantics, `mcp` policy with narrowing) | H4 | The APSS EXP-V1-0005 fixtures are vendored and pass, including `tools: null` rejected, empty `tools` meaning no tools, and an agent-tier `mcp` widening rejected |
| 11 | AW then syn | `harnesses/{claude,codex}/launch_policy` compilers; capability and readiness checks (§6); syn stops building `--tools` and the duplicated refusal | 3, 10 | Claude: an allowlist compiles to the expected argv fragment. A deny the harness cannot honour gives `rejected_policy`. Codex with any allowlist gives `rejected_policy`. An MCP grant naming a server with no binding is refused before launch. A required capability missing from the descriptor gives `unsupported_capability` before launch. A service that installed but fails readiness gives a loud failure. A grep fitness check: no `--tools` literal in `apps/syn-api` |
| later | AW | Rust trait implements the 0.2.0 operations against the same behaviour fixtures, for promotion | 1 | The shared behaviour fixtures pass for Rust Local and Docker |

## 8. Risks

| Risk | Signal that it broke |
|---|---|
| The host-side collector is one `docker exec` per operation in the hosting process (north-star:166) | API RSS and CPU at 20 concurrent phases, measured before and after PR 7. Mitigation: the `wait_seconds` long-poll and the #1310 executor split |
| `setsid` is missing from an image | PR 3a fails, and the fallback escalation becomes the documented behaviour |
| Polled observe adds latency | Dashboard line latency in the recording-based integration test |
| Python models drift from APSS | PR 2 parity test, plus behaviour fixtures |
| The closed `error.kind` is too narrow for a remote vendor | A provider maps most failures to `internal`, visible in its coverage row |
| The provider idempotency record is lost on restart | Acceptable without reattach, since the workspace is reaped (`packages/syn-adapters/src/syn_adapters/workspace_backends/orphaned.py`). Becomes a defect the day C1 adopts reattach |
| Moving capture into `while_running` changes timing | The PR 8 recording test shows capture verdicts per phase unchanged |

## 9. Out of scope

- Implementing PRs 1-11 in this run.
- Reattach and a durable attempt registry (C1, ADR-072).
- Remote durable capture storage (C3); its guarantee is in 0.2.0.
- Placement, budgets, scheduling, and the queue schema (`packages/syn-adapters/src/syn_adapters/execution_runs/schema.sql`).
- A remote provider.
- Moving harness flags other than tool policy out of `apps/syn-api`.
- `.github/workflows/` changes. A Python conformance CI job in AW would ship as a patch file.

## 10. Human decisions needed

- **H1. Confirm D1.** APSS JSON Schema is the contract, Python Docker is the first implementation, and Rust is deferred to promotion.
- **H2. Adoption timing of `apss.workspace-launch/v2`.** It would carry the requested `EnvironmentRef` and `ContentRef` inputs. Recommendation: define the refs in 0.2.0 and defer adopting v2 until a remote provider exists.
- **H3. Capture policy.** Keep `transcript.required=false` (today's fail-open, conformant under the new result rule), or require capture for some phases. Recommendation: keep it false. Revisit with C3.
- **H4. The EXP-V1-0005 0.3.0 recipe migration in AW**, including the `AgentName` versus `harness` reconciliation already noted at `harnesses/__init__.py:30-40`.
- **H5. Vocabulary.** Add `operation`, `operation key`, `finalization`, `MCP grant`, `deny` and `credential binding` to the orchestration vocabulary and the phase model.
- **H6. Closed versus extensible `error.kind`.** Recommendation: closed for v1.
- **H7. Whether `SupportsOperations` folds into `WorkspaceProvider`** after PR 4.
- **H8. The APSS experiment-bump process** beyond `experiment.toml` (open, owned by the APSS maintainers).
- **H9. Where PR 0 branches from.** Recommendation: stack it on `docs/runtime-research-20261012` so the parent plan's links resolve.

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1: OperationSpec loses the environment and launch challenge | **Accepted** | Confirmed: `AgentExecutionHandler.py:509-510`, `adapter.py:526`, `stream_helpers.py:67-72`, `stream_adapter.py:124-129`. Also found the API token merged into env (`managed_workspace.py:176-178`), and Rust's `CommandSpec` already carries `environment` (`lib/agentic-workspace/crates/workspace-core/src/lib.rs:346`). `OperationSpec` gains `environment` (non-secret), `credential_bindings` (refs) and `launch_marker {argv0, line}` with a non-readability MUST. The wrapper moves into the AW Docker provider, with syn still minting the marker. Credentials come off argv. Exit tests PR 3 (d)(e) and PR 7 |
| B2: finalization lacks a result and durability contract | **Accepted** | Both hooks are now used: `while_running` takes the moved capture call, `before_delete` the archive. New `FinalizationOutcome` with `retained`. `teardown` returns a typed `TeardownReport`. The registry is retained on failure, since both pop early (`adapter.py:459`, `docker.py:864-865`). Retry owner is named: syn backfill and orphan reaping. Fail-open versus SPEC:111 is resolved by declaring `required=false` (H3), with `success` defined in the result. Capture state is mapped from `AuthoritativeCapture`, not re-judged. `teardown_failure` is reported (`workspace_lifecycle.py:273-277`). New PRs 6 and 8 with exit tests |
| B3: byte-offset spool cannot give exact gaps | **Accepted** (owner-controlled option) | The Docker spool moves to a provider-owned host-side append-only collector outside every mount, so `integrity: exact`. The schema allows `lost_bytes: null` for `continuity_detected` providers. Cursor generations, foreign and expired cursor behaviour, a serialised page bound including base64, and `complete` = terminal plus drained are all defined. Tests PR 3 (f)-(j), plus PR 7 for UTF-8 and partial-line decoding |
| B4: immutable refs omitted | **Accepted** | `content-ref`, `environment-ref` and `credential-ref` schemas are designed now. Environment is brand-neutral (opaque `kind`, equality-only for core) with requested versus effective identity. The launch/v2 boundary is documented and adoption deferred (H2). Cosign is reframed as a Docker fact reported as the effective environment. v0.1.0 hash and revision rules are kept as debt (W-3.3-a/c) |
| B5: research table carries wrong classifications | **Accepted** | The map is atomised to clause ids with separate Py and Rust columns. #12 is reclassified: N/A for the manifest clause, a credential-delivery risk under W-6.3-a, with `environment` also secret-bearing (`config.py:494-504`). #8 is reclassified: holds, no domain branch found (`workspace_service.py:252` is adapter wiring). #5 separates "no manifest boundary" from host-path consumers. Area PASS labels are no longer converted to IT, and cells say IU until a named test id is cited. NE is used instead of asserted absence |
| I1: idempotency and failure semantics | **Accepted** | Concurrent same-key starts, same key with a different spec (`conflict`), record retention, and the lost-response retry are all specified. Typed `OperationError` for `unknown_operation` / `provider_unavailable`, separate from `lost`. The test is now 50 concurrent starts, not a sequential pair plus `docker top`. The in-process record is justified against ADR-060 explicitly |
| I2: Docker cancel feasibility | **Accepted** | A trusted pid comes from the pre-exec wrapper, with `setsid` group, TERM then KILL, `kill -0` confirmation, a start-time check against PID reuse, and escalation to container stop. New PR 3a feasibility gate. "No image change" is stated as contingent. Tests cover a grandchild and a TERM-trapping child |
| I3: recipe standard and harness ownership | **Accepted, and extended** | Found the recipe standard is EXP-V1-0005 v0.3.0, which already has a tools allowlist (§4.6) and MCP policy (§7), while AW's recipe is a stale 0.1.0 shape under a wrong id (`recipe.py:3-4`). §4 is rebuilt on those standards. Installed requirements go to EXP-V1-0006 capabilities plus the descriptor, not the recipe. The separate PR 10 migration (H4). The policy compiler is a sibling `launch_policy` module, leaving `HarnessPlugin` transcript-only. Static discovery and runtime readiness are split. Found the existing manifest lookup is dead (`_active_workspaces` exists nowhere), so it is deleted, not promoted |
| I4: weak exit evidence | **Accepted** | The staged-teardown tests are relabelled *regression*. launch/v1 fixtures run through both validator versions. The "symbol is gone" test is replaced by recorded provider calls plus a no-subprocess assertion with behaviour preserved. Added exit tests for PR 5 credentials, PR 10 and PR 11, and behaviour fixtures in APSS PR 1 |

No finding was rejected. Every reviewer citation I opened was accurate, and the code supported
each finding's conclusion. Where I went further than the review, the evidence is listed under §0.

## Readiness

Ready to implement PR 0 (the plan document). PR 1 onward is blocked on one human decision: H1,
confirming D1 (APSS JSON Schema as the contract surface, production Python Docker first, Rust
deferred to promotion).


## Implementation log

- 2026-10-13: PR 1 merged as AgentParadise/agent-paradise-standards-system#143 (`3bdbc33`). Deviation from §4.2: the observation page schema requires `state`, so the schema itself enforces "`complete` only on a terminal state". Accepted. Independent verifier: additive verdict parity, all failure fixtures rejected, 4/4 mutations caught. Credential-ref key-name filtering is a heuristic; the value prohibition is a spec rule (§5.1.3).
