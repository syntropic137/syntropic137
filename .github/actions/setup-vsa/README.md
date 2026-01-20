# Setup VSA CLI Action

Reusable GitHub Action to install the VSA (Vertical Slice Architecture) CLI tool from the `event-sourcing-platform` submodule.

## Purpose

VSA validation is a critical part of our QA pipeline, ensuring 100% architectural compliance. This action:
- Installs Rust toolchain (required for VSA CLI)
- Caches Rust dependencies for fast subsequent runs
- Builds and installs VSA CLI from the submodule
- Verifies installation

## Usage

```yaml
- name: Setup VSA CLI
  uses: ./.github/actions/setup-vsa
```

### With Custom Cache Key

For parallel jobs that might conflict:

```yaml
- name: Setup VSA CLI
  uses: ./.github/actions/setup-vsa
  with:
    cache-key-suffix: '-job-name'
```

## Requirements

- Repository must be checked out with submodules:
  ```yaml
  - uses: actions/checkout@v4
    with:
      submodules: true
  ```

## Caching Strategy

The action caches:
- `~/.cargo/bin/` - Installed Rust binaries (including VSA)
- `~/.cargo/registry/` - Rust crate registry
- `lib/event-sourcing-platform/vsa/target/` - Build artifacts

Cache key is based on:
- OS (`${{ runner.os }}`)
- VSA Cargo.lock hash
- Optional suffix (for parallel jobs)

## Maintenance

### Updating VSA Version

When the VSA submodule is updated:
1. The cache key automatically changes (based on Cargo.lock hash)
2. CI will rebuild VSA with the new version
3. No manual cache invalidation needed

### Troubleshooting

If VSA installation fails:
1. Check submodule is properly initialized
2. Verify Rust toolchain compatibility
3. Check build logs for compilation errors

## Performance

- **First run:** ~2-3 minutes (Rust compilation)
- **Cached runs:** ~5-10 seconds (cache restore + verification)

## Zero Maintenance Philosophy

This action is designed for long-term stability:
- ✅ Automatic cache invalidation on VSA updates
- ✅ Idempotent (safe to run multiple times)
- ✅ Self-healing (rebuilds if cache corrupted)
- ✅ Clear error messages for debugging
