# Plan: lifecycle-hazard semantics (LH-1..LH-7), failing cells at AW b88b1c3 / APSS ee926c6

Status: proposed, revised after cross-model review. Date: 2026-10-14. Phase: revise (no code, no commits).

This file is written to be committed **verbatim** as
`docs/plans/20261014_lifecycle-hazard-semantics.md` in syntropic137 (PR-0 below;
the name matches the existing `docs/plans/YYYYMMDD_slug.md` files). This phase
had only Read/Grep/Glob/Write/Skill and could not commit it.

**Repos.**

- **AW** = `AgentParadise/agentic-workspace` @ `b88b1c3`
- **APSS** = `AgentParadise/agent-paradise-standards-system` @ `ee926c6`
- **syntropic137** = this repository. Its submodule `lib/agentic-workspace` is pinned at `914129d`.

Every citation is the path from the root of the named repository, as `git ls-files` prints it.

## Evidence provenance

There are three evidence sources. They are kept apart below because they are not interchangeable.

| Source | What it is | Who read it |
|---|---|---|
| **PIN** | The harness's recorded verdicts at b88b1c3: the Python `FINDINGS` dict (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:672-685`), the real-daemon strict xfail (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:922-930`), the Rust pins (AW `implementations/docker/tests/operations.rs:1470-1487`), and the COVERAGE text (AW `tests/conformance/COVERAGE.md:146-215`) | research, review |
| **RUN** | The research phase's local `--runxfail` run of the Python matrix at b88b1c3: `7 failed, 6 passed, 1 skipped` | research |
| **CI** | AW Actions run [38593606789](https://github.com/AgentParadise/agentic-workspace/actions/runs/38593606789) at head `fd75db3f610e`, and run [38603430148](https://github.com/AgentParadise/agentic-workspace/actions/runs/38603430148) at head `0dde206da666` | review only |

Four things a reader should know about these sources:

- **Neither CI run is at b88b1c3.** The excerpts below are branch history from before the merge. They are not target-SHA executions.
- **Rust "ok" in CI does not mean the provider passed.** The Rust hazard tests assert the *pinned failing* verdicts (AW `implementations/docker/tests/operations.rs:1463`, `implementations/docker/tests/operations.rs:1493`). So `ok` means "fails exactly as pinned".
- **I did not read the CI logs myself.** This phase has no shell. The CI excerpts are as the reviewer reported them. PR-2 step 1 re-reads them and also records a b88b1c3 run.
- **Python line numbers were checked at both SHAs and agree.** In this phase I re-read the Python providers at syntropic137's submodule pin `914129d`. Every Python provider line cited below matches what the reviewer read at b88b1c3 (for example AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:430`, `:443`, `:446`, `:483`, `:654`, `:750`, `:809`, `:817`). The Rust file `implementations/docker/src/lib.rs` **did** drift: the blocking read is at `:488` at 914129d and at `:490` at b88b1c3. Rust citations below are at b88b1c3, as the research and review read them. The Rust operations, spool and conformance files do not exist at 914129d.

**CI excerpts (reviewer-reported, pre-merge heads):**

| Run (head) | Cell | Reported outcome |
|---|---|---|
| 38593606789 (`fd75db3`) | Local LH-1 | status `failed`, signal SIGTERM, descendants measured absent |
| 38593606789 (`fd75db3`) | Docker LH-7 (real daemon) | step 2 file_exists `{exists: false, regular_file: false}` |
| 38603430148 (`0dde206`) | hazard module | `1 failed, 8 passed, 1 skipped, 8 xfailed`; the failure is Local LH-1 |

---

## Problem

Against the 0.2.1 lifecycle-hazard fixtures, the three AW providers have **15 failing cells**:

- Python Docker: LH-3, LH-4, LH-6, LH-7
- Python Local: LH-1, LH-2, LH-4, LH-6, LH-7. LH-1 is a host-dependent strict xfail (APSS#146). LH-3 and LH-5 pass with their `given` never established (AW#68).
- Rust Docker: LH-2 through LH-7

In behaviour a caller can observe:

- **LH-3:** a cancel issued before the launch header blocks for the whole bound.
- **LH-4:** a workspace destroyed while a start is resolving credentials still launches that operation and returns a ref.
- **LH-6:** a drain that skipped evicted bytes never reports the stream as lossy.
- **LH-7:** reading a FIFO hangs the event loop (Local) or the thread (Rust).
- **LH-2:**
  - Local: a cancel retried after an interrupted one reports `failed` even though it killed the workload.
  - Rust: the retry returns `provider_unavailable` and never kills the workload.
- **LH-5 (Rust):** a container stuck in `Removing` never settles unless someone calls `status`.
- **Cancel outcome:** an unconfirmed cancel takes three different shapes across the providers: status `failed`, error `provider_unavailable`, or error `timeout`+ref (spec 5.1.4). The LH-1 fixture has no shape that an honest unconfirmed outcome can always match.

A previous fix run correctly refused (exec-667c38e28f5b), because its brief assumed the Python Docker cells already passed. They do not: each is still `xfail(strict=True)`.

---

## Cross-cutting decision 1: what an unconfirmed cancel looks like

LH-1, LH-2 and LH-3 all depend on this, so it is settled first and applied everywhere. Ratifying it is a human call (see "Needs a human decision").

**Rule (spec 5.1.4, APSS `standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:248-253`).** Keep the *call result* separate from the *terminal state*. The three termination failures are distinguished by a structured kind, never by parsing a message.

| What happened in `cancel` | Call result | Terminal state reported later by `status` |
|---|---|---|
| Every owned process confirmed gone | status `cancelled` | `cancelled` |
| The provider **ran** termination (signals sent, or `docker stop` exited 0) and could not confirm within its bound: survivors after KILL, unattributable orphans, container still `running`, container still `removing` past the wait, or the post-cancel wait elapsed | raise `OperationError{kind: timeout, ref}` | `failed`, with `cancel_signal_failure` metadata. Never `cancelled` (spec `:252-253`) |
| The provider could **not run** termination: the stop command could not start, `docker stop` exited non-zero, or the daemon could not be queried to inspect the result | raise `provider_unavailable`+ref (unchanged) | `failed` once settled |
| The caller abandoned the cancel mid-confirmation | the call is cancelled; the operation stays non-terminal | decided by the next confirmation that runs to completion |

**Inability to inspect counts as `provider_unavailable`, not `timeout`.** A daemon that cannot answer an inspection cannot answer anything. `timeout` means "the procedure ran, and the bound passed without proof". The plan adopts this split and states it in PR-1's spec sentence, so it is not left to each implementer.

**Fixture consequence.** The `timeout` alternative must not pin `descendant_alive: true`, because "unconfirmed" means "not known", not "known alive". See PR-1.

**Rejected:** accepting `{state: failed}` as a cancel result in the fixtures (the APSS#146 body's suggestion).

- It contradicts 5.1.4 and names a second unconfirmed shape that every consumer would have to branch on.
- It would also legitimise Local's LH-2 bug, where a confirmed kill is reported `failed`.

## Cross-cutting decision 2: admission closes durably when destruction begins

LH-4 needs all three of the following properties at once.

1. **Close at the right moment.** Admission closes at the first point where destruction is committed, and never before a `while_running` hook. The hook contract says that hook "may still exec into" the container (AW `lib/python/agentic_isolation/agentic_isolation/providers/base.py:356-359`). Docker `execute` goes through `operations.start` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:662-664`). So closing admission before the hook would break every `while_running` hook that runs a command.
2. **Stay closed.** A closed workspace never reopens. Any later `start` raises `resource_lost`, never `unknown_operation`. The tombstone is **never pruned**. Local already behaves this way: its `_closed` set is never discarded (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:369,711`).
3. **Check after resolve, and keep the barrier.** Admission is re-checked after credential resolution and before anything is spawned. Teardown **keeps** waiting on in-flight launch locks before it drops records. Closing admission stops new and still-resolving starts. The wait covers starts that were admitted earlier and are suspended in `_spawn` or `stdin.drain()` before they publish their record (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:430,443,446-447`). These are two different guarantees, and both are needed.

**Cost of never pruning.** Each destroyed workspace leaves one id string per provider process: about 100 bytes, or about 10 MB per 100k destroys between restarts. Local pays this today. It is recorded as a known cost (see Maintenance cost) rather than bought down with a pruning rule that reopens the hole.

---

## Per failing cell

**Verdict key:**

- **PROVIDER**: a provider bug, with the defect named
- **FIXTURE**: a fixture or spec gap, with the exact additive change
- **HARNESS**: a harness bug

The semantics given for each cell are provider-neutral.

### LH-1 double-fork orphan: Python Local (host-dependent strict xfail, APSS#146)

- **Observed:**
  - CI (`fd75db3`): status `failed`, SIGTERM, descendants absent.
  - PIN: COVERAGE (AW `tests/conformance/COVERAGE.md:207-215`) records it as host-dependent. When a foreign subreaper adopts the orphan, `cancel_signal_failure` says "…cannot be confirmed unrelated, so they were not signalled".
  - RUN: passes when no foreign subreaper is present.
- **Fixture** (APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-double-fork-orphan.json`, step 1) accepts one of:
  - `{state: cancelled, signal: SIGKILL}` with alive=false
  - `{kind: timeout, ref}` with alive=true
- **Verdict: FIXTURE + PROVIDER. Both changes are needed; neither alone flips the cell.**
  - FIXTURE: the timeout alternative pins alive=true.
  - PROVIDER: `cancel` returns `self._status(...)` unconditionally (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:562-568`). So the unconfirmed round set at `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:624-632` surfaces as status `failed`, not `timeout`+ref.
- **Semantics:** `cancelled` only when every owned process is confirmed gone. Otherwise raise `timeout`+ref.

### LH-2 interrupted cancel

**Python Local fails at step 3 cancel.**

- **Observed (RUN, verbatim):** `state "failed", exit_code 137, signal SIGKILL, cancel_signal_failure "cancel confirmation was interrupted before it completed", descendant_alive=False`.
- **Fixture** accepts `{state: cancelled}` with alive=false, or `{kind: timeout, ref}` with alive=true.
- **Verdict: PROVIDER.**
  - An interrupted round sets `operation.unconfirmed = True` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:589-592`).
  - Nothing ever clears that flag, and `_settle` checks it before `cancel_requested` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:506-509`).
  - So a later round that does confirm is overruled by an earlier round that was abandoned.
- **Semantics:**
  - An interrupted confirmation leaves the operation non-terminal. Step 2 already passes.
  - The **most recent confirmation that runs to completion** decides the outcome.
  - Settlement waits on the `stopping` lock (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:490-491`), so resetting the flag under that lock is race-free.

**Rust Docker fails at step 3 cancel.**

- **Observed (PIN, AW `implementations/docker/tests/operations.rs:1471-1474`):** `provider_unavailable` after about 7 s, with the workload alive.
- **Verdict: PROVIDER**, by reading the code; the review confirmed the reading.
  - `terminating` is set before the await (AW `implementations/docker/src/operations.rs:449-452`) and reset only when an `Err` is returned (AW `implementations/docker/src/operations.rs:457-459`).
  - The runner drops the cancel future after 300 ms (AW `crates/workspace-conformance/src/hazard.rs:344-357`). That leaves `terminating == true`.
  - The retry therefore computes `first = false`, skips `terminate`, waits, and returns `ProviderUnavailable` (AW `implementations/docker/src/operations.rs:473-484`).
- **Semantics:** the same as Local. An abandoned termination must not leave a claim that tells a retry "someone else is handling it".

### LH-3 cancel before the launch header

**Python Docker fails at step 1 cancel.**

- **Observed:** "did not settle within 30s" (RUN; PIN AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:674-675`).
- **Fixture:**
  - Step 1 has `settles_within_seconds: 30` and accepts `{state: cancelled}` with alive=false, or `{kind: timeout, ref}` with alive=true.
  - The spec says it MUST settle "without waiting for the header" (APSS `standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:378-382`).
- **Verdict: PROVIDER.** `cancel` waits `_LEADER_SECONDS = 30.0` for `leader_known` before doing anything (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:208,735-737`). That wait alone uses the whole bound.
- **Semantics:**
  - Cancel's wait for a header is bounded by the caller's `grace_seconds`, not by a provider constant.
  - With no header by then, escalate to `docker stop`. That fallback already exists (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:785-825`).
  - Report `cancelled` once the daemon shows `stopped` or `gone`. Otherwise use decision 1's mapping.

**Rust Docker fails at step 1 cancel.**

- **Observed (PIN, AW `implementations/docker/tests/operations.rs:1475-1477`):** `provider_unavailable` after about 9 s, and the late workload is measured alive.
- **Verdict: HARNESS first, then PROVIDER (wrong error kind).**
  - The Rust stand-in's late `exec` sleeps *before* exporting `AW_STANDIN` (AW `implementations/docker/tests/operations.rs:83` vs `implementations/docker/tests/operations.rs:95`).
  - It also never refuses an exec into a stopped container. The Python stand-in does (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:102-103`).
  - So "alive" is at least partly a stand-in artefact.
  - The provider's unconfirmed results are `ProviderUnavailable` (AW `implementations/docker/src/operations.rs:473-484`, and the stop path below), not `timeout`+ref.
  - **What the provider does once the stand-in is fixed has not been measured.** PR-2 measures it, and PR-6's LH-3 scope follows from that.
- **Semantics:** the same as Python Docker.

### LH-4 destroy during start: all three providers fail at step 0 start

- **Observed:** start returns a ref and launches once. Sources: RUN for both Python cells; PIN AW `implementations/docker/tests/operations.rs:1478-1480` for Rust.
- **Fixture** (APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-destroy-during-start.json`):
  - Step 0: `{kind: resource_lost}` or `{kind: cancelled}`, no ref, `launches: 0`, `operation_records: 0`.
  - Step 1 (a later start; APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-destroy-during-start.json:104,113,118`): `{kind: resource_lost}`, `launches: 0`, `operation_records: 0`.
- **Verdict: PROVIDER in all three, with two defects each.**
  1. **Step 0: admission is checked only before resolve.**
     - Docker checks at AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:353` and resolves at `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:414`.
     - Local checks at AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:351,355` and resolves at `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:398`.
     - Rust checks at AW `implementations/docker/src/operations.rs:1086-1092` and resolves at `implementations/docker/src/operations.rs:821`.
     - Docker also marks the workspace only after the container has been removed (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:927-928`).
  2. **Step 1 (masked today by the step-0 failure): closure is missing, transient, or the wrong kind.**
     - Docker's `_forgetting` is discarded when `forget_workspace` returns (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:497`). Its refusals are `unknown_operation` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:352,354`).
     - Local's `_closed` is durable, but it raises `unknown_operation` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:370`).
     - Rust's `Finalizing` is an RAII mark that disappears when finalize ends (AW `implementations/docker/src/operations.rs:656,672,1155`). The harness completes finalize before step 1 (AW `implementations/docker/tests/operations.rs:1382`).
