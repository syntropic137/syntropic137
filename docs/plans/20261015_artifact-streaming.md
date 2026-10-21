# Plan (final): #1552 item 2. Stream artifact collection instead of holding whole artifacts in API memory

Planned against `main` = `366e650b1`, the commit the research and the review used. This document stands alone: it replaces `plan.md` and carries everything from `research.md` and `cross-model-review.md` that the design depends on. The implementing agent's notes (exec-4e671cce1d13) could not be reached from any phase, so the design is re-derived from the code. No source was changed in this phase.

**Summary.** Artifact bodies stay small text inline (as today) or move to a by-reference shape. That shape already exists for binary (#990): `content=""`, with the bytes at `storage_uri`. Large text now uses it too. **No event field changes**, so there is no new `schema_version` and no upcaster. Bytes move from the workspace bind mount to MinIO through one streaming storage primitive, inside the worker thread the adapter already uses. Inside an execution only references and one bounded primary string per phase are kept. Memory is stated as four separate peaks (collection, retention, injection, read), each measured by its own test. Nine ordered PRs, two of them release-gated.

---

## 1. Problem

When a phase ends, the API process reads every file the agent wrote under `artifacts/output/` fully into memory. A single collection may legally hold 200 MiB (`MAX_COLLECTION_BYTES`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:79`). That is about 2× the whole per-execution allowance the #1979 memory default was sized on (`EXECUTION_API_MEMORY_MIB = 96`, `packages/syn-shared/src/syn_shared/settings/execution.py:38`).

The body is then copied again and again:

- the bytes are joined (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:126-134`);
- they are decoded to `str` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:277-289`);
- they are re-encoded for upload (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:924`);
- they are wrapped whole in a `BytesIO` (`packages/syn-adapters/src/syn_adapters/object_storage/minio.py:111-120`);
- the #700 readability check downloads them back in full (`packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:91-110`, `packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:251-253`).

After collection, every completed phase's bodies stay resident in `PhaseOutputCache` until the run ends (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/processor_types.py:52-74`). At the next phase start, injection materialises every earlier phase's output as one `list[tuple[str, bytes]]` before writing any of it (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:539-546`).

Text bodies of any size also go into `ArtifactCreatedEvent.content` and the projection's `content` column. ADR-012 itself lists that as a reason not to store content there (`docs/adrs/ADR-012-artifact-storage.md:215-217`).

Separately, the read path loads bodies nobody asked for. `GET /artifacts/{id}` defaults to `include_content=True` (`apps/syn-api/src/syn_api/routes/artifacts.py:730`). Both UIs' "metadata only" calls omit the flag:

- the frozen dashboard at `apps/syn-dashboard-ui/src/api/artifacts.ts:76-82`;
- Skyline at `packages/syn-ui/data/src/resources/artifacts.ts:66-68`.

Both execution pages fan that call out over every artifact of the run (`apps/syn-dashboard-ui/src/hooks/useExecutionData.ts:105`, `apps/syn-ui/src/routes/executions/Detail.svelte:55`).

API memory therefore grows with **output size × completed phases × concurrent executions**. Under concurrency, that is how the API gets OOM-killed and orphans every running execution (#1552).

**Not established:** that artifacts dominate RSS. No memory profile exists (§10). The arithmetic contradiction above stands either way.

## 2. Evidence that changed the design

| Claim | Verdict | Evidence |
|---|---|---|
| The "domain port" in the problem statement (`ArtifactCollectionPort`) is the whole-bytes path | **No.** It is dead in production. The live path is `ArtifactWorkspace.collect_files` / `IsolationPort.copy_from`. | `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:172-190`; only implementer `packages/syn-adapters/src/syn_adapters/workspace_backends/memory/memory_artifact.py:23`; live path `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:85-90`, `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:75-82` |
| Collection needs an agentic-workspace change | **No.** It reads the host bind mount in syn-adapters. | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:256-280` |
| Injection is equally streamable here | **No.** It goes through agentic-workspace's `provider.write_file(content: str \| bytes)`, which writes the whole body with a synchronous write inside an `async def`. | `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:218-232`, `lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:777-793` |
| The `ArtifactCreatedEvent` docstring ("deserialization ... ignores the stored version") is current | **Stale.** ESP decodes by `(event_type, schema_version)` and raises `UnknownEventVersionError` for an unknown version. | `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/envelope.py:184-194`, `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/decorators/events.py:54-60`; stale text `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/events/ArtifactCreatedEvent.py:53-58` |
| "Adding an optional, defaulted field needs no upcaster" | **True new-reads-old, false old-reads-new.** `DomainEvent` is `extra="forbid"`, so the previous release rejects an unknown field. | `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/event.py:31` |
| `just check-event-compat` can cover `ArtifactCreated` by adding fixtures | **No.** Both the gate and the probe resolve names only from the orchestration events package. The orchestration epoch excuses forward-incompatibility for **every** fixture. | `scripts/check_event_compat.py:61`, `scripts/check_event_compat.py:262-267`, `scripts/check_event_compat.py:326-341`, `scripts/event_compat/probe.py:28-37` |
| `check-event-compat` runs in CI | **No.** It is a `just` target (`justfile:1017-1018`) that no workflow under `.github/` references. It is a manual release gate (`docs/adrs/ADR-072-execution-hosting-and-upgrade-without-drain.md:555-569`). | grep of `.github/` |
| Readers already handle `content=""` + `storage_uri` | **Only for binary.** The query service, the API fallback and the 404/202 checks branch on the type, not the shape. An old reader returns `""` for by-reference text. | `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:215-231`, `apps/syn-api/src/syn_api/routes/artifacts.py:334`, `apps/syn-api/src/syn_api/routes/artifacts.py:744`, `apps/syn-api/src/syn_api/routes/artifacts.py:790-800` |
| Every text event has non-empty `content` | **Yes.** It is enforced by the command (`min_length=1`) and the aggregate. Binary always has `""`. | `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/commands/CreateArtifactCommand.py:57-64`, `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/aggregate_artifact/ArtifactAggregate.py:236-239`, `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/aggregate_artifact/ArtifactAggregate.py:61-66` |
| The collector is the only writer of artifact text | **No.** The API's `create_artifact` writes inline text of any size with no upload. `upload_artifact` puts bytes with no event. | `apps/syn-api/src/syn_api/routes/artifacts.py:424-484`, `apps/syn-api/src/syn_api/routes/artifacts.py:487-516` |
| Skyline's artifact page can download without the JSON body | **No.** Download and Copy are built from `content` and disabled when it is null. The frozen dashboard does the same. | `apps/syn-ui/src/routes/artifacts/Detail.svelte:182-190`, `apps/syn-ui/src/routes/artifacts/Detail.svelte:217-218`, `apps/syn-dashboard-ui/src/pages/ArtifactDetail.tsx:42-43` |
| Salvage puts an untruncated body into an orchestration event | **Yes.** The live path truncates at 500 chars. | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/stranded_salvage.py:131`; live `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/ArtifactCollectionHandler.py:128` |
| The MinIO upload already runs off the event loop | **Yes,** in one executor thread per upload. A synchronous reader consumed there needs no async bridge. | `packages/syn-adapters/src/syn_adapters/object_storage/minio.py:283-289` |

## 3. Approaches compared

| | A. Hybrid by shape (**chosen**) | B. Reference-only (`I = 0`) | C. `ArtifactCreatedEvent` v2 + upcaster | D. Stream transport only, text stays inline | E. Workspace-side upload (presigned PUT / sidecar) |
|---|---|---|---|---|---|
| Event schema change | none | none | new `schema_version`, first upcaster in repo | none | none |
| Previous release reads new events | yes, once the reader PR has shipped (§5, release rule) | same, but affects every text artifact | **no**: `UnknownEventVersionError` halts the artifact projections during overlap and rollback | yes | yes |
| Memory ceiling possible | yes (§4.5) | yes, slightly lower | yes | **no**: the event needs the whole text as one `str` | yes |
| Storage outage | small text still degrades to event-only | every artifact fails | as A | as today | as A |
| Prompt substitution and projection `content` | unchanged for text ≤ `I` | needs MinIO for every read; `content` column empty for every new row | as A | unchanged | as A |
| Cross-repo cost | none for collection | none | ESP upcaster wiring | none | agentic-workspace release chain; write credential handed to an agent-controlled environment; API still has to fetch the bytes to hash and classify them |

- **B** stays reachable later by lowering one constant. Its extra memory win over A is `phases × I`, a few MiB.
- **C** buys nothing the existing v7 shape does not express. The release gate is also written on the premise "ADR-007: no upcasters" (`scripts/check_event_compat.py:31-32`).
- **F, a process-wide runtime byte semaphore,** was also rejected as *the* ceiling mechanism. It would be a second authority that the allocating code is not forced to agree with: a missed `acquire` exceeds it silently. The ceiling here is structural (no type on the path can hold more than a bounded body) and measured by tests (§8). A semaphore may still be added later to cap *concurrent transfers*. That is I/O fairness, not memory.

## 4. Design

### 4.1 Representation: where a body lives is decided by its shape

- `content` non-empty ⇒ the body is inline.
- `content == ""` and `storage_uri` set ⇒ the body is at `storage_uri`.
- Neither ⇒ missing.

This is unambiguous over all stored history (§2: text was never empty, binary was always `""`).

One function, `body_location(content, storage_uri) -> Inline(text) | Stored(uri) | Missing`, lives in `packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py`, and every reader calls it. **Location is separate from interpretation.** A `Stored` body is then decoded according to `ContentType.is_binary` (`packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py:87-90`): strict UTF-8 for text types, bytes for binary. Readers stop asking "is it binary?" to decide *where* to look. They still ask it to decide *how to decode*.

Small text that was uploaded keeps both inline `content` and `storage_uri`, exactly as today. Large text has `content=""` plus `storage_uri`. Binary is unchanged.

### 4.2 One authority for inline vs reference

`MAX_INLINE_ARTIFACT_BYTES` (written `I` below) is a **domain constant**, not a setting. It sits in `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/commands/CreateArtifactCommand.py` beside `MIN_ARTIFACT_CONTENT_LENGTH`, which is the existing precedent for one named invariant shared by the aggregate and the phase-completion path (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/commands/CreateArtifactCommand.py:16-27`). It is a constant rather than an ADR-004 setting because it bounds the size of a *domain event*. Events written under different per-deployment values would differ in shape, and nothing about it is environment configuration.

