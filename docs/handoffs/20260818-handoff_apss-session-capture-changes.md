# Handoff: APS-V1-0004 changes - origin_environment, an exporter CLI substandard, and a Python consumption path

**Date:** 2026-08-18
**Repo:** https://github.com/AgentParadise/agent-paradise-standards-system   **Branch:** to be created off `main`
**Status:** ready-to-start

> Written from the syntropic137 side, where the gaps surfaced. The work is in the
> standards repo.

## Purpose & Vision

APS-V1-0004 is doing its job on one side and not the other. SeshMagic depends on
the crate for real; agentic-primitives reimplements the contract in Python and
references the standard only in prose. Three changes make the standard the thing
both sides actually hang off, rather than a document one of them cites.

## Current State

The standard at `standards/v1/APS-V1-0004-session-capture/` is ratified (1.0.0,
promoted from `EXP-V1-0003` on 2026-08-06), defines three conformance profiles
(Source, Exporter, Reconstitutor), and ships `schemas/session-envelope.schema.json`
plus `registry/reconstitution.toml`. It has **no substandards directory yet**.

Three gaps, each verified against running code:

1. **`origin_environment` is not in the envelope the way consumers need it.** The
   store treats it as first-class and rolls up on an `app__env` convention, and
   the exporter reads `SESSION_STORE_ORIGIN_ENV` - but nothing normative carries
   it, so agentic-primitives' contract has no slot for it and every Syntropic137
   session lands as `"laptop"`. Verified on a real uploaded record:
   `"origin": {"host": "c1ce88621479", "environment": "laptop"}`, where the host
   is an ephemeral Docker container ID.
2. **The exporter CLI is unspecified**, so the two sides disagree. The consumer's
   doctor invokes `--version`; the exporter parses only `--dry-run`, `--health`,
   `--loop`, `--cursor-limit`, ignores unknown flags, and **runs a full capture
   sweep instead**. A health check that performs a real upload at preflight.
   Nothing could have caught this, because no shared artifact describes the CLI.
3. **The standard ships as a Rust crate only.** No `pyproject.toml`, no `.py`
   files. Section 1.3 tells consumers to depend on the crate "so drift surfaces
   as a build or test failure" and names `agentic-primitives providers/workspaces`
   as a target adopter - but that adopter is Python and has nothing to depend on.
   The reimplementation is a consequence of the distribution gap, not negligence.

Next actions, in order:

1. Add `origin_environment` to the envelope spec and schema (main standard).
2. Amend the reference-implementation location text if the exporter moves org.
3. Create the exporter CLI substandard.
4. Decide the Python consumption path.

## Files Affected

- `standards/v1/APS-V1-0004-session-capture/docs/01_spec.md:975-995` - section
  1.3's "depend on the crate" requirement and the target-adopter list; also the
  paragraph placing the reference implementation in the SeshMagic repo.
- `standards/v1/APS-V1-0004-session-capture/schemas/session-envelope.schema.json`
  - envelope schema; `origin_environment` belongs here.
- `standards/v1/APS-V1-0004-session-capture/src/` - the crate's definitional
  types; must move in step with the schema.
- `standards/v1/APS-V1-0004-session-capture/substandards/` - does not exist yet.
- `standards/v1/APS-V1-0000-meta/substandards/SS01-substandard-structure/` - the
  structural template to follow.
- `standards/v1/APS-V1-0000-meta/substandards/CL01-cli-contract/` - the precedent
  for specifying a CLI as a substandard.

## Rationale & Key Decisions

**`origin_environment` goes in the MAIN standard, not the substandard.** It is
envelope metadata used for attribution, grouping, and search. The standard
already calls metadata first-class and names `origin` among the filterable
fields, so this is core envelope semantics. What belongs in the substandard is
only *how the CLI receives it* (the env var name), not what it means. Putting the
field itself in a substandard would let two conformant stores disagree about
attribution, which defeats the purpose.

The `app__env` double-underscore convention (e.g. `syntropic137__dev`) carries app
and tier in one field so a single value rolls up two levels, and existing sources
without `__` render as a flat group. If that convention is normative it must be
written down here, because two implementations already split on it independently.