- **Semantics:** decision 2, in full. Never `unknown_operation` for a destroyed workspace.

### LH-5 stuck removal: Rust Docker fails at step 1 observe (not settled within 120 s)

- **Observed:** PIN AW `implementations/docker/tests/operations.rs:1481-1483`. A recording decorator proves no `status` call was made (AW `implementations/docker/tests/operations.rs:1501-1515`).
- **Fixture** (APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-stuck-removal-timeout-settles.json`, step 1, `repeat_until_complete`, 120 s): a complete page `{state: timed_out}`, or `{kind: provider_unavailable, ref}`.
- **Verdict: PROVIDER. Two defects.**
  1. `observe` (AW `implementations/docker/src/operations.rs:1115-1139`) never drives settlement. Only `status` does (AW `implementations/docker/src/operations.rs:1099-1113`).
  2. **No persistent deadline exists to reuse.**
     - `settle` returns `()` and gives up while the container is `Removing` (AW `implementations/docker/src/operations.rs:389,400`).
     - Its deadline is recreated on every call, and only `wait=true` uses it (AW `implementations/docker/src/operations.rs:390,393`).
     - So repeating today's `status` path from `observe` would never turn a permanent `Removing` into an error.
- **Reference that passes:** Python Docker records `settle_by` once, when the client finishes (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:559-560`). Its single fallible `_resettle` raises `provider_unavailable`+ref past that deadline (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:647-668`), and it is called by both `status` and `observe` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:644,718,727`).
- **Semantics:**
  - Every read drives settlement.
  - The settlement deadline is fixed **once**, when the operation's client finishes, and stored on the operation.
  - Past the deadline, a stuck backend raises `provider_unavailable`+ref from whichever read is in flight.
  - Status is never required.

