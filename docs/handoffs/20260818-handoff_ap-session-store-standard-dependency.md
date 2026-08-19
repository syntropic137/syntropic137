# Handoff: make agentic-primitives actually depend on APS-V1-0004

**Date:** 2026-08-18
**Repo:** https://github.com/AgentParadise/agentic-primitives   **Branch:** to be created off `main`
**Status:** ready-to-start (nothing cut yet)

> This handoff lives in the syntropic137 repo because the agentic-primitives
> submodule checkout is a submodule pointer, not a working branch. The work
> happens entirely in agentic-primitives.

## Purpose & Vision

`APS-V1-0004-session-capture` section 1.3 is explicit:

> Consumers depend on that crate rather than reimplementing the envelope, so
> drift from this standard surfaces as a build or test failure.

and it names `agentic-primitives providers/workspaces` as a target adopter.
agentic-primitives does not do this. It reimplements the contract by hand in
Python and references the standard only in prose. The goal is to make the
dependency real so a mismatch fails a build instead of a workspace.

## Current State

- **The dependency does not exist.** `grep -rn 'APS-V1-0004'` across
  `lib/python/agentic_session_store/` and
  `workspace/capabilities/session-store/` returns exactly two hits, both prose
  in `workspace/capabilities/session-store/README.md` (lines 3 and 14).
- **SeshMagic, by contrast, depends on it for real:** `Cargo.toml:48` has
  `apss-v1-0004-session-capture = "1.0.0"`.
- **The likely reason:** the standard ships as a **Rust crate only**. There is
  no `pyproject.toml`, no `setup.py`, and no `.py` file anywhere under
  `standards/v1/APS-V1-0004-session-capture/`. SeshMagic is Rust and could just
  add the crate. `agentic_session_store` is Python and had nothing to depend on.
- Timeline rules out "the standard came later": ratified 2026-08-06, the
  capability landed 2026-08-16 in #303.

Next actions, in order:

1. Decide the Python distribution question (see Rationale). This blocks
   everything else and is not agentic-primitives' call alone.
2. Replace the hand-rolled contract in
   `lib/python/agentic_session_store/agentic_session_store/contract.py` with the
   standard's definitions.
3. Fix the four defects below that the missing dependency allowed.
4. Add a conformance test so drift fails CI.

## Files Affected

- `lib/python/agentic_session_store/agentic_session_store/contract.py` - the
  hand-rolled `Env` (six members) and `ExporterEnv`. This is the reimplementation
  section 1.3 forbids. Should become a consumer of the standard.
- `lib/python/agentic_session_store/agentic_session_store/doctor.py` - five
  checks; `_exporter_present` at :199-229 is defective (see below).
- `workspace/capabilities/session-store/seshmagic/init.sh` - translates
  `AGENTIC_SESSION_STORE_*` into the exporter's own env names. That translation
  table is the CLI contract, written nowhere normative.
- `workspace/capabilities/session-store/README.md:3,14` - the prose claim.
- `workspace/entrypoint.sh:429-437` - doctor invocation and audit redirect.
- `lib/python/agentic_isolation/agentic_isolation/config.py:74,147,150,153` -
  `read_only_root` and the tmpfs list.
- `docs/adrs/040-workspace-capability-modules.md` - the capability contract ADR.

## Rationale & Key Decisions

**The missing dependency is not cosmetic. It produced real defects.** Each of
these is a thing a shared artifact would have caught:

1. **`_exporter_present` invokes a flag that does not exist.**
   `doctor.py:199-229` runs `[path, "--version"]` and requires exit 0. The real
   exporter parses only `--dry-run`, `--health`, `--loop`, `--cursor-limit`. It
   **ignores `--version` and performs a full capture sweep instead**. So the
   preflight check passes by accident, does network I/O and state writes before
   the agent starts, and turns any transient store hiccup into a dead workspace.
   The capability README asserts the doctor "runs `--version`" as though that
   were a contract. The exporter source disagrees. Nothing could have detected
   this, because the two sides share no artifact.
   *Fix:* use `--dry-run` (real, network-free, state-free) or drop to
   `shutil.which` + `os.access(X_OK)`.

2. **No environment identifier exists in the contract.** `Env` has exactly six
   members, none for environment. The store has `origin_environment` as a
   first-class field and the exporter reads `SESSION_STORE_ORIGIN_ENV`, but the
   capability never sets it, so every session lands as `"laptop"`. Meanwhile
   `init.sh` deliberately refuses to set `SESSION_STORE_ORIGIN_HOST`, so
   `origin.host` is the ephemeral Docker container ID. Verified on a real
   uploaded record: `"origin": {"host": "c1ce88621479", "environment": "laptop"}`.

