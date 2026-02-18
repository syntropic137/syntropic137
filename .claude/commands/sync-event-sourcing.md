# Sync Event Sourcing Platform

Sync updates from the local `event-sourcing-platform` library when changes are made.

## When to Use

Run this command when:
- Proto definitions are updated (`eventstore.proto`)
- Python SDK methods are added/modified (`grpc_client.py`)
- Rust event store backend is modified (`store_postgres.rs`, `store_memory.rs`)
- Any changes to `lib/event-sourcing-platform/`

## Quick Commands

### Python SDK Changes Only

```bash
uv sync --reinstall-package event-sourcing-python
```

### Rust Event Store Changes (Docker)

```bash
# Clear Docker build cache and rebuild
docker builder prune -f
docker compose -f docker/docker-compose.dev.yaml build event-store --no-cache
```

### Full Sync (Both Python SDK + Docker)

```bash
# 1. Sync Python SDK
uv sync --reinstall-package event-sourcing-python

# 2. Rebuild Docker image (no cache)
docker builder prune -f
docker compose -f docker/docker-compose.dev.yaml build event-store --no-cache

# 3. Restart services
docker compose -f docker/docker-compose.dev.yaml down -v
docker compose -f docker/docker-compose.dev.yaml up -d
```

Or use the justfile shortcut:
```bash
just sync-es  # Reinstalls Python SDK
just dev-fresh  # Full restart with Docker rebuild
```

## Verification

### Check Python SDK

```bash
# Verify new methods exist
uv run python -c "from event_sourcing.client.grpc_client import GrpcEventStoreClient; print(dir(GrpcEventStoreClient))"
```

### Check Docker Image

```bash
# Verify event store is healthy
docker ps | grep syn-event-store

# Check event store logs
docker logs syn-event-store --tail=20
```

## Why This Is Needed

### Python SDK

The `event-sourcing-python` package is a **local path dependency**:

```toml
# pyproject.toml
event-sourcing-python = { path = "lib/event-sourcing-platform/event-sourcing/python" }
```

When the source is modified, `uv` doesn't automatically detect changes and rebuild. The `--reinstall-package` flag forces a fresh build from source.

### Docker (Rust Event Store)

Docker uses layer caching aggressively. Even with `--build`, if the Cargo.lock/Cargo.toml haven't changed, Docker may use cached layers with old Rust code. You need:

1. `docker builder prune -f` - Clear build cache
2. `--no-cache` flag - Force full rebuild

## Related Files

- `lib/event-sourcing-platform/event-sourcing/python/` - Python SDK source
- `lib/event-sourcing-platform/event-store/eventstore-backend-postgres/` - Rust Postgres backend
- `lib/event-sourcing-platform/event-store/eventstore-proto/` - Proto definitions
- `docker/docker-compose.dev.yaml` - Docker compose configuration
- `packages/syn-adapters/src/syn_adapters/subscriptions/service.py` - Uses the SDK

## Common Errors Without Sync

### Python SDK Stale

```
AttributeError: 'GrpcEventStoreClient' object has no attribute 'read_all'
```

**Solution**: `uv sync --reinstall-package event-sourcing-python`

### Docker Image Stale

```
grpc.aio._call.AioRpcError: status = StatusCode.UNIMPLEMENTED
```

**Solution**: Rebuild Docker image with `--no-cache`

### Events Not Being Delivered

If events are written to event store but not picked up by live subscription:
1. Check if Docker image has the latest Rust code
2. Restart backend after Docker rebuild
3. Clear projection state if needed: `docker compose -f docker/docker-compose.dev.yaml down -v`