### LH-6 drain with a gap: all three providers fail at step 2 observe

- **Observed:** a page `{gap: {lost_bytes: 8}, complete: false}` with no `loss_detected`. Sources: RUN for Python; PIN AW `implementations/docker/tests/operations.rs:1484-1485` for Rust.
- **Fixture** (APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-drain-with-gap-reports-loss.json`):
  - Step 2: `{gap: {lost_bytes: 8}, loss_detected: true}`.
  - Step 3: `{complete: true, loss_detected: true}`, no gap.
  - Steps 0-1 are start and status (APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-drain-with-gap-reports-loss.json:11,61`). They are not observation pages, so they cannot assert that the field is absent.
- **Verdict: PROVIDER. One rule, missing from both spools.**
  - Python never sets it (AW `lib/python/agentic_isolation/agentic_isolation/providers/operation_spool.py:111-132`).
  - Rust hard-codes `None` (AW `crates/workspace-core/src/operations/spool.rs:124`).
  - The harness's `FINDINGS` text names the completing page, but the first miss is step 2.
- **Semantics** (spec 5.1.5, APSS `standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:278-283`):
  - A page carries `loss_detected: true` iff its generation evicted bytes before that page's `next_cursor`. In spool terms that is `base > 0`, because `next_cursor >= base` always holds after the clamp (AW `lib/python/agentic_isolation/agentic_isolation/providers/operation_spool.py:87-89`).
  - `gap` stays per page.
  - The rule is stateless and needs no cursor change.

### LH-7 FIFO in the workspace

**Python Docker (real daemon) fails at step 2 file_exists.**

