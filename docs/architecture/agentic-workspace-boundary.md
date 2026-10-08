# Where Does This Change Belong? agentic-workspace vs Syntropic137

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.

## Submodules (`lib/`)

Both are our own projects - we dogfood them. If something needs fixing, push the fix directly to the submodule repo. Don't work around it.

- **agentic-workspace**: Workspace images (claude, omni-agent, toolchain), isolation providers, agent event recording/playback, harness adapters. Publishes and signs every workspace image from its protected `release` branch; Syntropic137 pins those digests. Replaced agentic-primitives on 2026-09-25 - that submodule is gone and nothing here depends on it.
- **event-sourcing-platform**: Rust event store, Python SDK, VSA validation CLI, projection framework

## Where does this change belong?

The boundary is harness knowledge vs domain meaning, and there is a test for it:

> **If it changes when Anthropic or OpenAI ships a new CLI version, it belongs
> in agentic-workspace. If it changes when we decide what a cost, a session or
> an execution IS, it belongs here.**

| agentic-workspace | Syntropic137 |
|---|---|
| Stream and transcript formats, where a harness puts its session id | Domain events, aggregates, what a session means |
| Anything baked into the workspace image, including binaries agents call | Pricing, execution totals, attribution |
| Workspace isolation, capture capabilities, delegation skills | Projections, the API, the read path |

Harness specifics live beside the existing `harnesses/{claude,codex}` adapters
in `agentic_isolation`, which already normalize to `HarnessTranscript` and
`TranscriptExtractionResult`. Extend those rather than adding a parallel path,
and never reimplement a harness detail here: it will drift the moment that CLI
changes, and the drift is silent.

**Depend on a port, not on a format.** When this repo needs something
harness-specific, define a Protocol here and let agentic-workspace satisfy it.
That keeps the domain testable against a double and stops CLI details leaking
into the domain model.

**The split has a real delivery cost, so plan for it.** A change in
agentic-workspace reaches a running workspace only after: merge -> image
build -> the protected `release` channel -> a `PINNED_DIGESTS` bump here.
Pushing to `main` publishes `:edge` only, which is explicitly unreviewed and is
NOT what consumers pull. So put as little in the submodule as genuinely needs
to be there, and define the contract first so work on both sides can proceed in
parallel instead of serialising behind the image.