**The aggregate owns the invariant. Writers obey it.**

`CreateArtifactCommand` changes. A command is not persisted, so this has no compat cost.

- Replace `content: str | bytes` with `content: str | None` (inline text only).
- Replace `storage_uri: str | None` with `stored: StoredContent | None`. `StoredContent` is a frozen dataclass of `storage_uri`, `content_hash` and `size_bytes`, all measured by storage over the bytes it stored.

`_measured` (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/aggregate_artifact/ArtifactAggregate.py:46-66`) enforces:

| `content` | `stored` | Allowed when | Event |
|---|---|---|---|
| text ≤ `I` bytes | None | text type | inline only (today's degrade path) |
| text ≤ `I` bytes | set | text type, and `sha256(content) == stored.content_hash` | inline + `storage_uri` (today's normal text path) |
| None | set, `size_bytes ≥ 1` | any type | `content=""`, hash and size from `stored` |
| text > `I` | any | **refused** | n/a |
| None | None | **refused** | n/a |

Writers read the same constant to choose what to send. A writer that chooses wrong is refused, so there is no second authority that could disagree silently. Readers never consult `I` (§4.1), so changing it later needs no reader change and no migration.

### 4.3 The streaming primitive

**Domain port.** `packages/syn-domain/src/syn_domain/contexts/artifacts/ports/ArtifactContentStoragePort.py` gains these, alongside the existing methods (removed only in PR 8, §5):

- `ByteSource` protocol: `size_bytes: int` and `open() -> ByteReader`. `ByteReader` is a context manager with a **synchronous** `read(n) -> bytes`. Its contract, in the docstring: blocking, and called only from a worker thread. Each `open()` starts again from byte 0. That is what makes two passes possible, and it is a stated requirement of the protocol, not an accident of one implementation. `ByteSource.of_bytes(b)` serves small in-memory writers.
- `put(artifact_id, source: ByteSource, *, content_type, placement: StoragePlacement) -> StorageResult`. `StoragePlacement` is a frozen dataclass of `workflow_id`, `phase_id`, `execution_id`, `session_id`, `artifact_type` and `title`. **`artifact_type` is preserved:** the collector passes it today (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:929-933`). `StorageResult.content_hash` and `size_bytes` (`packages/syn-domain/src/syn_domain/contexts/artifacts/ports/ArtifactContentStoragePort.py:47-54`) are measured over the bytes actually consumed.
- `open_stream(artifact_id, *, storage_uri) -> AsyncIterator[bytes]`. The response is closed and its connection released in a `finally`, so this happens on early exit and client disconnect as well as on completion.
- `read_text(artifact_id, *, storage_uri, max_bytes) -> TextRead(text, truncated: bool)`. This is the only way to get a decoded body. It is bounded by construction, and a truncated read cuts at the last complete UTF-8 boundary.

**Why there is no async queue.** `put_object` already runs inside one executor thread (`packages/syn-adapters/src/syn_adapters/object_storage/minio.py:283-289`). The adapter passes minio a file-like wrapper over `source.open()` that reads, hashes and counts **in that same thread**. There is no producer/consumer handoff, so there is nothing to cancel and no queue to unblock.

