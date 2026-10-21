# OpenSandbox 1.1.1 source review

Reviewed 2026-10-12. Commit `531700ca18a7fa5fab6a2f25d6dc68a76eddab12`, stable release-1.1.1, published 2026-10-09. Apache-2.0. Source trace plus 16 selected Go SDK mock pool tests passed; no live infrastructure provisioned. Pinned source base: https://github.com/opensandbox-group/OpenSandbox/blob/531700ca18a7fa5fab6a2f25d6dc68a76eddab12/. [Design synthesis and Syn/APSS gap matrix](2026-10-12-harbor-opensandbox-runtime-design.md).

## Architectural patterns to reuse

1. **Separate control plane and execution plane.** `specs/sandbox-lifecycle.yml` owns sandbox lifecycle, identity, expiration, image/template provisioning, endpoint resolution, snapshots, network policy. `specs/execd-api.yaml` owns commands, files, sessions, metrics. Server runs Python/FastAPI; execd is Go in the sandbox. APSS should describe launch intent and normalized guarantees; a provider can implement transport via OpenSandbox without making workflow logic OpenSandbox-specific.
2. **Layer backend interfaces.** `server/opensandbox_server/services/sandbox_service.py:42-218` is the lifecycle ABC. Factory `services/factory.py:54-78` selects Docker or Kubernetes, wrapping Kubernetes plus fast-sandbox in `CompositeSandboxService`. Kubernetes has a second `WorkloadProvider` interface (`services/k8s/workload_provider.py:45-100`) and registered implementations. It passes resource requirements, network policy, volumes, image and expiry to the workload backend. This distinction maps well to Syn fleet/pool versus APSS provider, but OpenSandbox does not implement E2B as a native reference server runtime here.
3. **Resolve capabilities and endpoints at runtime.** SDK creates remote object, awaits endpoint publication, constructs execution clients, health checks with a common readiness budget (`sdks/sandbox/python/src/opensandbox/sandbox.py:741-830`). `connect:858+` attaches by sandbox ID; `resume:958+` resolves new endpoints. Endpoint is address AND required headers, not just host:port (`models/sandboxes.py:785-820`). Important for routing and credential boundaries. Some isolated-execution capabilities have a dedicated endpoint; do not infer a complete global provider negotiation protocol from that.
4. **Explicit local close versus remote deletion.** `sandbox.py:440-480`: kill remote only, close local transports only, destroy both with local cleanup in finally. APSS should make detach, cancellation, deletion and finalization distinct operations.
5. **Safe retry policy.** Python `transport/retry.py:34-38,104-158`: idempotent HTTP verbs default retries, POST/PATCH response retries opt-in, exponential backoff with jitter, per-attempt timeout and overall deadline. `_async_retry.py:160-179` explicitly says header deadline does not bound streaming body. This avoids silently replaying agent side effects. Workflow retry policy remains Syn-owned.
6. **Reconciliation rather than request-only lifecycle.** Docker restores expiry tracking from discovered containers and persisted override metadata (`docker/docker_service.py:281-513`). Kubernetes informer/watch adapters and snapshot CRs converge external intent. PostgreSQL+Kubernetes snapshot service periodically recovers unfinished operations (`snapshot_service.py:847-912`). Syn should persist intent and reconcile side effects on restart, not infer that a lost request means operation failed.

## Execution and reconnect semantics

`specs/execd-api.yaml:403-579` provides shell string OR native argv, foreground SSE OR background detached commands, cwd/env/uid/gid, timeout in milliseconds, interrupt, status and incremental background logs. Native argv is preferable for APSS structured command contracts. Status has start/finish, running, exit code and error.

**Critical protocol drift:** spec `execd-api.yaml:518-578` calls log cursor a line index. Implementation `components/execd/pkg/runtime/command_status.go:75-126` uses byte offset (`file.Seek`), returns combined stdout/stderr, and reads all remaining bytes. The caller must treat cursor opaque and pin server/SDK compatibility. This is direct evidence that matching method names/OpenAPI generation alone does not establish semantic conformance. Large uncapped reads still require a Syn capture limit/backpressure design.

Command metadata lives in `Controller.commandClientMap` (`runtime/ctrl.go:40-63`, `command_status.go:41-72`), output in sandbox temporary files (`command_common.go:33-35,101-114`). Completed metadata/background output retained at least 24h with hourly sweep; running output protected. This is not an external durable event log. Foreground log files removed at command completion (`command.go:225-233`) and no foreground SSE replay cursor exists. Durable capture must be Syn/AW-owned and exported before TTL deletion. An execd restart may lose command lookup despite surviving files.

Do not assume client disconnect cancels a foreground command: controller creates HTTP request context for SSE (`web/controller/command.go:53-103`), but `runtime/ctrl.go:79-86` builds execution context from `context.Background()`. `command.go:315-326` comments mention disconnect as cancellation, but the traced wiring does not transfer that context. Explicit interrupt or server command timeout must be tested; characterize post-disconnect outcome as uncertain until live conformance verifies it.