- **Observed:** `{exists: false, regular_file: false}` (CI `fd75db3`; PIN AW `tests/conformance/COVERAGE.md:205-206`).
- **Fixture:** `{exists: true, regular_file: false}` or `{kind: rejected_policy}`.
- **Verdict: PROVIDER.** This needs ratification (decision B below).
  - `file_exists` deliberately answers `False` for an entry that exists (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:817,824-825`). That is a false statement about the filesystem.
  - The spec's MUST sentences (APSS `standards-experimental/v1/EXP-V1-0006-workspace/docs/01_spec.md:400-404`) do not require `exists: true`. The fixture's stricter reading is the right one: an existence probe that lies teaches callers that an occupied path is free.
  - No syntropic137 code under `packages/` or `apps/` calls `.file_exists(` or `.read_file(`.
- **Second defect, at step 3 (masked today):**
  - `NotARegularFileError` subclasses `ValueError` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:1190`).
  - The harness `_probe` catches only `OperationFailure` and `OSError` (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:608,610`).
  - So the refusal would escape as a test *error*, not a `FixtureMismatch`. That is a HARNESS mapping gap, fixed in PR-2.

**Python Local fails at step 3: `read_file` blocks past 10 s.**

- **Verdict: PROVIDER.** `read_file` calls `exists()` and then a plain blocking `open` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local.py:260-266`).

**Rust Docker fails at step 2 (`collect` blocks past 10 s).**

- **Verdict: PROVIDER.** `collect` canonicalizes, checks containment, then calls `fs::read` (AW `implementations/docker/src/lib.rs:490`), which blocks on a FIFO that has no writer.
- The harness drives both file probes through `collect` (AW `tests/conformance/COVERAGE.md:170-171`). That is acceptable once `collect` refuses with an error the harness maps to `rejected_policy` (see PR-6).

**Semantics, all providers:**

- The existence probe answers truthfully and never opens the entry.
- Reading a non-regular file is refused without blocking, with a typed error that maps to `rejected_policy`.
- The type check is made on the opened descriptor, so an inode swapped in after path resolution cannot block the read.
- Finalize still settles.

---

## Approach: ordered PRs

Each PR exits when its cells flip to PASS **and** each listed revert mutation turns its own test red. The PR author runs every revert mutation once and records the resulting first-miss line in the PR body. A mutation that leaves its test green means the test does not test the fix, and the PR is not done.

### PR-0 (syntropic137, docs only): this plan

- Commit this document as `docs/plans/20261014_lifecycle-hazard-semantics.md`.
- Before committing, re-audit every citation at the stated SHAs. This phase could not run `git show`.

### PR-1 (APSS 0.2.2, additive fixtures and one spec sentence). Blocked on decision A.

**Fixture files.** These three steps have the same shape:

- `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-double-fork-orphan.json`, step 1
- the LH-2 interrupted-cancel fixture under `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/`, step 3
- `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-cancel-before-launch-header.json`, step 1

**Change:**

- In each `{kind: timeout, ref}` alternative, delete the `descendant_alive: true` constraint.
- The `cancelled` alternative keeps `descendant_alive: false`.
- This is strictly additive: every outcome that 0.2.1 accepts is still accepted.

**Spec 5.1.4/5.1.11, one paragraph:**

> An executed termination that cannot be confirmed within the provider's bound is `timeout` with `ref`, whatever a harness later measures. A provider that could not execute or inspect termination reports `provider_unavailable` with `ref`.

**Release:**

- Version lock and changelog for 0.2.2. The 0.2.1 lock commit is `65d02bb`.
- Closes APSS#146 with this resolution.

**Not changed:**

- LH-6: the fixture already follows 5.1.5.
- LH-7: the fixture is right.
- No new steps are added. A new step is a new requirement, so it belongs in 0.3.

**Exit:**

- The APSS fixture validation passes.
- Each of the three steps still rejects `{state: cancelled}` with alive=true.

**Revert mutation:** restore the pin. AW Local LH-1 then fails at step 1 again, after PR-5.

### PR-2 (AW harness, Python + Rust): make the matrix trustworthy and re-baseline it

1. **Observations at the target SHA.**
   - Run the Python and Rust hazard suites at b88b1c3. Record each cell's first-miss line in AW `tests/conformance/COVERAGE.md`.
   - Re-read runs 38593606789 and 38603430148, and label them as pre-merge evidence.
   - If any line contradicts an "Observed" entry above, amend this plan before any provider PR.
2. **Pin the first miss, including its outcome.**
   - Each `FINDINGS` entry (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:672-685`) becomes `(step, call, outcome fields)`. Assert that the raised `FixtureMismatch` names them, as LH-1 already does.
   - Apply the same narrowing to the real-daemon LH-7 strict xfail (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:925`). It must name step 2 `file_exists` with `{exists: false}`, so a moved failure or a timeout no longer stays green.
   - The Rust pins (AW `implementations/docker/tests/operations.rs:1470-1487`) gain the same stable outcome fields.
3. **Liveness fails closed (AW#68).**
   - An unreadable `/proc/<pid>/environ` becomes `Unmeasurable`, never "not ours". The two fail-open sites are Rust `unwrap_or_default` (AW `crates/workspace-conformance/src/hazard.rs:497-499`) and Python `except OSError: continue` (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:243-258`).
   - A cell whose `alive` could not be measured reports NOT RUN.
4. **Unestablished `given` reports NOT RUN.** Local LH-3 and LH-5 report NOT RUN when their `given` cannot be established.
5. **The Rust stand-in models a stopped container.**
   - Export `AW_STANDIN` before the late-exec sleep (AW `implementations/docker/tests/operations.rs:83,95`).
   - Refuse the exec with exit 137 when the container is stopped, as the Python stand-in does (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:102-103`).
6. **Typed file refusals in `_probe`.**
   - Map `NotARegularFileError` to `rejected_policy`.
   - Any other non-`OSError` exception becomes `FixtureMismatch("untyped error …")` instead of a test error.
7. **Record which alternative matched.** `_matches` and its Rust twin return the index of the alternative that matched. Where the outcome is deterministic, assert it:
   - Docker LH-1, LH-2 and LH-5: `cancelled` / pinned.
   - Local LH-2 after PR-5: `cancelled`.
   - Rust LH-2 after PR-6: `cancelled`.
   - This is the counterweight to PR-1's loosening. A provider that starts answering `timeout` where it used to confirm goes red.
8. Vendor APSS 0.2.2 once PR-1 lands. Until then, PR-2 ships against 0.2.1.

**Exit, per cell:**

- **The new baseline is whatever PR-2 measures.** Each cell is recorded as PASS, FAIL at a pinned `(step, call, outcome)`, or NOT RUN with its reason.
- **Some cells may change only because measurement changed.** These are:
  - Rust LH-3 (the stand-in fix; it is re-pinned to what it now measures)
  - Local LH-3 and LH-5 (now NOT RUN)
  - any cell that depends on alive=false on a host where alive cannot be measured (now NOT RUN)
- **Any other cell that changes fails the PR.**
- **The Python `--runxfail` baseline is recomputed.** The research's `7 failed, 6 passed, 1 skipped` is retired.

**New negative tests:**

- A fake with an unreadable environ yields NOT RUN.
- A stand-in whose late exec is refused measures alive=false.
- A probe that raises a bare `ValueError` yields `FixtureMismatch`.
- A cell failing at a different step than its pin goes red.

**Revert mutations:**

- Restore `unwrap_or_default` / `except OSError: continue`: the unreadable-environ test fails.
- Widen one pin back to "any mismatch": the different-step test fails.

### PR-3 (AW spools, Python + Rust): `loss_detected`. Flips LH-6 in all three columns.

**Changes:**

- **Python:** `OperationSpool._build` (AW `lib/python/agentic_isolation/agentic_isolation/providers/operation_spool.py:111-132`) sets `loss_detected=True if self._base > 0 else MISSING`.
- **Rust:** AW `crates/workspace-core/src/operations/spool.rs:124` sets `loss_detected: (base > 0).then_some(true)`. The contract refuses `Some(false)` (AW `crates/workspace-core/src/operations/contract.rs:568-575`).
- **Both changes go in one PR.** They are one rule in two languages, and the LH-6 fixture run against all three columns is what keeps them in agreement.

**Unit tests, one set per spool:**

- (a) Pages before any eviction carry no `loss_detected`.
- (b) The `gap` page carries `loss_detected: true`.
- (c) The completing page carries it, with no `gap`.
- (d) A fresh drain from `cursor=None` after eviction carries it on every page.

**Revert mutation:** drop the assignment. Tests (b)-(d) fail, and LH-6 returns to its pinned step-2 miss.

### PR-3b (AW Python): extract `contained_files.py`. Precedes PR-4 and PR-5.

**Move:**

- Move `_open_contained` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:1257`) and `NotARegularFileError` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:1190`) into `lib/python/agentic_isolation/agentic_isolation/providers/contained_files.py`, unchanged.
- `NotARegularFileError` keeps its `ValueError` base. The existing tests (AW `lib/python/agentic_isolation/tests/test_docker_contract_debt.py:302-340`) depend on that base.

**Add `exists_contained`:**

- It walks the path with `O_NOFOLLOW` and `fstatat`s the final component without opening it.
- It returns `(exists, regular)`.

**Behaviour:**

- No change for Docker in this PR.
- **Exit:** the existing Docker contained-file tests pass unchanged.
- **Revert mutation:** not applicable; this is a pure move plus a new tested function.
- `exists_contained` gets its own unit tests: a regular file, a FIFO, a symlink escaping the workspace, and a missing path.

This is an explicit PR so that PR-4 and PR-5 can run in parallel after it.

### PR-4 (AW Python Docker): LH-3, LH-4, LH-7, and the unconfirmed-cancel mapping

**LH-3:**

- In `cancel`, replace `asyncio.timeout(_LEADER_SECONDS)` with `asyncio.timeout(grace_seconds)` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:735-737`).
- Delete `_LEADER_SECONDS` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:205-208`).
- Update the note at AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:745-748`.

**Unconfirmed mapping (decision 1)**, inside `_terminate_group` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:785-825`):

