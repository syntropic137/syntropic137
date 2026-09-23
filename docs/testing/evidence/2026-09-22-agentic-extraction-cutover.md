# Agentic extraction cutover evidence

Date: 2026-09-22

This record covers the pre-merge Syntropic137 compatibility proof for the
Agentic Primitives split. It is not a production-release attestation. The
public-repository CI and live-harness gates listed below must still pass.

## Immutable sources

- Agentic Skills tag `v0.1.0` resolves to commit
  `33091b9da32da80cff402e08dff7e674383aa83e`.
- The Agentic Workspace submodule candidate resolves to merged commit
  `231b35b00c791d174f6f7063376e71c04074b2d4`.
- That commit directly pins APSS `EXP-V1-0006` through merged APSS commit
  `18d55b231e7d06b509386b2599f925195b63ba0c` and delegates semantic launch
  manifest validation to the standard crate.
- Syntropic's editable `agentic-events`, `agentic-isolation`, and
  `agentic-logging` dependencies resolve from `lib/agentic-workspace`.

## Compatibility tests

The focused workspace settings, image-name, operator settings, and signature
verification suites passed: 100 tests.

The broader `packages/syn-shared/tests` and `packages/syn-adapters/tests`
suites passed. Their only non-pass results were two existing expected failures
for issue 444 and one existing platform-specific skip for issue 1170.

Full `just preflight` reached its intended release boundary. Formatting,
linting, generated artifacts, submodule initialization and upstream
reachability, APSS/VSA validation, architecture fitness, 729 architecture
tests, compose overlays, and execution of the currently pinned multi-harness
image all passed. The final image provenance gate correctly refused the old
Agentic Primitives digests because their source revision
`276eec0ac2315d32b83fb86fc4997cbaf1d87a52` does not equal the staged Agentic
Workspace gitlink `231b35b00c791d174f6f7063376e71c04074b2d4`. This
revision pins Vercel Skills CLI `1.7.0` across all three provider images and
guards that pin in CI and in each image build by asserting the installed
binary reports the exact configured version.

The cutover also repaired two pre-commit gates so they validate the stage-zero
index rather than stale `HEAD`, and made generated environment validation
idempotence-based. This lets preflight validate the exact tree about to be
committed without weakening CI, where the index and `HEAD` are identical.

## Cross-harness skill discovery

The `sdlc/review` skill from Agentic Skills was mounted into the locally built
`omni-agent-workspace` image and installed with both `--agent claude-code` and
`--agent codex`. The Vercel Skills CLI reported one universal installation at
`/workspace/.agents/skills/review`, with Claude Code linked to the same content.
`skills list --json` returned `review`, and `skills-lock.json` recorded the
local source plus computed content hash
`fd46e54c1de9d9b2b2d1532b19e726a9459049c12cd6d88d50675cf425aa2dbf`.

## Updated release-candidate images

Agentic Workspace commit
`231b35b00c791d174f6f7063376e71c04074b2d4` built successfully as both local
release-candidate images on arm64. Each build executed the pinned
`skills@1.7.0` install layer and all existing toolchain and package assertions.
Clean container smoke tests reported Skills `1.7.0` in both images, Claude
Code `2.1.250` and Codex CLI `0.150.1` in `omni-agent`, and Claude Code
`2.1.126` and Codex CLI `0.144.6` in `claude-cli`. Both images contain the
workspace entrypoint and SDLC plugin payload.

## Signed Workspace release

Agentic Workspace Actions run `35908207891` completed successfully from tag
`v0.1.1` and source commit
`231b35b00c791d174f6f7063376e71c04074b2d4`. Both images were published for
linux/amd64 and linux/arm64 with SBOM, provenance, keyless signatures, and
workflow-side signature verification:

- `agentic-workspace-claude-cli@sha256:69ab1e0d125bccbf46ba9d509140ca2a9b5e74c14dad1844ce0ac50a37d46b3a`
- `omni-agent-workspace@sha256:862668c9d9ae034e04082edc970769e95a79ac2613ceb0f3dbcaf9772f5591a5`

Local `cosign verify` accepted both digests only for the release identity
`https://github.com/AgentParadise/agentic-workspace/.github/workflows/release-images.yml@refs/tags/v0.1.1`
and GitHub Actions issuer. A negative check using the former Agentic Primitives
publisher identity failed as required. Syntropic's `PINNED_DIGESTS` and
generated `.env.example` now reference the new immutable indexes. The focused
workspace settings, image-name, signature verification, and skill-install
semantics suites pass: 91 tests.

## Remaining gates

1. Make Agentic Workspace public after its disclosure gate so public
   Syntropic137 CI can initialize the submodule without a private credential.
2. Reconcile the migration branch with current Syntropic `main` and rerun the
   full validation set.
3. Run the production-like Claude and Codex workflow plus rollback proof.

## Merge acceptance criteria

This pull request remains a draft until every item below is evidenced:

- [ ] Public Syntropic137 CI can initialize the public Agentic Workspace
  submodule from a clean checkout.
- [ ] Every required GitHub check passes on the final commit.
- [ ] `just qa-ci` passes locally, except checks documented as GitHub-only.
- [ ] The local Agentic Workspace image builds from the pinned submodule and
  the container E2E passes through its real entrypoint.
- [ ] Both Claude and Codex complete a production-like workflow, producing
  expected artifacts and event streams without credential leakage.
- [x] Signed linux/amd64 and linux/arm64 release images exist with SBOM and
  provenance. Syntropic pins their immutable digests and verifies the release
  certificate identity and pinned source revision.
- [ ] Rollback to the previous signed image digests is executed and recorded.
- [ ] The final branch commits are attributed to NeuralEmpowerment.

## Local integration attempt

The corrected container E2E starts the extracted workspace image through its
real entrypoint, connects it to Syntropic's sidecar, confirms Claude CLI,
workspace directories, settings, and JSONL streaming, and rejects Claude
result events whose `is_error` field is true. The local run reached that live
boundary but Claude returned `Not logged in`; therefore it is infrastructure
proof, not yet a passing live-agent acceptance test. The earlier test falsely
accepted that error result and has been tightened. Codex and rollback remain
unrun.