An initialized command receives a server-generated ID. Losing connection before receiving it creates a potential unknown execution outcome. No client-supplied idempotency key was found in this command request path. Syn needs an attempt identifier, durable external operation association and a policy for reconciliation before rerun.

## Security and resource semantics

Lifecycle authentication: global API key, or TenantProvider key-to-tenant lookup (`middleware/auth.py:68-151`). Missing global keys and no tenant provider skips auth; startup guard demands acknowledgement. Use gateway/private network and configured auth, never assume production defaults. Kubernetes tenant namespaces and labels provide routing/authorization scope, not a proof of runtime containment.

Data-plane credentials must be distinct from lifecycle authority. Python `models/sandboxes.py:799-820` and Go `sandbox.go:622-634,656-668` attach lifecycle API key only in proxy mode. Direct endpoints use their returned headers. Python `ConnectionConfig.follow_redirects=False` (`config/connection.py:76-83`); when enabled, strips OpenSandbox-prefixed auth headers across origins. Arbitrary custom headers still may leak by its own docstring. Stable Go `http.go:99-120,165-182` preserves caller CheckRedirect but has no protective default. [Issue 2170](https://github.com/opensandbox-group/OpenSandbox/issues/2170) reports cross-origin credential forwarding; [Go fix 2178](https://github.com/opensandbox-group/OpenSandbox/pull/2178) merged 2026-10-12, after the reviewed stable release. [Issue 2148](https://github.com/opensandbox-group/OpenSandbox/issues/2148) concerns JS/C# direct-mode key forwarding. These reports are integration checks, not exploit reproductions in this review. Do not advertise SDK security parity solely by version family. Execd can enforce its own `X-EXECD-ACCESS-TOKEN` hash/legacy token (`web/router.go:191-230`); no-token fallback permits requests, so claim 'all direct execd unauthenticated' is also too broad.

Server `config.py:1147-1198` supports optional gVisor/Kata/Firecracker runtime selection. Empty default means no secure runtime. Firecracker maps Kubernetes RuntimeClass. Ordinary container isolation must not satisfy an APSS microVM requirement merely because both provision sandboxes.

Docker defaults (`config.py:1200-1307`): host networking, port publication0.0.0.0 for bridge, dangerous capabilities dropped, no_new_privileges=true, pids_limit4096. Example overrides bridge. Storage allowlist empty means ALL host paths allowed (`examples/example.config.toml:45-49`). These are deployment choices needing APSS security profiles and explicit reject-if-unsupported semantics. Docker's bwrap compatibility branch may set AppArmor/seccomp unconfined (`docker_service.py:922-926`); evaluate layered confinement rather than assuming config baseline describes every runtime path.

Docker CPU/memory/gpu limits parsed and enforced through NanoCpus/mem_limit/device requests (`docker/container_ops.py:329-395`). K8s supports requests separately from limits (`k8s/create_helpers.py:89-95`, `workload_provider.py:87-90`); fallback requests=limits documented. Portable contract should separate reservation, hard ceiling, ephemeral disk, output bytes, process count and wall time. GPU/device availability is backend capability. Execd timeout, sandbox TTL and workflow deadline are different clocks.

## Recovery and scale limits

Docker expiry timers are process-local, restored at startup. Renew override metadata is local JSON under ~/.opensandbox/metadata with atomic rename (`docker/metadata.py:16-20,43-46,108-118,150+`). Replicas on different hosts do not share this state. Timer-per-sandbox is implemented (`docker_service.py:281-307`), an operational reason to load test rather than assume1000 trivial.

TTL omitted supports manual cleanup. Max create TTL defaults no cap and specifically does not cap renewals/total lifetime (`config.py:608-617`). Pause is Docker container pause, not memory-releasing hibernation or remote-provider snapshot equivalence. Docker snapshot uses docker commit (`docker/snapshot_runtime.py:153-165`), so this is image/rootfs snapshot, not a cross-provider memory checkpoint guarantee.

PostgreSQL store is not blanket server HA. Docker example says one active server per database (`examples/example.config.toml:57-64`), but narrow PostgreSQL+Kubernetes snapshot HA exists: `test_snapshot_ha_postgresql_kubernetes.py:270` two services share one CR and one terminal CAS; `:345` active peer recovers creator crash; `:434` fast-sandbox peer recovery. This proves the intended snapshot reconcile path under tested DB setup, not active-agent ownership, Docker expiry HA or full-service failover. Test requires OPENSANDBOX_TEST_POSTGRESQL_DSN and otherwise skips.

Scale knobs: `config.py:525-595` Uvicorn limit_concurrency1024 returns503 beyond concurrent connections, thread_pool_size200, backlog2048, shutdown grace5s. This is connections, not1000 executable sandboxes. Data-plane proxy streams consume connections; direct mode changes bottleneck location. K8s read/write QPS buckets separately configurable but default0 unlimited (`:661-690`); watch informer resync300s/watch60s (`:650+`). Host bridge each sandbox consumes2–3 ports; default40000–60000 range (`:1246-1284`). CPU, memory, image pulls, container runtime/pod churn, log volume, tenant quotas and capacity ownership still need measurements.

SDK pool is a useful warm inventory implementation, not the Syn job scheduler. Redis store atomic scripts/fenced writes and leader ownership (`async_redis_pool_store.py:86-180,435+`; `pool_async.py:816-849,985+`) protect replenishment/acquisition. Each acquired execution still needs durable job ownership/fencing and a fleet-wide active-resource budget outside idle inventory. `max_idle` does not cap borrowed resources; direct-create fallback may allocate beyond the buffer. Ownership transfers after renewal and namespace/local-generation checks; cancellation beforehand attempts shielded cleanup (`pool_async.py:977-1005`).

Changing a shared warm-pool template requires a new pool namespace. Draining idle entries does not fence peers from refilling the old definition. Go and Python/JS/Kotlin differ in replenish pacing/backoff. Pin the language-specific implementation (`docs/guides/client-pool.md:125-153,230-243`).

## Additional tests inspected

- `runtime/command_status_test.go:28-201`: unknown/running/completed states, byte cursor clamp/negative checks, poll after append.
- `runtime/command_cleanup_test.go`: private log dir/symlink defense, retention protects live output.
- `runtime/command_tail_bench_test.go:25,55,113`: idle1MiB, growing longline, shortline performance benchmarks; not fleet throughput proof.
- `sdks/sandbox/python/tests/test_redirect_integration.py`: loopback network cross-origin redirect tests.
- `server/tests/test_snapshot_ha_postgresql_kubernetes.py`: focused shared-DB/crash recovery tests.
- `server/tests/k8s/test_rate_limiter.py`, `server/tests/test_tenants.py`, snapshot repository contract tests.

## Recommended reuse and boundaries

Separately executed 16 Go SDK tests from `sdks/sandbox/go`:

```sh
go test . -run '^(TestPoolBuilder_|TestPool_Acquire_Empty_|TestPool_Concurrent_Acquire$|TestPool_ReleaseAllIdle_BoundsConcurrentKills$|TestReconciler_LockFailure$)' -count=1 -v
```

All passed: validation/defaults, leader-lock failure, empty-buffer policies, concurrent acquire and bounded cleanup. These are local mocks, not live-provider reliability evidence.

Reuse API separation, asynchronous operation identity/readiness budgets, endpoint headers, explicit detach/destroy, idempotency-aware retry, capabilities/resources distinction, reconciler shape and contract tests. Consider an APSS OpenSandbox adapter and optional execd transport instead of new custom remote command daemon.

Avoid adopting entire lifecycle schema as portable APSS domain: backend-specific extensions, host binds, rootfs snapshot versus hibernation, auth differences and missing global capability negotiation require mapping. Avoid SDK warm pool as replacement for Syn durable execution queue. Keep recipe tools/skills and semantic artifacts outside vendor extension fields. Add APSS conformance for request loss before ID, reconnect, cancel aftermath, stdout/stderr fidelity, cursor semantics, finalization-before-delete, unsupported security/resources rejection and crash recovery before throughput claims.

## Operational reference

Commands are examples, not executed deployment actions. Entry point/options: `server/opensandbox_server/cli.py:72-144,296-352`.

| Task | Command | Notes |
|---|---|---|
| Inspect server | `opensandbox-server --help` | No allocation |
| Inspect configuration | `opensandbox-server init-config --help` | Skeleton or example |
| Generate Docker example | `opensandbox-server init-config /tmp/osb-docker.toml --example docker` | Review security before use |
| Generate Kubernetes example | `opensandbox-server init-config /tmp/osb-k8s.toml --example k8s` | Backend configuration required |
| Start service | `opensandbox-server --config /path/to/config.toml` | Not executed here |
| Inspect migration | `opensandbox-server migrate-snapshots --help` | Narrow snapshot-store migration |

| Configuration | Stable default or semantics |
|---|---|
| server.limit_concurrency | 1024 connections; 0 disables |
| server.thread_pool_size | 200 sync-route workers |
| server.timeout_graceful_shutdown | 5 seconds |
| store.type | sqlite; PostgreSQL optional |
| storage.allowed_host_paths | Empty means unrestricted host paths |
| SDK pool.max_idle | Warm buffer target, not execution limit |
| SDK pool.primary_lock_ttl | 60 seconds; tune to preparation duration |
| SDK pool.idle_timeout | 24 hours; runtime determines billing |

| Variable | Purpose |
|---|---|
| SANDBOX_CONFIG_PATH | Server config path; --config overrides |
| OPENSANDBOX_STORE_POSTGRESQL_DSN | Metadata database connection |
| OPENSANDBOX_INSECURE_SERVER | Explicit no-auth acknowledgement; avoid in production |
| OPENSANDBOX_TEST_POSTGRESQL_DSN | Test-only shared-DB snapshot checks |