| Branch | Lines | Kind after this PR |
|---|---|---|
| stop command could not start | `:787-790` | `provider_unavailable`+ref, unchanged |
| `docker stop` exited non-zero | `:791-797` | `provider_unavailable`+ref, unchanged |
| inspection failed after a successful stop | `:806-808` | `provider_unavailable`+ref, unchanged |
| stop succeeded, container still `running` | `:809-816` | **`timeout`+ref** |
| stop succeeded, still `removing` past `_REMOVAL_WAIT_SECONDS` | `:817-825` | **`timeout`+ref** |

How the change works:

- The kind is the structured discriminator. Nothing parses a message.
- `cancel` already lets the failure propagate (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:749-756`) and leaves `cancel_confirmed` false. Settlement then publishes `failed` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:624-627`), as decision 1 requires.
- The timeout path's `except OperationFailure` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:530-533`) catches both kinds, so it needs no change.
- This replaces the earlier draft's "convert the final status in `cancel`". That draft change was dead code: on a normal return `cancel_confirmed` is always `True` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:756`).

**LH-4 (decision 2):**

- **Where admission closes.** Add `close_admission(workspace_id)` to `DockerOperations`. It is called inside `_teardown_locked` **after** `while_running` has returned successfully and **before** `_measure_usage`/`_stop` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:974-986`). It is also called at the start of the retained-retry branch (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:964-969`).
- **A failed `while_running` leaves admission open.** The workspace stays registered and live (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:977-980`).
- **Durable tombstone.** `_forgetting` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:314,489,497`) is replaced by a `_closed` set that is never discarded.
- **Admission checks in `start`, all raising `resource_lost` with no ref:**
  - The `_closed` check moves ahead of the "has no container" check (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:350-354`). That way a destroyed workspace is refused as `resource_lost` whatever its handle says.
  - It is re-checked in `_start_locked` after the credential loop, between AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:414` and `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:415`.
- **`forget_workspace` keeps its launch-lock wait** (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:491-494`). It drops records only afterwards, so a start admitted before the close and suspended in `_spawn` or `drain` cannot publish a record after cleanup.
- **The harness probe may need updating.** If the harness's "destroy reached operation teardown" probe (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:479-491`) reads `_forgetting` by name, update it in this PR.

**LH-7:** `file_exists` uses `exists_contained` and answers `True` for any entry inside the workspace, regular or not. `read_file` is unchanged: it still raises `NotARegularFileError`, which PR-2 maps to `rejected_policy`.

**Exit:**

- The Docker `FINDINGS` entries for LH-3 and LH-4, and for LH-6 (after PR-3), are removed, and those cells PASS.
- The real-daemon LH-7 xfail is removed, and the test passes against a real daemon.
- Docker LH-1, LH-2 and LH-5 stay PASS, with the matched alternative pinned as in PR-2.

**Revert mutations, one per mechanism:**

| Mutation | Expected red |
|---|---|
| Restore `_LEADER_SECONDS` | LH-3 fails at step 1 |
| Delete the post-resolve re-check | LH-4 fails at step 0 with `launches: 1` |
| Move `close_admission` back to after `_teardown_locked` | LH-4 fails at step 0. This proves placement |
| Make `_closed` transient again (discard at the end of `forget_workspace`) | **LH-4 step 1** fails. This is a unit test that destroys, then starts, and expects `resource_lost`, zero records and zero spawns |
| Remove `forget_workspace`'s launch-lock wait | New deterministic unit test fails. The test gates `_spawn` on an event so a start is paused *after* the post-resolve check and before record insertion, then destroys, resumes, and asserts `_operations` and `_by_key` hold nothing for the workspace. The LH-4 fixture pauses earlier and cannot catch this |
| Call `close_admission` before `while_running` | New unit test fails. Its `while_running` hook calls `execute("true")` and expects exit 0 |
| Restore `provider_unavailable` at `:809-816` / `:817-825` | Two unit tests fail, one per branch. Each uses a fake daemon whose `stop` exits 0 while inspection keeps answering `running` (or `removing`), and expects `timeout`+ref. A third test, where `stop` exits non-zero, still expects `provider_unavailable`. Reverting either `timeout` branch fails only its own test |
| Restore `except NotARegularFileError: return False` | LH-7 fails at step 2 |

### PR-5 (AW Python Local): LH-1, LH-2, LH-4, LH-7. After PR-3b; LH-1 also needs PR-1.

**LH-2:**

- At the top of `_signal_and_confirm` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:594`), which runs under `stopping`, set `operation.unconfirmed = False`.
- The flag is then set only by this round (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:618,625,635`) or by an interruption of this round (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:589-592`).
- So the latest round that runs to completion decides.
- The earlier `cancel_signal_failure` note is kept as history.

**LH-1 (decision 1):**

- After `_terminate` returns, `cancel` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:562-568`) checks this round's `unconfirmed`.
- If it is set, `cancel` awaits the collector, then raises `OperationFailure(OperationError(kind="timeout", ref=ref))` instead of returning the status.

**Internal cancel caller:**

- `forget_workspace` cancels each operation (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:716-718`).
- With the change above, an unconfirmed cancel would now raise and abort `destroy` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local.py:137-143`). That would leave the workspace directory and its records behind.
- So `forget_workspace` catches `OperationFailure` there, records it, and continues.

