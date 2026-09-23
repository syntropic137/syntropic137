# Agentic extraction cutover evidence

Date: 2026-09-22

This record covers the pre-merge Syntropic137 compatibility proof for the
Agentic Primitives split. It is not a production-release attestation. The image
digest and private-repository CI gates listed below must still pass.

## Immutable sources

- Agentic Skills tag `v0.1.0` resolves to commit
  `33091b9da32da80cff402e08dff7e674383aa83e`.
- The Agentic Workspace submodule candidate resolves to merged commit
  `1914f46a91533387b591de4068c8e6783726f3e1`.
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
Workspace gitlink `1914f46a91533387b591de4068c8e6783726f3e1`.

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

## Release attempt

Agentic Workspace Actions run `35815343298` built both workspace images for
linux/amd64 and linux/arm64 with SBOM and provenance enabled. GHCR rejected the
push because the existing package names grant Actions write access only to the
Agentic Primitives repository. Neither `v0.1.0` image tag exists, so there is no
partial release to consume or clean up.

## Remaining gates

1. Grant Agentic Workspace Actions write access to both existing GHCR packages.
2. Complete the signed release and record both multi-architecture index digests.
3. Update `PINNED_DIGESTS` and verify the new release-tag certificate identity.
4. Resolve public Syntropic137 CI access to the initially private Agentic
   Workspace source. AgentParadise currently disables repository deploy keys.
5. Run the production-like Claude and Codex workflow plus rollback proof.
