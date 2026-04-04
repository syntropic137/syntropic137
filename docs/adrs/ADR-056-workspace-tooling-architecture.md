# ADR-056: Workspace Tooling Architecture

## Status

Accepted

## Date

2026-04-04

## Related

- ADR-021: Isolated Workspace Architecture
- ADR-024: Workspace Setup Phase (secret injection lifecycle)
- ADR-027 (agentic-primitives): Provider-Based Workspace Images
- ADR-033 (agentic-primitives): Plugin-Native Workspace Images
- Issue #541: Workspace tooling gaps
- Issue #544: OTLP receiver in syn-collector
- Issue #545: Capture image version in events
- Issue #547: Consume GHCR images

## Context

Syntropic137 workspace images were built in-repo via `release-containers.yaml`, tightly coupling the platform to image internals. Key gaps:

1. **No version provenance.** When a workspace started, the platform had no way to know which Claude CLI version, RTK version, or tooling was inside the container.
2. **No standard observability contract.** Token/cost data came from parsing Claude CLI JSONL transcripts — fragile, lagging (only available at session end), and coupled to transcript format changes.
3. **Tool compression absent.** Claude agents consumed 2-3x more tokens than necessary on Bash output because RTK (token compression) wasn't integrated.
4. **Single-arch builds.** Images only built for amd64, blocking deployment to Mac Mini fleets (arm64).

Meanwhile, the `agentic-primitives` repo (AgentParadise/agentic-primitives) was maturing as the agent-agnostic building block layer. It already owned Dockerfiles, provider manifests, and the plugin architecture.

## Decision

### 1. agentic-primitives owns image builds; syn137 consumes from GHCR

Images are built and published by agentic-primitives' CI (`build-workspace-images.yml`) to `ghcr.io/agentparadise/agentic-workspace-<provider>`. Syntropic137 references them via `DEFAULT_WORKSPACE_IMAGE` from `syn_shared.settings.workspace_images` — a single-source-of-truth module with registry constants, provider enum, and image ref builder.

The `release-containers.yaml` in syn137 no longer builds the `agentic-workspace` image.

### 2. Two-channel observability contract

Workspace images provide two complementary observability channels:

| Channel | Transport | Data | Consumer |
|---------|-----------|------|----------|
| **Plugin hooks** | JSONL to stderr | Custom events: git ops, compaction, subagent lifecycle | syn-collector (existing JSONL parser) |
| **Native OTel** | OTLP JSON push | Standard metrics: `claude_code.token.usage`, `claude_code.cost.usage`, tool timing | syn-collector `/v1/metrics` endpoint |

OTel is enabled by default in workspace images (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER=otlp`). Orchestrators provide `OTEL_EXPORTER_OTLP_ENDPOINT` at runtime. If no endpoint is provided, export silently no-ops.

This replaces the transcript watcher for token/cost data. The transcript watcher remains for backward compatibility but is on the retirement path.

### 3. Version manifest contract

Every workspace image includes `/opt/agentic/version.json`:

```json
{
  "provider": "claude-cli",
  "provider_version": "1.1.0",
  "components": {
    "claude_cli": "2.1.76",
    "rtk": "0.34.3",
    "node": "22",
    "python": "3.12",
    "rust": "stable"
  },
  "build_commit": "e63b4458332a",
  "built_at": "2026-04-04T16:58:05Z",
  "manifest_digest": "d55e27a49de81850"
}
```

After container creation, the workspace lifecycle reads this file via `docker exec` and stores it in the `IsolationStartedEvent.image_manifest` field. This enables:

- Dashboard display of component versions per workspace
- Correlation of behavior changes with version upgrades
- Audit trail for what ran in each execution

The manifest is optional (None) for backwards compatibility with older images or non-Docker backends.

### 4. RTK integration (token compression)

RTK is baked into workspace images and initialized via `rtk init` in the entrypoint. It transparently intercepts Bash tool calls, compressing output from commands like `ls`, `find`, `git`. Live A/B eval results:

| Metric | Baseline | With RTK | Delta |
|--------|----------|----------|-------|
| Context tokens | 61,117 | 28,663 | -53% |
| Cost (USD) | $0.13 | $0.09 | -29% |
| Turns | 12 | 6 | -50% |

RTK is multi-arch: pre-built musl binary on amd64, cargo-built from source on arm64.

### 5. Multi-arch builds with supply chain security

Images are built for `linux/amd64` and `linux/arm64` via Docker Buildx + QEMU. Supply chain security:

- Actions SHA-pinned (ISS-259 standard)
- Cosign keyless signing (Sigstore OIDC)
- SLSA provenance + SBOM via BuildKit
- Per-provider GHA layer caching (`mode=max`)

## Consequences

### Positive

- **Version provenance** in every workspace event — debuggable, auditable
- **Real-time cost tracking** via OTel (5s granularity vs end-of-session)
- **53% context reduction** from RTK — meaningful cost savings at scale
- **arm64 support** — Mac Mini fleet deployment unblocked
- **Decoupled releases** — workspace image versions independent of syn137 releases

### Negative

- **Cross-repo dependency** — agentic-primitives image availability blocks syn137 deployments
- **OTLP JSON parsing** — lighter than protobuf but still a new code path to maintain
- **arm64 build time** — RTK cargo build adds ~2-3 min to arm64 CI

### Migration

1. Transcript watcher retirement: Plan to remove in a future release after confirming OTel covers all required metrics
2. Existing deployments: `SYN_WORKSPACE_DOCKER_IMAGE` env var allows overriding the default image for gradual rollout