**LH-4 (decision 2):**

- `_admit` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:368-370`) raises `resource_lost`.
- `_admit` is re-called in `_launch` after the credential loop, between AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:398` and `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:399`.
- `_closed` stays durable and unpruned, as it is today.
- `forget_workspace` keeps its launch-lock wait and its cancels.

**LH-7:**

- `read_file` and `file_exists` (AW `lib/python/agentic_isolation/agentic_isolation/providers/local.py:254-275`) use `contained_files.py`, with the relative path computed as today (`path.lstrip("/")`).
- `read_file` raises `NotARegularFileError` for a FIFO without blocking.
- Symlinks that escape the workspace are now refused. Decision E covers whether to accept that.

**Exit:**

- The Local `FINDINGS` entries for LH-2, LH-4, LH-6 and LH-7 are removed, and those cells PASS.
- The LH-1 strict xfail is removed. It matches `timeout` when a foreign subreaper is present and `cancelled` otherwise; both are measured on CI.

**Revert mutations:**

| Mutation | Expected red |
|---|---|
| Drop the per-round reset | LH-2 fails at step 3 with `state "failed"` |
| Drop the post-resolve `_admit` | LH-4 fails at step 0 |
| Restore `unknown_operation` in `_admit` | LH-4 step 1 unit test fails |
| Restore the plain `open` | LH-7 blocks at step 3 |
| Revert `cancel` to `return self._status(...)` | Unit test with a fake `_owned` reporting orphans fails. It expects `error.kind == "timeout"` and `error.ref == ref` |
| Remove `forget_workspace`'s catch | Unit test fails. It destroys a workspace whose cancel cannot confirm, and expects the directory to be gone and no records left |
| Follow symlinks again (only if decision E accepts the tightening) | Escaping-symlink test fails |

### PR-6 (AW Rust Docker): LH-2, LH-3 (scope from PR-2), LH-4, LH-5, LH-7, unconfirmed mapping

**LH-2:** a drop guard resets `terminating` around the `terminate` await (AW `implementations/docker/src/operations.rs:449-459`). An abandoned cancel then leaves no claim behind, and a retry re-drives `terminate`.

- **Rejected:** a detached termination task. It would outlive its caller, and `finalize` would have to join it.

**Unconfirmed mapping (decision 1).**

- **The current defect:** `stop_confirmed` collapses command failure and executed-but-unconfirmed into a single `String`, and `terminate` maps all of it to `ProviderUnavailable` (AW `implementations/docker/src/operations.rs:524,534,548,553`).
- **The change:** replace that `String` with an enum. The internal type is `enum StopOutcome { Confirmed, Unconfirmed(String) }`; a command that failed to run, or an inspection that failed, stays an `Err`.
- **Mapping in `terminate`:** `Unconfirmed` maps to `ErrorKind::Timeout`+ref, and `Err` maps to `ProviderUnavailable`+ref.
- **The post-cancel wait** (AW `implementations/docker/src/operations.rs:473-484`) also returns `Timeout`+ref when it elapses.
- **`finalize` must keep its behaviour.** It cancels the records it finds (AW `implementations/docker/src/operations.rs:1174-1183`). If it branches on the cancel error's kind, it must treat `Timeout` exactly as it treats `ProviderUnavailable` today. This is the same trap as Local's `forget_workspace` above.

**LH-4 (decision 2):**

- **Durable closure.** On completion, `finalize` records the workspace in a `closed` set that is never pruned, before the `Finalizing` mark drops (AW `implementations/docker/src/operations.rs:656,672,1155`). This matches Python Local's `_closed`.
- **Outer check.** `start` (AW `implementations/docker/src/operations.rs:1086-1092`) refuses with `ResourceLost` and no record if the workspace is either finalizing or closed.
- **Post-resolve check.** `launch` makes the same check after secret resolution (AW `implementations/docker/src/operations.rs:821`), before anything is spawned.
- **Ordering.** `finalize` sets its mark before it waits on launch locks (AW `implementations/docker/src/operations.rs:1155-1164`), and it keeps that wait.

**LH-5:**

- **Persistent deadline.** Add `settle_by: Option<Instant>` to the operation record. It is set exactly once, when settlement first finds the client finished but the outcome undecided, as `now + REMOVAL_WAIT` (AW `implementations/docker/src/operations.rs:49`). It is never recomputed.
- **One shared fallible resettle.** Add `resettle(&record) -> Result<(), OperationError>`. It re-probes, settles when it can, and returns `ProviderUnavailable`+ref when the container is still `Removing` at or past `settle_by`.
- **Both reads call it.** `status` (AW `implementations/docker/src/operations.rs:1099-1113`) calls it. `observe` (AW `implementations/docker/src/operations.rs:1115-1139`) calls it before and after its wait, mirroring AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:718,727`.

**LH-7:**

- `collect` (AW `implementations/docker/src/lib.rs:474-495`) keeps canonicalization and containment (AW `implementations/docker/src/lib.rs:485`).
- It then opens with `O_RDONLY | O_NONBLOCK | O_NOFOLLOW`, `fstat`s the descriptor, and refuses a non-regular file **before reading**.
- **Refusal type:** the existing `WorkspaceError::UnsafePath(String)` variant (enum `WorkspaceError` in AW `crates/workspace-core/src/lib.rs`, `:455` at b88b1c3). Its message names the file type, for example `"outputs/pipe: not a regular file (fifo)"`.
  - **Public meaning:** "this path is refused by the provider's path policy", which covers both containment escapes and non-regular files.
  - **Mapping:** the harness already maps `UnsafePath` to `rejected_policy` (AW `implementations/docker/tests/operations.rs:1305`).
  - **Why not a new variant:** adding one would break exhaustive matches on a public enum that is not `#[non_exhaustive]`. The Python analogue already raises both refusals as `ValueError` subclasses.

**Exit:**

- Each pin at AW `implementations/docker/tests/operations.rs:1470-1487` reads `pass`, with LH-3 judged against its PR-2 re-pin.
- LH-2's matched alternative is pinned `cancelled`.
- The recording decorator still proves LH-5 passes with **no** `status` call (AW `implementations/docker/tests/operations.rs:1501-1515`).

**Revert mutations, one per mechanism:**