- **Exceptions.** A `ByteReader` raises `SourceChangedError` (a domain exception, not an `ArtifactStorageError`). It propagates out of `put_object` and through the adapter unconverted, because it is not in `BACKEND_FAILURES`. On any exception the adapter aborts the multipart upload and deletes the key best-effort.
- **Cancellation** behaves as today's `asyncio.to_thread` collection does: the thread finishes or fails. It cannot be interrupted mid-read.
- **Downloads** run `await asyncio.to_thread(response.read, R)` once per chunk. That is acceptable on the read path, which serves a client at network speed.

**Object storage.** In `packages/syn-adapters/src/syn_adapters/object_storage/minio.py`:

- `put_object(..., length=size, part_size=P, num_parallel_uploads=1)`;
- the whole-buffer md5 (`:120`) is deleted in favour of the server ETag;
- `upload(bytes)` becomes `put(ByteSource.of_bytes(...))`, so conversations, bundles, skills and plugins keep their behaviour on one primitive.

**Readability (#700) keeps its contract and loses its copy.** `_read_served` (`packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:91-110`) hashes the GET in `R`-sized reads instead of `response.read()`. The digest comparison (`packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:173-175`) is unchanged.

**Settings (ADR-004).** In `packages/syn-shared/src/syn_shared/settings/storage.py`:

- `transfer_part_bytes` (`P`, default 5 MiB, the S3 minimum part);
- `transfer_read_bytes` (`R`, default 1 MiB, today's `_READ_CHUNK`, `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:75`);
- `artifact_json_content_max_bytes` (the JSON read cap, §4.6).

Regenerate `.env.example`.

### 4.4 Collection: two passes per file, one file at a time

**Workspace port.** `ArtifactWorkspace.collect_files` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:90`) and `IsolationPort.copy_from` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:75-82`) become `list_outputs(patterns) -> list[WorkspaceFile]`.

- A `WorkspaceFile` carries `relative_path`, `size_bytes` and the file's identity at listing time (`st_dev`, `st_ino`, `st_size`, `st_mtime_ns`). It is also a `ByteSource`.
- It also has `async inspect(keep_head: int) -> FileFacts`, run in one `asyncio.to_thread`. It reads the file once in `R` chunks and returns:
  - `sha256` and `size`;
  - `content_type`, from the streaming classifier;
  - `head`: the whole file **only when** it is text and `size ≤ keep_head`, else None.
- The listing holds **no bytes**.

**Adapter.** In `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py`, the walk (`:198-215`) yields `WorkspaceFile`s instead of reading them. Every `open()` and `inspect()` goes back through `_open_contained` (`:96-113`) and re-applies the regular-file and single-hard-link checks (`:118-125`). It then also verifies:

- the fd's `fstat` identity equals the listing's (dev, ino, size, mtime_ns). This catches rename-replacement, in-place rewrites that move mtime, and growth or shrinkage;
- the reader returns exactly `size` bytes. Early EOF ⇒ `SourceChangedError`. Bytes after `size` ⇒ `SourceChangedError`, which replaces today's "grew while read" check (`:128-133`).

`MAX_COLLECTION_BYTES` and `MAX_COLLECTION_MATCHES` stay. They are applied from `st_size` at listing, so the first becomes a "bytes stored per collection" bound, and its comment (`:76-78`, "held in memory") is rewritten to say so.

**Classifier.** `ContentClassifier` (`feed(chunk)`, `result(path)`) sits beside `ContentType` in `packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py`. It has:

- an incremental strict UTF-8 decoder;
- a NUL check;
- a **12-byte** signature prefix. WebP needs bytes 8-11 (`packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py:150`).

It keeps the text-first rule (`packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py:104-106`). `ContentType.of(data, path)` is redefined as `ContentClassifier().feed(data).result(path)`, so production has one classifier. T1 checks it against an **independently written expected-MIME table**, not against `of` (§8).

**Collector.** In `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py`, `_store` (`:650-686`) and `create_artifact` (`:864-969`) process one file at a time:

1. `facts = await file.inspect(keep_head=I)`.
2. `stored = await storage.put(id, file, content_type=facts.content_type, placement=...)`. The object is stored under its real type, because classification came first.
3. Require `stored.content_hash == facts.sha256` and `stored.size_bytes == facts.size`. On a mismatch, or on `SourceChangedError` from either pass: delete the key best-effort, write no event, log a warning naming the path, and continue with the next file, exactly like today's skipped files.
4. Build the command per §4.2:
   - `content=head` if text ≤ `I`, plus `stored`;
   - `content=None, stored=stored` otherwise.
5. Save, then drop `head` before the next file.

**Storage outage** (`ArtifactStorageError` from `put`; the degrade rationale is at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:899-918`):

- text ≤ `I` ⇒ `content=head, stored=None`, the event-only artifact, as today;
- text > `I` ⇒ refused (decision §11.2);
- binary ⇒ refused, as today.

**Other paths in the collector.** Recovery from `last_agent_message` (#1195, #1300) and stranded salvage (`collect_from_unfinished_phase`, `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:769-835`) already hold their text in memory. They use the same §4.2 shapes, with `ByteSource.of_bytes` when the text exceeds `I`. Empty-file recovery keys on `size == 0` and is unchanged. Primary ordering (#997, #1149) is unchanged: `_store` still flags index 0.

### 4.5 Memory: four peaks, stated separately

Defaults: `P` = 5 MiB, `R` = 1 MiB, `I` = 256 KiB (decision §11.1). `F` = files retained across the run. `m` = retained bytes per file entry, measured by T2b and asserted ≤ 1 KiB.

| Peak | When, and per what | Bound | At defaults | Proven by |
|---|---|---|---|---|
| **Collection** (transient) | one phase end; one file at a time, sequential per execution | pass 1: `R` + head ≤ `I` + decoder state; pass 2: minio part ≤ `P` + reader `R` + readability GET `R`; event append ≤ `I` text + its `str` (≤ 4`I`) + serialisation copies (≈ 2`I`) | ≈ `P + 2R + 8I` ≈ 9 MiB | T2 (large files), T2b (many small files), T3 (minio part buffering) |
| **Retention** (held for the run) | per execution, all completed phases | `phases × 4I` (one primary `str` per phase; ≤ 4 bytes per code point) + `F × m`. **No file body is retained:** uploaded files are cached as `StoredBody(uri, hash, size, content_type)`, event-only files as `EventOnlyBody(artifact_id)` | 10 phases: ≤ 10 MiB primaries (2.5 MiB for ASCII) + `F × m` | T7 (bodies), T7b (many small files) |
| **Injection** (transient) | one phase start; one file at a time | the largest single injected file (≤ `storage.max_file_size_bytes`: 50 MiB default, up to 500 MiB configurable, `packages/syn-shared/src/syn_shared/settings/storage.py:153-161`) + `R`. Whole-file because agentic-workspace's `write_file` takes a whole body (§2) | ≤ 50 MiB + 1 MiB | T13 |
| **Read** | per API request, not per execution | `/raw`: ≤ 2`R`. JSON: ≤ cap + its `str` + JSON encoding ≈ 6 × cap | `/raw` 2 MiB; JSON ≈ 6 MiB at a 1 MiB cap | T9, T14 |

**The per-execution ceiling claim is narrowed to collection + retention.** That sum, `P + 2R + 8I + phases × 4I + F × m`, is independent of artifact *size*. It depends on file *count* only through metadata.

**Injection is outside the claim, with its own named limit:** the largest file, bounded by `max_file_size_bytes`. That is a real gap at large configured file limits. Closing it to `R` needs a streaming `write` capability in agentic-workspace (§9, decision §11.5). This plan does improve it from today's sum of all phases' outputs to one file.

`F × m` is the one term that grows with output count. With `MAX_COLLECTION_MATCHES = 10_000` per phase (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:80`), ten phases at the limit and `m` = 1 KiB come to about 100 MiB of metadata. That is above budget. Lowering the per-phase output cap is decision §11.8.

**T12, the formula check, is only a budget-arithmetic guard.** It stops someone raising `I` or `P` without revisiting #1979's sizing. It enforces nothing at runtime. The runtime bound is held by structure (no type on the path carries more than `I` of body) and proven by the measured tests T2, T2b, T7, T7b and T13.

### 4.6 Read path, #1570 and the UIs

- **Default.** `GET /artifacts/{id}` defaults to `include_content=False`. That fixes the over-fetch in both execution pages without touching the frozen app. It also makes Skyline's fixture (`packages/syn-ui/data/src/fixtures/artifacts.ts:130`) agree with the API. The CLI sends the flag explicitly (`apps/syn-cli-node/src/commands/artifacts.ts:93`).
- **`/raw`** returns a `StreamingResponse` over `open_stream`.
- **JSON content cap** (`GET /{id}?include_content=true`, `/content`). For text whose `size_bytes` exceeds `artifact_json_content_max_bytes`:
  - `content` is **null**. It is never a prefix, so no client can mistake a prefix for the whole body;
  - two new response fields: `content_preview` (the first cap bytes, via `read_text`) and `content_truncated: true`;
  - for smaller text the response is unchanged and the two fields are null and false.
  
  `/content`'s 202 retry branch (`apps/syn-api/src/syn_api/routes/artifacts.py:790-800`) must not fire for a truncated body: `content_truncated` is checked first. `just codegen` regenerates the spec, the CLI types and the API docs.
- **Skyline** (`apps/syn-ui`, `packages/syn-ui/data`):
  - add `requestBlob(path)` beside `requestForm` in `packages/syn-ui/data/src/client/http.ts`, using the same authenticated `clientConfig().fetch` (`packages/syn-ui/data/src/client/http.ts:70`), with a fixture route;
  - add `getArtifactRaw(id)` in `packages/syn-ui/data/src/resources/artifacts.ts`;
  - in `apps/syn-ui/src/routes/artifacts/Detail.svelte`, **Download always fetches `/raw`** (`:182-190` today builds it from `content`), so it saves the original bytes, text or binary, truncated or not;
  - when `content_truncated`, render `content_preview` under a visible label ("Preview: first N of M") and point Copy at the preview with the same label.
  
  Small tweaks to a shipped screen go straight to code (CLAUDE.md, Design).
- **CLI.** `syn artifacts show` and `syn artifacts content` (`apps/syn-cli-node/src/commands/artifacts.ts:107-110`, `:122-`) fall back to `/raw` when `content_truncated` is true, and stream it to stdout.
- **Frozen dashboard (`apps/syn-dashboard-ui`), not edited.** Policy: for text above the cap it sees `content: null`. Its viewer shows no content and Download and Copy are disabled (`apps/syn-dashboard-ui/src/pages/ArtifactDetail.tsx:35-43`). That is a visible absence, not a silent prefix export. Below the cap it behaves exactly as today. This is acceptable because the frozen app is being replaced by Skyline, and it is stated in the PR 7 description.
- **#1570.** Read routes resolve bodies through `body_location` and the artifact's `storage_uri`, so serving a body never depends on the projection's `content` column. The projection-lag 404 itself comes from `resolve_or_raise` (`apps/syn-api/src/syn_api/routes/artifacts.py:736`, `:776`, `:825`) and is #1570's fix. Whichever lands second rebases onto the other's resolver. If #1570 falls back to loading the aggregate, `ArtifactAggregate.storage_uri` is what PR 7 needs.

### 4.7 The compatibility gate

`scripts/check_event_compat.py` and `scripts/event_compat/probe.py`, both in PR 1:

- **Fixture identity names its context.** `Fixture` gains `context: str = "orchestration"`. Both processes resolve `syn_domain.contexts.<context>.domain.events`, falling back to the class-named submodule as the probe already does (`scripts/event_compat/probe.py:33-37`). The probe file is this tree's, run under the release's interpreter (`scripts/check_event_compat.py:290`), so one PR changes both sides.
- **The epoch excuse is scoped.** `guarded` (`scripts/check_event_compat.py:326`) applies only to fixtures with `context == "orchestration"`. ADR-072 D9's epoch keeps old *Executors* off a run. It says nothing about artifact readers, so an artifact fixture is never excused.
- **Fixtures.** `ArtifactCreated` inline text and binary-by-reference go in at PR 1. Text-by-reference goes in at PR 2. Nothing in the payload shape is new, so all three pass against the previous release.
- **What the gate does not do.** It proves the previous release can *decode* a payload. It cannot catch the old reader returning `""` for by-reference text, which is a behaviour difference, not a schema one. That is why the release rule (§5) and T4 remain necessary even with every fixture green.
- **It is a manual release gate.** No `.github/` workflow runs it. "Never add a field to `ArtifactCreatedEvent`" is therefore *checked at release time when the gate is run*, not enforced on every PR. Wiring it into CI needs a workflow change, which an agent workspace cannot push (§9).

## 5. Ordered PRs

**Release rule.** PR 2 (readers understand by-reference text) must ship in a release **before** the release containing PR 5b or PR 5c (the first writers of by-reference text). A rollback target must contain PR 2. Rolling back past it is the R1 failure.

Every PR is type-correct and deployable on its own. Removed operations are removed only in PR 8, after their last caller migrates (temporary facades, not two permanent implementations).

| PR | Contents | Depends on | Release |
|---|---|---|---|
| **1. Compat gate learns contexts** | §4.7: `context` on fixtures, both processes, scoped epoch excuse, two `ArtifactCreated` fixtures, T5. Scripts and tests only. | none | any |
| **2. Readers understand by-reference text** (expand) | `body_location` (§4.1). `_content_of` (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:215-231`) and `get_for_phase_injection` (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:247-285`) resolve location by shape and decode by type; a stored primary is read with `read_text(max_bytes=I)` once PR 4 exists, until then with `download` and a size check. `_load_artifact_content` (`apps/syn-api/src/syn_api/routes/artifacts.py:310-336`) and the checks at `apps/syn-api/src/syn_api/routes/artifacts.py:744` and `:790-800` use it. The stale docstring (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/events/ArtifactCreatedEvent.py:53-58`) is rewritten: the decode rule, the `extra="forbid"` consequence and the location rule. Text-by-reference fixture added. T4. | 1 | **N** |
| **3. Stop read-path amplification** | `include_content` default → False (`apps/syn-api/src/syn_api/routes/artifacts.py:730`), then `just codegen`. One `preview_of(text)` beside `ArtifactsCollectedForPhaseEvent`, used by `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/ArtifactCollectionHandler.py:128` and `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/stranded_salvage.py:131`. The field type is unchanged, so the orchestration snapshot does not move and `ORCHESTRATION_EVENT_EPOCH` stays 1. T8, T10. | none | any |
| **4. Streaming primitive, added beside the old one** | §4.3: `ByteSource`, `ByteReader`, `SourceChangedError`, `StoragePlacement`, `put`, `open_stream`, `read_text` on the artifact port and in the MinIO, object-storage and in-memory adapters (in-memory stays ADR-060-guarded). The existing `upload` and `download` are re-implemented as **facades** over `put(ByteSource.of_bytes(...))` and `open_stream`, so no caller changes and no caller breaks. Streaming readability hash. Settings `P`, `R`, JSON cap. Port conformance (`packages/syn-adapters/src/syn_adapters/port_conformance.py`) covers the new methods. T3. | none | any |
| **5a. Streaming classifier** | `ContentClassifier`; `ContentType.of` redefined on it. Pure refactor, no behaviour change. T1. | none | any |
| **5b. Command and aggregate shape; API writers** (contract, part 1) | §4.2: `MAX_INLINE_ARTIFACT_BYTES`, `StoredContent`, the new `CreateArtifactCommand` fields and the `_measured` table. **Every** `CreateArtifactCommand` caller migrates in this PR: the collector (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:952-967`, still uploading whole bytes via the PR 4 facade for now), the API `create_artifact` (`apps/syn-api/src/syn_api/routes/artifacts.py:467-474`), the docstring examples (`packages/syn-domain/src/syn_domain/contexts/artifacts/__init__.py:16`, `packages/syn-domain/src/syn_domain/contexts/artifacts/ports/ArtifactContentStoragePort.py:14-21`) and the tests. **API `create_artifact`:** text ≤ `I` is inline-only, as today; text > `I` is `put` first and created by reference, and a storage outage returns 503 (decision §11.4). **API `upload_artifact`** (`apps/syn-api/src/syn_api/routes/artifacts.py:509-513`) moves to `put`. T11 (aggregate half), T15. | 2 shipped, 4 | **≥ N+1** |
| **5c. Streaming collection** (contract, part 2) | §4.4: `list_outputs`, `WorkspaceFile` / `inspect` in `packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py`, `ManagedWorkspace` (`packages/syn-adapters/src/syn_adapters/workspace_backends/service/managed_workspace.py:256-271`), the memory test adapter (`packages/syn-adapters/src/syn_adapters/workspace_backends/memory/memory_adapter.py:251`), the collector two-pass loop, the outage split, the salvage paths. Deletes the dead `ArtifactCollectionPort` (`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/ports.py:172-190`), its double (`packages/syn-adapters/src/syn_adapters/workspace_backends/memory/memory_artifact.py`) and its conformance entries. Amends ADR-012 (`docs/adrs/ADR-012-artifact-storage.md:30-38`): Tier 1 holds text ≤ `I`; larger text is Tier 2 only. Adds `artifact_memory_ceiling_bytes` beside `EXECUTION_API_MEMORY_MIB`. T2, T2b, T6, T11 (collector half), T12. **Mutation evidence:** commit a `.mutations/` patch restoring `b"".join` in the reader and ask the orchestrator to run `just mutation-evidence`. | 5a, 5b | **≥ N+1** |
| **6. Phase outputs are references** | `PhaseOutputFile.content` (`packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py:174-194`) becomes `body: StoredBody \| EventOnlyBody \| InlineText`. `InlineText` exists only for the legacy `phase_outputs: dict[str, str]` fallback (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:408-412`), which is already a bounded primary. `CollectedArtifacts.files` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:640-647`) and `PhaseOutputCache` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/processor_types.py:52-74`) hold references plus one primary `str` ≤ `I` per phase. `primary_text` (`packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py:197-213`) stays the single #1149 selector; for a stored primary it uses `read_text(max_bytes=I)` (decision §11.3). The query service's `_files` (`packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:201-213`) and the resume path (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/resume_handoff.py:58-80`) return references. **Injection:** `_injectable` (`:416-455`) yields `(path, body ref)` lazily, and `_inject_and_log` (`:521-556`) resolves and injects **one file at a time**. A `StoredBody` comes from `read_text`/`open_stream`, gathered to one body because `write_file` needs it whole. An `EventOnlyBody` comes from `self._repository.get_by_id` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/processor_types.py:112`), strongly consistent and with no projection lag. The body is dropped before the next file. `ArtifactWorkspace.inject_files` takes one file per call; the adapter's loop (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter_copy.py:230-232`) is already per-file. A warning is logged when an injected file's size differs from its artifact's `size_bytes` (the R1 signal). T7, T7b, T13. | 5c | any after 5c |
| **7. Read path streams; JSON cap; CLI and Skyline** | §4.6 in one PR, because API, CLI and Skyline ship together in this monorepo: `/raw` → `StreamingResponse`; `get_artifact_bytes` (`apps/syn-api/src/syn_api/routes/artifacts.py:339-353`) returns location + metadata; JSON cap with `content_preview` / `content_truncated`; `just codegen`; CLI `/raw` fallback; Skyline `requestBlob`, `getArtifactRaw`, Download via `/raw`, preview labelling. The frozen-dashboard policy is stated in the PR body. T9, T14, T16. | 4 | any after 4 |
| **8. Remove the facades** | Delete the bytes `upload` / `download` from `ArtifactContentStoragePort` and its adapters once grep finds no caller. The object-storage `upload(bytes)` used by conversations, bundles, skills and plugins **stays**: it is a different port, already implemented on `put`. Retires `metadata: dict[str, Any]` on the artifact `upload` (`packages/syn-domain/src/syn_domain/contexts/artifacts/ports/ArtifactContentStoragePort.py:95`), which lowers `untyped-dicts`. | 5b, 5c, 6, 7 | any |
| **9 (optional). Stop projecting large historical bodies** | `packages/syn-domain/src/syn_domain/contexts/artifacts/slices/list_artifacts/projection.py:88-114`: project `content=""` when a historical inline text exceeds `I` **and** has a `storage_uri`. `VERSION = 7 → 8` (`:65`) triggers the rebuild. Events are not rewritten. Decision §11.6. | 2 | any |