**Specify the CLI contract, not the binary.** A standards repo that ships
compiled, signed, multi-arch artifacts inherits a release pipeline it should not
have. `CL01-cli-contract` under APS-V1-0000-meta is the existing template: define
flags, exit codes, env vars, sweep semantics, and the state-file contract; let
the implementation live elsewhere and *conform*. The `--version` incident is the
motivating example and should be cited in the substandard's rationale.

Worth specifying in that substandard, because each has already caused a defect:

- **A liveness probe that is side-effect free.** The current one uploads.
- **Credential delivery.** The write token is currently a container env var,
  readable by the agent under exec-based execution models. If the contract says
  how the exporter receives its credential (0600 file, or finalize-only
  injection), every integration gets it right instead of each inventing it.
- **Multi-arch and signing as conformance requirements.** Consumers pin images by
  digest and cosign-verify. A client that only builds for one arch cannot be
  embedded. Today the only build in existence is Mach-O arm64.

**Python consumption - three options:**

- **(a) Publish a Python package from the standard.** Cleanest conformance; the
  standards repo takes on a second release pipeline.
- **(b) Generate Python types from `session-envelope.schema.json` at consumer
  build time, failing CI on drift.** No new distribution; the schema is already
  the shared artifact and is already normative.
- **(c) Require consumers to be Rust.** Most faithful to 1.3 as written, but it
  makes the standard's own named adopter non-conformant by construction.

**Recommendation: (b).** It delivers what 1.3 actually asks for - drift as a build
failure - without committing this repo to publishing on PyPI. Revisit (a) when a
second Python consumer appears. Whichever is chosen, say so in the spec, because
right now 1.3 issues an instruction that one named adopter cannot follow.

**On the reference-implementation location.** `01_spec.md:980-982` currently
states the behavioural reference implementation "lives in the SeshMagic
repository, NOT here" and lists the reference exporter among SeshMagic's
responsibilities. If the exporter moves to Agent Paradise so agentic-primitives
can bake it, this text must be amended. Do not leave the spec describing a layout
that no longer exists - the spec is the thing both sides are supposed to trust.

## Do's and Don'ts (learned this session)

- **Do** treat "consumers depend on the crate" as testable. It is stated as a
  requirement in 1.3 and is currently violated by a named adopter with no test
  detecting it. A conformance check belongs with the requirement.
- **Don't** let a substandard define envelope fields. Substandards should
  constrain *how* a profile is implemented, not *what* the data means.
- **Do** write the `app__env` convention down before more code splits on it. Two
  implementations already parse it and neither reads a normative source.
- **Don't** assume prose adoption is adoption. agentic-primitives cites this
  standard twice in a README and shares no artifact with it.

## Important Context to Keep in Mind

- The syntropic137 checkout vendors this repo as a submodule and its **main
  checkout pin is stale** (`d541a92`, which predates APS-V1-0004 entirely - only
  `APS-V1-0000-meta` and `APS-V1-0001-code-topology` exist there). The newer pin
  is in the `20260818_omni-digest-reconcile` worktree. Check which pin you are
  reading before concluding a standard is missing.
- Changing the envelope schema is a versioned, breaking-capable change with at
  least two live consumers (the SeshMagic store and its exporter) plus one
  reimplementation (agentic-primitives). Sequence the schema change ahead of the
  consumers, not alongside.

## Suggested Skills

- `meta:authoring-skills` - if the substandard ships agent skills like its siblings
- `superpowers:test-driven-development` - the conformance test should fail before
  the dependency is wired

## References

- `standards/v1/APS-V1-0000-meta/substandards/CL01-cli-contract/` - the template for the CLI substandard
- `standards/v1/APS-V1-0000-meta/substandards/SS01-substandard-structure/` - required substandard layout
- `docs/handoffs/20260818-handoff_ap-session-store-standard-dependency.md` - the agentic-primitives consumer side
- `docs/handoffs/20260818-handoff_seshmagic-exporter-extraction.md` - the exporter extraction