3. **`--read-only` rootfs breaks the capability entirely.** Consumers run
   workspaces with `read_only_root=True` (`config.py:74`, emitted at `:147`).
   Only `/tmp` and `/home/agent` get tmpfs (`:150,153`). `/spool` is a plain
   image directory, so partition creation fails:
   `mkdir: cannot create directory '/spool/exec-probe': Read-only file system`.
   Independently, `entrypoint.sh:429-433` does `mkdir -p ... 2>/dev/null || true`
   and then **redirects** the doctor's output into that directory; under
   `--read-only` the redirect fails, the `if` takes the else branch, and the
   entrypoint reports `doctor: FAIL` for a doctor that never ran.
   This affects **any** capability, not just session-store.

4. **The withhold mechanism is a no-op under exec-based harnesses.**
   `init.sh:85` declares `AGENTIC_SESSION_STORE_AUTH SESSIONS_WRITE_TOKEN` for
   withholding and `entrypoint.sh:487-516` unsets them from PID 1. But a
   consumer that starts the container with `sleep infinity` and runs agents via
   `docker exec` builds each exec's environment from the container's *configured*
   env, not from PID 1. Verified: the token is readable inside an exec. ADR-040's
   withhold contract needs an explicit statement about exec-based execution, and
   the credential should not be a `docker run -e` at all.

**The Python distribution question is the real decision.** Three options:

- **(a) Publish a Python package from the standard.** Cleanest conformance, but
  the standards repo takes on a second release pipeline.
- **(b) Generate the Python types from the standard's JSON Schema**
  (`schemas/session-envelope.schema.json`) at build time, and fail CI on drift.
  No new distribution; the schema is already the shared artifact.
- **(c) Rewrite the capability's contract layer in Rust.** Most faithful to
  section 1.3, largest change.

**Recommendation: (b).** It makes drift a build failure, which is what 1.3
actually asks for, without committing the standards repo to publishing on PyPI.
Revisit (a) if a second Python consumer appears.

## Do's and Don'ts (learned this session)

- **Do** treat the doctor as fail-closed. `entrypoint.sh:420` states it plainly:
  "Opting into a capability is opting into loud failure." That means every check
  must be correct, because any wrong check kills the workspace rather than
  degrading capture.
- **Don't** assume a check that passes is a check that works. `exporter_present`
  passes only when the store happens to be reachable, because the flag it uses
  silently runs a full sweep.
- **Don't** trust the capability README over the code. It documents `--version`
  as the liveness probe and documents `seshmagic/doctor.sh` as if it runs; the
  provider-specific doctor is never invoked (`CHECKS` in `doctor.py:371-378` has
  no `ProviderSpecificCheck`, unlike the memory capability).
- **Do** verify against a container started the way consumers actually start
  one. Every defect above was found by reproducing the real `docker run`
  argument set, not by reading code.

## Important Context to Keep in Mind

- **Consumers pin by digest and verify signatures.** Any image change means a
  new published digest and a signing-policy entry downstream. Do not assume a
  rebuilt `:latest` reaches anyone.
- **The image deliberately does not ship the exporter**
  (`providers/workspaces/*/Dockerfile`), and `WorkspaceConfig.mounts` /
  `MountConfig` / `with_mount()` exist but are **dead code** -
  `providers/docker.py` never reads `config.mounts`, so anything set there is
  silently dropped. See the SeshMagic exporter handoff for the delivery decision.
- The only exporter build in existence is Mach-O arm64. There is no Linux amd64
  binary anywhere.

## Suggested Skills

- `superpowers:test-driven-development` - the conformance test should fail before
  the dependency is wired, or it proves nothing
- `delegation:delegating-to-codex` - cross-model review before merge, and add
  `< /dev/null` to every `codex exec` invocation

## References

- `lib/agent-paradise-standards-system/standards/v1/APS-V1-0004-session-capture/docs/01_spec.md:975-995` - section 1.3 and the target-adopter list
- `docs/adrs/040-workspace-capability-modules.md` (agentic-primitives) - capability contract
- agentic-primitives PR #303 - where the capability landed
- `docs/handoffs/20260818-handoff_seshmagic-exporter-extraction.md` - the binary delivery half
- `docs/handoffs/20260818-handoff_apss-session-capture-changes.md` - the standard-side changes