PRs 1, 3, 4 and 5a are independent and low risk. They can run in parallel with the profile (§10).

## 6. Migration for existing events

**None is required for correctness.** Every stored `ArtifactCreated` is either inline text (non-empty `content`, with or without `storage_uri`) or binary by reference. `body_location` reads both exactly as they mean today.

- No upcaster is written, because no stored payload changes shape.
- Stored events keep their inline bodies. That is history and is not rewritten.
- Old events whose upload failed (`storage_uri=None`) stay inline-only and are served from the projection as today.
- Their cost to the read model is what optional PR 9 reclaims, through a projection rebuild rather than event rewriting. The backfill precedent is `scripts/backfill/backfill_artifact_created_at.py`.

**Rollback.** From the PR 5b/5c release back to release N (with PR 2) is safe. Back past N is not (R1).

## 7. Risks

| # | Risk | Signal |
|---|---|---|
| R1 | Rollback past PR 2: an old reader's `_content_of` returns `""` for by-reference text, so resume injects an empty file. | T4 fails if PR 2 is reverted. In production, the PR 6 warning: injected size 0 while `size_bytes > 0`. |
| R2 | A future field on `ArtifactCreatedEvent` breaks the previous release (`extra="forbid"`). | `just check-event-compat` fails on the artifact fixtures, **when run** (§4.7). |
| R3 | minio-py buffers more than one part (parallel parts, or reading ahead). | T3's allocation assertion fails. Treat that as a finding, not a tuning knob. |
| R4 | The streaming classifier misclassifies at a chunk boundary or drops a signature. | T1 against independent expectations. |
| R5 | A file changes between passes (salvage while the container may still be writing). | `SourceChangedError` / hash-mismatch warning by path (T6). A rising rate means salvage needs the container stopped first. |
| R6 | Phase-end latency: two reads per file, multipart round trips over 5 MiB, and per-file GETs at injection now that the cache holds references. | Collection and injection duration per phase, p95 before and after on the same workflow (§10). |
| R7 | A storage outage now refuses text > `I` that used to survive inline. | Phase failure naming the file. Rare by construction; small text still degrades. |
| R8 | Event-loop blocking: a synchronous read leaks onto the loop. **Already present today, outside this plan:** agentic-workspace's `write_file` writes synchronously inside `async def` (`lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:788-793`), so injecting one 50 MiB file blocks the loop. | Loop-lag warnings; the exec-27fed66a653d symptom (exit -1 on a neighbour's exec). Recorded for the §11.5 follow-up. |
| R9 | The `include_content` default flip breaks an unknown client relying on implicit `True`. | Reports of `content: null`. The CLI is verified unaffected. |
| R10 | The frozen dashboard loses body access for text above the JSON cap. | Accepted by policy (§4.6). Visible as "no content", never as a truncated download. |
| R11 | `F × m` metadata retention grows with file count, not size. | T7b measures `m`. Decision §11.8. |