| Mutation | Expected red |
|---|---|
| Remove the drop guard | LH-2 returns to `fail 3 cancel` |
| Remove the post-resolve check | LH-4 returns to `fail 0 start` |
| Remove the durable `closed` set (keep only `Finalizing`) | LH-4 fails at **step 1**. The LH-4 cell drives both steps |
| Remove `observe`'s resettle | LH-5 returns to `fail 1 observe` |
| Recompute `settle_by` on each call | New paused-clock unit test fails. It observes repeatedly before the deadline (each page incomplete, no error), then advances past the same deadline while removal stays stuck, and expects `ProviderUnavailable`+ref |
| Map `StopOutcome::Unconfirmed` back to `ProviderUnavailable` | New unit test fails. Its stand-in `stop` succeeds and inspection keeps `running`; it expects `Timeout`. A sibling test, where `stop` exits non-zero, still expects `ProviderUnavailable` |
| Restore `fs::read` without the type check | LH-7 returns to blocking at step 2 |
| Remove the `fstat` (check by path type only) | New unit test fails. It drives the post-canonicalization read helper directly on a FIFO path, covering an inode swapped in after canonicalization |

### PR-7 (syntropic137, after an AW release): consume it

- Bump the `lib/agentic-workspace` pin (currently `914129d`) and `PINNED_DIGESTS` once AW has released through its protected `release` channel. This plan does not schedule that.
- **The one in-repo consumer is unaffected.** `stream_adapter.py` (syntropic137 `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py:276-284`) already catches and logs any exception from `cancel`.
- **Behaviour change in that consumer.** An unconfirmed cancel is now logged there rather than passed to `_settle` as a `failed` status. Its primary error is still re-raised.

### Order

```
PR-0
PR-1 (blocked on decision A)  ∥  PR-2
PR-3  ∥  PR-3b                       (after PR-2)
PR-4  ∥  PR-5  ∥  PR-6               (after PR-3 and PR-3b; PR-5's LH-1 half after PR-1)
PR-7                                 (after an AW release)
```

- **PR-2 comes before any fix** because it makes a flip mean something.
- **Without PR-1,** PR-5 lands everything except removing the LH-1 xfail.

---

## Rejected alternatives