## 8. Verification

Gates, from the repository root:

```
just preflight-agent
uv run pytest -m unit -q
just check-event-compat          # PR 1 onward, at release time
just codegen && pnpm --dir apps/syn-cli-node check:api-drift   # PRs 3, 7
just check-untyped-dicts         # PRs 4, 8 must not raise any package's count
```

**Measurement method.** T2, T2b, T7, T7b, T9, T13 and T14 use `tracemalloc`, which measures **Python heap allocations**. `bytes` and `str` bodies are Python objects, so that is the quantity this plan bounds. T3 asserts on `tracemalloc` and also *reports* (does not assert) a process RSS delta. It does that by running the upload in a fresh subprocess and comparing `ru_maxrss` with a baseline subprocess that runs no upload, because C-level buffers in urllib3 and ssl may not show in `tracemalloc`.

New Python test modules carry `@pytest.mark.unit` unless marked docker-backed. Each test states what it catches when its change is reverted.

| T | PR | Test | Catches |
|---|---|---|---|
| T1 | 5a | `packages/syn-domain/tests/contexts/artifacts/test_content_classifier.py`. A corpus with **hand-written expected MIME types**: ASCII; 4-byte emoji; NUL inside text; PNG, JPEG, GIF, PDF; **WebP with no extension** (needs bytes 8-11); a `.png`-named valid UTF-8 file (text-first ⇒ `text/markdown`); invalid UTF-8 in the final byte; a truncated multibyte sequence at EOF; empty. Fed at chunk sizes {1, 2, 3, 7, 11, 12, 13, 1 MiB}. Asserts the classifier equals the table, and separately that `ContentType.of` equals the table. | a non-incremental decoder; an 8-byte signature buffer (WebP becomes octet-stream); a lost text-first rule |
| T2 | 5c | `packages/syn-domain/tests/contexts/orchestration/test_streaming_collection_memory.py`. Three 24 MiB text files (each > `P` and > `R`) plus one 2 KiB file under a tmp `artifacts/output/`. Runs `collect_from_workspace` with the **real** `adapter_copy` reader and an ADR-060-guarded storage double that hashes and discards. Asserts peak < `P + 2R + 8I + 2 MiB`; each large file's event has `content == ""`, `storage_uri` set, `content_hash == sha256(file)` and `size_bytes == file size`; the 2 KiB file's event has its text inline **and** a `storage_uri`. | restoring `b"".join` (peak ≥ 72 MiB) |
| T2b | 5c | Same module. **2,000 files of `I` bytes each** (500 MiB raised for the test via `max_total_bytes`). Asserts the collection peak stays under the T2 bound (one head at a time, not 2,000), and records `m` from the returned `CollectedArtifacts`. | heads accumulated across files; inline bodies kept in `CollectedArtifacts.files` |
| T3 | 4 | docker-backed, CI only: `packages/syn-adapters/tests/object_storage/test_minio_streaming.py`. `put` a 20 MiB source against testcontainers MinIO. Asserts `tracemalloc` peak < `P + 2R + 2 MiB` and reports RSS. Asserts the object round-trips by sha256 and the readability check passes. A second case serves different bytes at the key and asserts `UploadError` (#700 unchanged). A third raises `SourceChangedError` from the reader mid-part and asserts no object remains. | `num_parallel_uploads` left at default; `response.read()` in `_read_served`; minio buffering the source; an orphaned partial upload |
| T4 | 2 | extends `apps/syn-api/tests/test_990_binary_artifacts_round_trip.py`. A text payload with `content=""` and a `storage_uri` goes through the ESP deserializer, aggregate, projection, `get_files_for_phase_injection` and `get_for_phase_injection`. Asserts the body equals the stored bytes decoded, and that the phase stays in the primary map. The existing v6 inline case must still pass. | reverting `_content_of` to `_is_binary` (returns `""`) |
| T5 | 1 | `scripts/tests/test_check_event_compat.py`: an artifact fixture resolves in both processes; an orchestration-epoch bump **does not** excuse a failing artifact read; an orchestration fixture is still excused as before. | the gate silently not loading artifact fixtures; a global epoch excuse |
| T6 | 5c | Real `adapter_copy` against a tmp dir, mutated between `inspect` and `put`: (a) grow, (b) shrink, (c) same-length in-place rewrite, (d) rename-replace with a same-size file. Each asserts no `ArtifactCreated` is saved, no object is left in the double, the warning names the path, and other files in the collection are still stored. | identity or EOF checks missing; publishing a partial original |
| T7 | 6 | After three simulated phases, each with a 10 MiB output, `PhaseOutputCache.files` contains only `StoredBody` / `EventOnlyBody` and every `primary` is ≤ `I` bytes. | PR 6 reverted (30 MiB of `str` retained) |
| T7b | 6 | Ten phases × 500 small files, **including event-only files from a simulated outage**. Asserts retained `tracemalloc` delta ≤ `10 × 4I + 5,000 × 1 KiB`, and no `InlineText` other than the legacy alias. | event-only texts retained inline; `m` creeping up |
| T8 | 3 | `GET /artifacts/{id}` with no query: the storage double's `download` / `open_stream` are called zero times and `content` is null. | reverting the default |
| T9 | 7 | `/raw` for a 20 MiB stored object, consumed with `httpx.AsyncClient(transport=ASGITransport).stream(...)`, **hashing and discarding each chunk inside the measured region and never touching `response.content`**. Asserts the sha256 matches and the peak is < 2`R` + 1 MiB. | reverting to `Response(content=...)` |
| T10 | 3 | Stranded salvage of a 10,000-character body: `first_content_preview` length == `PREVIEW_CHARS`. The orchestration schema snapshot test passes unchanged. | the untruncated preview |
| T11 | 5b/5c | Aggregate: every row of the §4.2 table. Collector: on storage outage, text ≤ `I` is event-only inline, text > `I` is handled per §11.2, and binary is refused. | two authorities disagreeing; the outage split lost |
| T12 | 5c | `artifact_memory_ceiling_bytes(defaults, phases=10, files=…) ≤ EXECUTION_API_MEMORY_MIB × 2^20 / 4`. **A budget-arithmetic guard only**: it fails when someone raises `I` or `P` without revisiting #1979. It is not evidence of a runtime bound. | silent erosion of #1979's sizing |
| T13 | 6 | Injection of inherited outputs (resume path) from 3 phases × 5 files, the largest 8 MiB, through a recording workspace double. Asserts `inject_files` is called once per file, and the peak is < largest file + 2`R` + 4`I` (not the 3-phase sum). | `_inject_and_log` building the whole list again |
| T14 | 7 | A stored text larger than the JSON cap: `GET ?include_content=true` returns `content: null`, `content_truncated: true` and a `content_preview` of ≤ cap bytes ending on a UTF-8 boundary; `/content` does not return 202 for it. | a prefix returned in `content`; the 202 branch firing |
| T15 | 5b | API `POST /artifacts` with text > `I`: the event is by reference and the body round-trips via `/raw`. With storage down it returns 503. With text ≤ `I` it behaves as today. | an unbounded inline event via the API |
| T16 | 7 | Skyline Playwright/unit, in `apps/syn-ui`: for a fixture artifact with `content_truncated`, the preview label is shown and Download fetches `/raw`; the downloaded blob's sha256 equals the fixture bytes' hash. | a prefix exported as the artifact |

**End-to-end** (orchestrator, after PR 6). Run one workflow whose phase writes a **40 MiB** text file and 500 small files under the #1717 load harness at N = 10. Using 40 MiB stays under the default 50 MiB per-file limit. To test 100 MiB, run with `SYN_STORAGE_MAX_FILE_SIZE_MB=128` declared in the run's settings, and expect the injection peak to rise with it (§4.5). Show that API `memory.current` stays within the #1979 envelope, and that the downstream phase receives every file intact (sha256 equal).

## 9. Out of scope

- **Streaming injection into the next workspace.** It needs a streaming write in agentic-workspace. Define the Protocol here first, then the submodule's image release and the `PINNED_DIGESTS` bump. The same follow-up should move `write_file`'s synchronous write off the event loop (R8). Decision §11.5.
- **Wiring `check-event-compat` into CI.** It is a `.github/workflows` change, which this workspace credential cannot push. Raise it as an issue for a human to land.
- Memory in stream parsing and conversation recording, the other #1552 suspects.
- The bytes behaviour of conversations, bundles, skills and plugins. They sit on the new primitive with unchanged behaviour.
- #1570's projection-lag 404. It is coordinated with (§4.6), not fixed here.
- Presigned-URL downloads for browsers: a deployment and security decision of its own.
- Any edit to `apps/syn-dashboard-ui` (frozen).
- Rewriting stored events.

## 10. Sequencing against the missing profile

Run the RSS profile during #1717 at N = 0/5/10/20 **in parallel with PRs 1, 3, 4 and 5a**. Those PRs stand on their own:

- compat-gate coverage of artifact events;
- the dashboard over-fetch removed;
- the salvage preview bounded;
- a streaming primitive, with a cheaper readability check for every uploader.

PRs 5b, 5c and 6 are the costly ones. If the profile shows artifacts are a negligible share of the per-execution slope, reprioritise them against the real driver. Do not cancel them, because the 200 MiB-vs-96 MiB contradiction in §1 stands either way.

## 11. Needs a human decision

1. **`MAX_INLINE_ARTIFACT_BYTES` (`I`).** Proposed 256 KiB. That keeps every realistic report inline (the #1570 example was 34,621 characters) and bounds a single event at 256 KiB, against a legal 200 MiB today. It amends ADR-012's Tier-1 decision, so the ADR-012 owner picks it. It is a constant, not a setting (§4.2).
2. **Storage outage for text > `I`** (collector):
   - (a) refuse that artifact and fail the phase, as binary is today (**recommended**);
   - (b) skip it with a warning;
   - (c) inline anyway, which reintroduces the unbounded event and is forbidden by §4.2's aggregate invariant, so this option would need that invariant relaxed.
   
   No ADR records degrade-to-inline as a requirement; the code argues for it at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:899-918`.
3. **Prompt substitution of a primary > `I`:**
   - (a) substitute the first `I` bytes plus a note naming the injected file path `artifacts/input/<phase-id>/…` where the full file is (**recommended**: a prompt holding megabytes is already broken for the harness);
   - (b) download it in full for substitution only, which breaks the retention bound by one primary per phase.
4. **API `POST /artifacts` with text > `I`:**
   - (a) upload, then create by reference; 503 on storage outage (**recommended**, keeps the endpoint working);
   - (b) refuse with 413.
5. **Whether to open the agentic-workspace streaming-write follow-up now** (§9). It is the only thing that brings the injection peak from one file to `R`.
6. **Whether to do PR 9** (projection v8 rebuild). Its value depends on the production size distribution, which only a query over `artifact_summaries.size_bytes` on flywheel can answer.
7. **Whether all artifact-context events should join the event-compat fixtures**, and whether the gate should run in CI (§4.7). This plan adds `ArtifactCreated` because its safety depends on it. The rest is a policy call for the ADR-072 D9 owner.
8. **Per-phase output file cap for `artifacts/output/`.** Today it is `MAX_COLLECTION_MATCHES = 10_000`, which allows about 100 MiB of retained metadata over ten phases (§4.5). Options:
   - (a) a separate, lower cap for phase outputs, for example 1,000, with collection failing loudly rather than stopping silently past it;
   - (b) keep 10,000 and accept the `F × m` term outside the budget.
   
   **Recommended: (a).**
9. **JSON content cap value** (`artifact_json_content_max_bytes`). Proposed 1 MiB. Above it, `content` is null and the frozen dashboard shows no body (R10).

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| **B1** Ceiling omits retained inline files and injection | **Accepted** | Verified: the cache keeps every file (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/processor_types.py:64-74`, built at `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:640-642`), and `_inject_and_log` materialises all phases (`:539-546`). The cache now retains **no** file bodies: uploaded files are `StoredBody`, event-only files are `EventOnlyBody(artifact_id)` resolved through `ArtifactRepository.get_by_id` at injection. Injection now goes one file at a time (PR 6). §4.5 states four separate peaks, including the `str` expansion, event serialisation and `F × m` metadata. The ceiling claim is narrowed to collection + retention, with injection's own limit named (largest file ≤ `max_file_size_bytes`, up to 500 MiB) as a gap. T12 is relabelled an arithmetic guard. Added T2b (many small files), T7b (many small + event-only), T13 (inherited-output injection). Added decision §11.8 for the file-count term. |
| **B2** PR 3 deletes methods callers still need | **Accepted** | Verified the callers: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ArtifactCollector.py:922`, `packages/syn-domain/src/syn_domain/contexts/artifacts/domain/services/artifact_query_service.py:226`, `apps/syn-api/src/syn_api/routes/artifacts.py:328`, `:467`, `:509`. PR 4 now **adds** `put` / `open_stream` / `read_text` and turns `upload` / `download` into facades. A new PR 8 removes them after the last caller. PR 5b migrates every `CreateArtifactCommand` caller, including the API `create_artifact` (large text uploaded first; decision §11.4) and `upload_artifact`, plus T15. |
| **B3** Fixtures alone do not make the compat gate work | **Accepted, plus one correction of my own** | Verified at `scripts/check_event_compat.py:61`, `:262-267`, `:326-341`, `scripts/event_compat/probe.py:28-37`. A new PR 1 adds a `context` on fixtures in both processes and scopes the epoch excuse to orchestration fixtures, tested by T5. The behavioural T4 and the reader-before-writer release rule are kept. Also found that the gate runs in no CI workflow, so the plan's "enforced" wording is corrected to "checked at release time" and CI wiring is listed as out of scope and as decision §11.7. |
| **B4** Bounded JSON read needs a real dashboard migration | **Accepted** | Verified at `apps/syn-ui/src/routes/artifacts/Detail.svelte:182-190`, `:217-218`, `apps/syn-dashboard-ui/src/pages/ArtifactDetail.tsx:42-43`, and the CLI at `apps/syn-cli-node/src/commands/artifacts.ts:107-110`. The JSON contract is now concrete: `content` is null above the cap (never a prefix), with new `content_preview` and `content_truncated`. PR 7 includes Skyline (`requestBlob` over the authenticated `clientConfig().fetch`; Download always via `/raw`; labelled preview), the CLI `/raw` fallback, and the frozen-dashboard policy (visible absence, R10). Added T14 and T16 (hash of the downloaded blob). |
| **I1** Classifier loses WebP; T1 is circular | **Accepted** | Verified WebP at `packages/syn-domain/src/syn_domain/contexts/artifacts/_shared/value_objects.py:150`. The prefix buffer is 12 bytes. T1 now checks a hand-written expected-MIME table (WebP without extension, text-first `.png`, split and truncated multibyte, chunk sizes around 12), never `of` vs classifier. Classifier split into its own PR 5a. |
| **I2** Stream lifetime, replayability, async/sync bridge | **Accepted, with a simpler mechanism than the review implied** | The `asyncio.Queue` design is dropped. `put_object` already runs in one executor thread (`packages/syn-adapters/src/syn_adapters/object_storage/minio.py:283-289`), so a synchronous, re-openable `ByteReader` is consumed in that thread, with no handoff, no queue to unblock and no cancellation path to design. Re-open is a stated protocol requirement. `SourceChangedError` propagates unconverted. Multipart is aborted and the key deleted on failure. Download responses close in `finally`. Change detection covers fstat identity (dev, ino, size, mtime_ns), exact-length reads and a three-way hash. T6 covers grow, shrink, same-length rewrite and rename-replace. T3 covers no orphaned object. |
| **I3** Test instrumentation and small contract claims | **Accepted** | T9 consumes `/raw` via streaming ASGI and hashes and discards chunks, never touching `response.content`. T3 asserts `tracemalloc`, reports RSS from a subprocess, and drops the unverified `2 × P` claim. `StorageResult.sha256` is corrected to `content_hash` (`packages/syn-domain/src/syn_domain/contexts/artifacts/ports/ArtifactContentStoragePort.py:50`). `StoragePlacement` keeps `artifact_type`. The e2e test uses 40 MiB under defaults, or a declared `SYN_STORAGE_MAX_FILE_SIZE_MB` override for 100 MiB. |
| **I4** Two authorities for inline vs reference; location vs MIME | **Accepted** | `I` becomes a domain constant `MAX_INLINE_ARTIFACT_BYTES` beside `MIN_ARTIFACT_CONTENT_LENGTH`. The aggregate enforces the §4.2 table without reading settings; writers choose by the same constant and are refused if wrong. The command states a fact (`content` ≤ `I` and/or `stored`). `body_location` decides only *where*; `ContentType.is_binary` decides *how to decode*. |

No finding was rejected. Every one checked out against the code at `366e650b1`. Two needed a different remedy from the one the review sketched: I2 (no queue at all) and B3 (the gate is not in CI either).

## Readiness

PRs 1, 3, 4 and 5a are **ready to implement now**. PRs 5b, 5c and 6 are **blocked on one human decision: the ADR-012 owner choosing `MAX_INLINE_ARTIFACT_BYTES` (§11.1) together with the storage-outage policy for text above it (§11.2).** The remaining §11 items have recommended defaults and can be confirmed in review.