1. **Accept `{state: failed}` in the fixtures (APSS#146 as written).** It contradicts 5.1.4, adds a second unconfirmed shape, and would pass Local's LH-2 bug.
2. **Let teardown cancel the start's coroutine.** Teardown does not own the caller's task, and a resolver may shield itself from cancellation. A re-check local to `start` works with every resolver.
3. **Drop the teardown launch-lock wait once admission closes.** That leaves a window between admission and record publication in which records appear after cleanup. Closing admission and waiting for admitted work are separate guarantees.
4. **Prune admission tombstones on the record-retention clock.** A stale `Workspace` handle presented after expiry would be readmitted, and Local would recreate the directory (AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:406`). The cost of never pruning is bounded and already paid by Local.
5. **Close admission at the very start of teardown.** That breaks `while_running` hooks that exec, which the contract allows (AW `lib/python/agentic_isolation/agentic_isolation/providers/base.py:356-359`).
6. **Keep Docker `file_exists` returning `False` and relax LH-7.** That ratifies a false answer, and removes the only probe that tells "absent" apart from "present and unsafe".
7. **A new Rust `WorkspaceError` variant for non-regular files.** It breaks exhaustive matches for no semantic gain over `UnsafePath`.
8. **Settle LH-6 per consumer, with a lossy bit in the cursor.** It changes the cursor format, and the per-generation wording does not ask for it.
9. **Fix providers first and the harness later.** `xfail(raises=FixtureMismatch)` accepts any mismatch, so a fix that only moved the failure would look like progress.

## Maintenance cost

**Net new surface:**

- One extracted Python module (`contained_files.py`). It removes duplication rather than adding it.
- One method (`close_admission`).
- One flag reset.
- One Rust drop guard, one Rust enum (`StopOutcome`), one stored deadline (`settle_by`), and one shared `resettle`.
- Harness pins that each grow by step, outcome and matched alternative.

**Deleted:** `_LEADER_SECONDS` and the transient `_forgetting`.

**Tombstones** grow by one id per destroyed workspace per provider process, never pruned. That is about 10 MB per 100k destroys between restarts. Local already pays this. If long-lived providers at the 1,000-execution target make it matter, the remedy is a registry-backed validity check, not pruning. File an AW issue for it when PR-4 lands.

**Two spools, one rule.** The two spools must keep one rule; the LH-6 fixture plus one unit-test set per spool enforce it.

## Risks

| Risk | Signal |
|---|---|
| PR-1's loosening lets a provider answer `timeout` where it used to confirm | The matched-alternative pins from PR-2 go red |
| A grace-bounded header wait stops the **whole container** far more often, killing sibling operations in that workspace | The `cancel_escalation: container_stopped` metadata rate. Siblings settling `failed`/`lost` right after an unrelated cancel. See decision D |
| Python Docker LH-3 can still exceed 30 s if a stopped container sits in `removing` (the wait is 30 s, at AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:184,800`) | It does not occur with the stand-in or a healthy daemon. If it does occur, the outcome is `timeout`+ref, still within the 5.1.4 shape but late |
| Docker `file_exists` → `True` for FIFOs changes an external API | No syntropic137 consumer. An external caller sees `read_file` raise `NotARegularFileError` after `exists` returned `True` |
| Local refuses escaping symlinks after PR-5 | A Local test or user path through such a symlink fails. See decision E |
| Admission closed while a teardown that failed after `while_running` waits for a retry | Starts are refused on a workspace whose container may still exist. This is intended: destruction began |
| Rust diagnoses (LH-2/4/5, StopOutcome lines) come from the research and review at b88b1c3, not from this phase | PR-2's first-miss records. If a measured miss differs from its pin, re-scope that cell in PR-6 |
| Liveness fail-closed turns some PASS cells NOT RUN on hidepid CI hosts | The PR-2 COVERAGE diff. Those cells were never measured |

## Verification

From AW `lib/python/agentic_isolation`:

```
uv run --extra dev python -m pytest -q -rsx tests/test_behaviour_hazards.py -k test_provider_meets_lifecycle_hazard
uv run --extra dev python -m pytest -q -rsx --runxfail tests/test_behaviour_hazards.py -k test_provider_meets_lifecycle_hazard
uv run --extra dev python -m pytest -q tests/test_docker_contract_debt.py tests/test_docker_operations.py
```

- After each PR, the first command is green, and no `xfail` remains for the cells that PR owns.
- The second command's failure count drops by exactly that PR's cells, measured against the **post-PR-2 baseline**.
- The real-daemon LH-7 test (AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:922-963`) passes on a Docker host once its xfail is removed.

From AW root:

```
cargo test --manifest-path implementations/docker/Cargo.toml --test operations hazards
cargo test --manifest-path crates/workspace-conformance/Cargo.toml
cargo test --manifest-path crates/workspace-core/Cargo.toml operations::spool
```

- The pins at AW `implementations/docker/tests/operations.rs:1470-1487` read `pass`.
- `lh6_completion_without_loss_detected_fails` (AW `crates/workspace-conformance/src/hazard.rs:600`) still passes.

## Out of scope

- Any code change in this phase, and any syntropic137 code. Provider and harness behaviour belongs in AW (syntropic137 `CLAUDE.md`, "Where does this change belong?").
- New APSS fixture requirements, for example a cross-generation `loss_detected` step. That is a 0.3 change.
- Local containment beyond the two file calls (`write_file`, AW `lib/python/agentic_isolation/agentic_isolation/providers/local.py:245`).
- Workflow files, and the `PINNED_DIGESTS` bump (PR-7 is listed, not scheduled).

## Needs a human decision

- **A. The unconfirmed-cancel shape** (APSS spec owner).
  - Ratify decision 1: executed-but-unconfirmed is `timeout`+ref, could-not-execute or could-not-inspect is `provider_unavailable`+ref, the state is `failed`, and the fixture drops the alive pin.
  - The alternative is APSS#146's "accept `state: failed`".
  - **Blocks:** PR-1 and PR-5's LH-1 exit.
- **B. LH-7 `exists` for a FIFO** (APSS spec owner + AW).
  - The plan says `exists: true` and the read is refused. That reverses documented Docker behaviour.
  - **Blocks:** PR-4's LH-7 half.
- **C. `loss_detected` scope.** Settled: per generation. The earlier concern does not arise, because LH-6 steps 0-1 are not observation pages. Listed only so the record shows it was closed.
- **D. Cancel collateral.** With the header wait bounded by `grace_seconds`, escalating to `docker stop` (which kills every operation in the workspace) becomes reachable under ordinary load. The options:
  - accept it
  - set a floor, such as `max(grace_seconds, 5)`
  - let the spec allow `timeout`+ref there without stopping anything

  The plan proceeds with "accept" unless someone overrides it.
- **E. Local symlink tightening.** Accept it as part of PR-5, or keep Local's old path resolution and add only the file-type check.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| B1 Rust LH-4 step 1 still admitted | **accepted** | Decision 2 now requires durable closure. PR-6 adds a never-pruned `closed` set written as `finalize` completes, checked both pre-launch and post-resolve. A separate revert mutation (drop the durable set) must fail LH-4 **step 1**. Applied the same reasoning to Python Docker, whose `_forgetting` is discarded at AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:497`; PR-4 adds a step-1 unit test and mutation |
| B2 Rust LH-5 has no persistent deadline | **accepted** | PR-6 specifies `settle_by: Option<Instant>`, set once when settlement is first undecided, and a shared fallible `resettle` used by `status` and `observe`, mirroring AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:560,647-668`. Added a paused-clock test across one deadline, and a "recompute per call" mutation separate from the "remove observe's resettle" mutation |
| B3 dropping Docker's launch-lock wait races record publication | **accepted** | Confirmed at AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:430-447,483-497`. `forget_workspace` keeps its wait (decision 2 property 3; rejected alternative 3). Added a deterministic test that pauses `_spawn` after admission, plus a mutation that removes the wait |
| B4 timeout contract not applied at the existing unconfirmed branches | **accepted** | Confirmed: on a normal return `cancel_confirmed` is always `True` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker_operations.py:756`), so the draft's final-status conversion was dead code. Decision 1 now enumerates three cases. PR-4 maps each `_terminate_group` branch (`:787-825`) by kind. PR-6 introduces `StopOutcome` in place of `String`. Each branch has its own test and mutation |
| B5 observations and citation provenance | **accepted in part** | Added the Evidence provenance section, with the reviewer's CI excerpts and their pre-merge head SHAs. "Rust ok" is explained as a pinned failure, not a pass. Fixed `implementations/docker/src/lib.rs:490` (488 was the 914129d line) and `_probe` handlers to `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:608,610`. Every abbreviated path is now repo-root. **Not done:** this phase has no shell, so I could not read the CI logs myself; they are labelled reviewer-reported, and PR-2 step 1 re-reads them and records a b88b1c3 run. I did re-check every Python provider line at 914129d, and those lines agree with the reviewer's b88b1c3 reads |
| I1 tombstone pruning breaks closure | **accepted** | Pruning removed. Tombstones are never pruned in all three providers, matching Local's existing `_closed`. Cost recorded in Maintenance cost; rejected alternative 4 |
| I2 Rust file-error boundary unspecified | **accepted** | Chose the existing `WorkspaceError::UnsafePath` with a public meaning ("refused by the path policy"), already mapped to `rejected_policy` by the harness at AW `implementations/docker/tests/operations.rs:1305`. Rejected a new variant (rejected alternative 7). Added an inode-swap test via the post-canonicalization helper, and a mutation that removes the `fstat` |
| I3 pin the real-daemon LH-7 xfail | **accepted** | PR-2 step 2 narrows the xfail at AW `lib/python/agentic_isolation/tests/test_behaviour_hazards.py:925` to step 2 `file_exists` `{exists: false}`, and all pins carry stable outcome fields |
| I4 recalculate baselines after harness corrections | **accepted** | PR-2's exit no longer says "every failing cell still fails". It records a new per-cell baseline, lists which cells may change because measurement changed, and retires the `7 failed, 6 passed, 1 skipped` figure. Later PRs measure against the post-PR-2 baseline |
| I5 LH-6 steps 0-1, and ordering of the shared file module | **accepted** | Removed the LH-6 risk; decision C is marked settled, citing APSS `standards-experimental/v1/EXP-V1-0006-workspace/fixtures/behaviour/hazard-drain-with-gap-reports-loss.json:11,61`. Added explicit PR-3b for `contained_files.py` before PR-4 and PR-5. The symlink change keeps its own test and decision E |
| (new, this phase) closing admission at teardown start breaks `while_running` hooks | n/a, found in this phase | Docker `execute` goes through `operations.start` (AW `lib/python/agentic_isolation/agentic_isolation/providers/docker.py:662-664`), and hooks "may still exec" (AW `lib/python/agentic_isolation/agentic_isolation/providers/base.py:356-359`). `close_admission` now runs after `while_running` succeeds and before `_stop`. Added a hook-exec test and mutation |
| (new, this phase) a `timeout` raised from cancel would abort Local destroy | n/a, found in this phase | AW `lib/python/agentic_isolation/agentic_isolation/providers/local_operations.py:716-718` calls `cancel` inside `forget_workspace`. PR-5 catches it there, with a test and mutation. PR-6 requires Rust `finalize` to treat `Timeout` like `ProviderUnavailable` |

No finding was rejected. Each one held up when checked against the code. B5 is only partly met, because this phase could not run a shell to read the logs first-hand.

## Readiness

PR-0, PR-2, PR-3, PR-3b, PR-6 and PR-4/PR-5 minus their LH-1/LH-7 halves are ready to implement. PR-1, the removal of the Local LH-1 xfail, and Docker's LH-7 `exists: true` change are blocked until the APSS spec owner ratifies decisions A (unconfirmed cancel = `timeout`+ref, alive pin dropped) and B (FIFO `exists: true`).

