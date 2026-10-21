# Plan: #1970, a feedback ticketing server

**Status:** final plan, revised after cross-model review. Not yet implemented.

**Where this file goes:** `docs/plans/20261017_feedback-ticketing-server.md`. The date is the
session date, 2026-10-17. This phase had no shell, so `date -u` was not run. This phase may not
commit (its tools are Read/Grep/Glob/Write), so **PR 0** lands this file at that path unchanged
except for the status line. That is the only change PR 0 makes: the brief allows only the plan doc.

**Read on:** the `main` checkout in the workspace. Earlier phases name it as
`4acaaefdf22eb69776345b7650f7c8fd5228e7bd`; this phase has no git tool to confirm it. Every
`file:line` below is a repository-root path and was re-read in this phase or the plan phase. The
issue facts come from the research phase's `gh issue view 1970 --comments` and are attributed to
the issue, not to code.

Closes #1628 when built. Touches #1385 (keeps its off-by-default contract) and #856 (retires the
backend half of the untested library).

---

## 1. The problem, and what the code does today

**What the issue asks for** (issue #1970, its body and two owner comments, 2026-10-14 to
2026-10-17):

- a ticket id (UUIDv7) plus a short number `FB-123` that a submitter can look up;
- provenance on every ticket: signed key id, surface, version/commit and route, with unsigned
  marked `anonymous`;
- per-deployment signing with HMAC over body + timestamp + nonce, and a 5-minute replay window;
- Cloudflare WAF, a rate rule, and Turnstile on the anonymous lane;
- Redis buckets per key and per IP, a 16 KB body cap, screenshots by a separate presigned upload,
  and a per-deployment daily quota;
- an append + 202 ingest, with a classifier running off a queue;
- a "System 1" classifier (candidate Haiku 5.5, chosen by eval) that sets P0-P3, a type, and an
  injection-risk verdict;
- quarantine, and a batched owner digest that pages only on a spike;
- spam dropped, counted per source, with repeat offenders throttled;
- exact dedup by content hash per source, and near-duplicate merge with a reporter count;
- auto-filed GitHub issues only above confidence and dedup thresholds;
- links from ticket to GitHub issue, PR, execution and release (#1628);
- an eval seed set of real VPS feedback + injection strings + synthetic spam, measuring the
  false-quarantine rate.

**What exists today:**

| Fact | Evidence |
|---|---|
| Feedback is mutable, deletable CRUD rows. POST returns 201 synchronously, and no route has an identity dependency (each takes only `storage`) | `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/api/feedback.py:17` (prefix), `:83-89` (POST), `:92-102` (PATCH), `:105-113` (DELETE) |
| The id is UUIDv4, and there are no ticket-number, link, hash or quarantine columns | `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/migrations/001_feedback_tables.sql:10`; `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/migrations/002_feedback_subject.sql:10-12` adds only `subject_kind`, `subject_id` |
| Rows carry `status`, `assigned_to` and `resolution_notes`, which an import must preserve | `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/migrations/001_feedback_tables.sql:28-31`, `:46` |
| `comment` and `url` are unbounded. The model is not `frozen`/`extra="forbid"`. The client supplies `hostname` and `git_branch` | `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/models/feedback.py:59`, `:79`, `:90-91`, `:93` |
| Priority is low…critical, not P0-P3 | `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/models/feedback.py:31-37` |
| Media is stored as BYTEA. `external_url` is unused. Uploads check the size on both the declared and the received bytes, and check MIME + magic bytes | `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/migrations/001_feedback_tables.sql:72-73`; `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/api/media.py:14-27`, `:74-84` |
| Storage is this deployment's observability DB, with no in-memory fallback in production. One module decides the flag, the storage and the schema | `apps/syn-api/src/syn_api/services/ui_feedback.py:1-19`, `:82-94` |
| The flag defaults to off and gives a typed 404. The routes appear in OpenAPI in both states, and a test pins the legacy paths | `packages/syn-shared/src/syn_shared/settings/config.py:882-895`; `apps/syn-api/src/syn_api/services/ui_feedback.py:151-159`; `apps/syn-api/tests/test_ui_feedback_feature_flag.py:170-179` |
| The feedback service is a recoverable degraded service | `apps/syn-api/src/syn_api/services/lifecycle.py:941-946` |
| The orchestrator dispatches from raw open feedback | `.claude/skills/orchestrating/SKILL.md:93`; `.claude/skills/orchestrating/references/tick.md:66-68` |
| **The browser** posts provenance (including the commit it read) straight to `/feedback`, then uploads media per item | `apps/syn-ui/src/shell/FeedbackDialog.svelte:202-225`, `:228-243`; `packages/syn-ui/data/src/resources/feedback.ts:41-43`, `:63-68` |
| Other live consumers of the legacy routes: the bubble's stats and recent list, and the detail view's get, media and PATCH | `apps/syn-ui/src/shell/FeedbackBubble.svelte:62`, `:71`; `apps/syn-ui/src/shell/feedback/FeedbackDetail.svelte:37-40`, `:58`; `packages/syn-ui/data/src/resources/feedback.ts:53-60`, `:74-92` |
| The frozen React app mounts the old widget against same-origin `API_BASE` | `apps/syn-dashboard-ui/src/components/feedback/FeedbackWidgetChunk.tsx:44-46`; frozen and receiving no new features: `docs/adrs/ADR-073-svelte-for-syn-ui.md:13`, `:22` |
| The CLI reads `/feedback` | `apps/syn-cli-node/src/commands/feedback.ts:55` |
| The client's 10 MiB constant contradicts the API's 5 MiB | `packages/syn-ui/data/src/resources/feedback.ts:23-24` vs `apps/syn-api/src/syn_api/services/ui_feedback.py:43` |
| Webhook HMAC has no timestamp and no nonce | `apps/syn-api/src/syn_api/routes/webhooks/signature.py:15-29` |
| Gateway: the webhook location runs with `auth_basic off` and its own zone. `/api/v1/` caps bodies at 6M. Real IP comes from `CF-Connecting-IP` | `infra/docker/images/gateway/docker-entrypoint.sh:123-139`, `:164-165`; `infra/docker/images/gateway/nginx.conf:85-87`; `infra/docker/images/gateway/rate-limit.conf:8-23` |
| **MinIO presigned upload is not implemented.** `for_upload` is ignored, the helper only signs GET, and on error it **returns an unsigned URL** | `packages/syn-adapters/src/syn_adapters/object_storage/protocol.py:232`, `:239`; `packages/syn-adapters/src/syn_adapters/object_storage/minio.py:396`, `:403`; `packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:293-308` |
| The server knows its own build: version, image tag and commit | `apps/syn-api/src/syn_api/build_info.py:83`, `:95-108` |
| A stable, unsigned installation id exists | `packages/syn-shared/src/syn_shared/settings/session_inventory.py:23-27` |
| `process_pending()` runs only for live events. Backlog is delivered without running the processor side | `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/process_manager.py:133-142`; `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py:89-105`, `:117-125` |
| **A durable platform clock already exists.** One `InventoryReconciliationSweep` event is appended per interval, and orchestration's QuarantineNotice PM subscribes to it by name as "the wake that does not depend on anything else happening" | `packages/syn-adapters/src/syn_adapters/session_inventory/clock.py:20`; `packages/syn-shared/src/syn_shared/settings/session_inventory.py:28-33`; `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_quarantine/QuarantineNoticeProcessManager.py:66-82` |
| **The github context exports no PR domain events.** PR events reach consumers as pipeline observers, which are live-only and never see a deduplicated event. A merge recorder is the precedent: idempotent by `(repository, number)` | `packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py:66-82`; `apps/syn-api/src/syn_api/services/shipped_ledger.py:5-14`, `:106-135`, `:153-164` |
| `DedupPort` is re-exported from github's public API. The Redis adapter is a TTL'd SET NX check, not a durable outcome | `packages/syn-domain/src/syn_domain/contexts/github/__init__.py:66`, `:103`; `packages/syn-adapters/src/syn_adapters/dedup/redis_dedup.py:28-41` |
| The API is one uvicorn process with no `--workers`. Postgres is one instance for event-store tables, projections and observations | `docs/north-star.md:127`, `:129` |
| The eval runner launches real agent runs. Its holdout is "run to report the result, never to choose it" | `scripts/eval_suite.py:39-45`, `:47-51` |
| Vocabulary and context must land together (fitness tests in both directions) | `ci/fitness/code_quality/test_ubiquitous_language.py:62-68`, `:81-89` |

**Why it matters.** Opening intake to other deployments removes the only guard between a writer and
an agent prompt, which today is Basic Auth. It also adds flood load to a synchronous write path
that has no JSON cap below 6 MB and no per-sender limits.

---

## 2. Shape

A new bounded context, **`feedback`**, holds two event-sourced aggregates: **Ticket** and
**Source**. The whole flow:

```
browser ──► local syn-api  Relay (same origin, existing Basic Auth)
             │  owns the source key, stamps get_build_info(), strips fields,
             │  durable outbox, client_submission_id (UUIDv7) per submission
             ▼
           Cloudflare (WAF, rate rule; Turnstile only for the anonymous web lane)
           ──► gateway  location ^~ /intake/v1/  (auth_basic off, own zone, 16k JSON / 5M media)
           ──► Intake container: IP bucket → parse → admission budget → lane checks → append → 202 receipt
                                         │
                       feedback_intake (Postgres; insert-only from Intake; purgeable)
                                         │ lease (short txn), persisted verdict, persisted disposition
           syn-api Screener ── ScreeningPort ──► ScreeningPolicy / NearDuplicateMatcher (pure, domain)
                                         │ OpenTicket / AddReport / none
                                 TicketAggregate (event store; hashes, never text)
                                         │
     ProcessManagers on the durable clock: Triage (file / digest / quarantine alert),
     SourceGuard (spam throttle), FixResolver (#1628)
     Pipeline observer: PullRequestLinker → idempotent commands
```

Raw text never enters the event store. Events carry the `submission_id` and the `content_hash`, so
text can be erased and injection strings never reach a projection.

**One code path for every deployment.** With the flag on, a deployment runs the Relay. Where the
Relay sends depends only on `SYN_FEEDBACK_FORWARD_URL`:
- **Unset:** it sends to the deployment's own Intake. The deployment runs the context, Intake and
  Screener itself. The owner's VPS is this case, and so is a private self-host.
- **Set:** it sends to central. The deployment runs only the Relay and its outbox.

"Central" is simply a deployment whose Intake also accepts other enrolled sources.

### 2.1 Bounded context `feedback`

`packages/syn-domain/src/syn_domain/contexts/feedback/`, laid out as `domain/aggregate_<name>/`
per ADR-020.

It is a context of its own because its words collide with orchestration's:
- **Quarantine** there is a git ref (`docs/architecture/orchestration-ubiquitous-language.md:514`);
- **Eval** is an orchestration aggregate (`docs/architecture/orchestration-ubiquitous-language.md:934`);
- **Shipped** is reserved for agent-authored work (`docs/architecture/orchestration-ubiquitous-language.md:92`).

A context boundary is what lets each of these words mean something else here.

**Aggregate: Ticket** (`domain/aggregate_ticket/TicketAggregate.py`)

| Event | Carries | Guard |
|---|---|---|
| `TicketOpened` | `ticket_id` (UUIDv7, allocated once by the Screener and persisted on the intake row), `number`, `submission_id`, `content_hash`, `source_id` or `anonymous`, `provenance`, `screening` (`clean`\|`quarantined`), `type`, `priority` P0-P3, `confidence`, optional `recurrence_of` | the stream must not exist. A retry with the same `ticket_id` is a no-op success |
| `TicketReportAdded` | `submission_id`, `source_id`, `similarity` | refused on closed/resolved. A quarantined submission never joins a clean ticket. **A submission already a member is a no-op**, so the reporter count cannot rise twice |
| `TicketReportDetached` | `submission_id`, `by`, `reason` | the owner's correction of an over-merge. The detached submission is reopened as its own ticket by the same route (§2.4) |
| `TicketReleasedFromQuarantine` | `by`, `reason` | only while quarantined |
| `TicketReprioritised` | `priority`, `by` | |
| `TicketLinkedToIssue` | `repository`, `repository_id`, `number` | refused while quarantined |
| `TicketLinkedToExecution` | `execution_id` | refused while quarantined |
| `TicketPullRequestLinked` | `repository`, `repository_id`, `number` | refused while quarantined. Several PRs are allowed. A repeat is a no-op |
| `TicketPullRequestStateChanged` | `repository`, `number`, `state` (`open`\|`closed`\|`merged`), `merge_commit?`, `observed_at` | the PR must be linked. An observation older than the last one recorded is ignored. `merged` is terminal |
| `TicketFixObserved` | `source_id`, `commit`, `version`, `contains_fix` (bool), `observed_at` | requires a merged PR. Kept per source: the latest `observed_at` wins and older ones are ignored |
| `TicketFixReleased` | `release_tag`, `version`, `commit` | requires a merged PR |
| `TicketResolved` | `rule` (`released`\|`all_reporters_observed`), `version` | emitted by the aggregate in the same command whose event makes `ResolutionPolicy` true. Carries the version that #1628's note names |
| `TicketClosed` | `reason` (`wont_fix`\|`duplicate_of`\|`invalid`\|`legacy`), `duplicate_of?` | |
| `TicketReopened` | `by`, `reason` | from closed or resolved (a regression) |

**Status** is derived:
- `quarantined`;
- `closed`;
- `resolved`;
- `fix_merged`: some linked PR merged, and the ticket is not resolved;
- `in_progress`: some linked PR is open;
- `open`.

**Per-report status** is shown to that report's source as "fixed in your deployment at `<version>`"
once its source has a `contains_fix` observation.

**ResolutionPolicy** (pure, in `domain/`). The default is proposed and needs owner confirmation
(**D7**). A ticket resolves when:
- **(a)** a published release contains the fix; or
- **(b)** every *signed* source with a report on the ticket has a `contains_fix` observation.

Anonymous reports, and sources that never call in again, therefore resolve through (a). Betas
create no GitHub release (CLAUDE.md "Betas"), which is why (b) exists: the owner's VPS on a beta
still resolves its own tickets.

**Ticket numbers** come from a Postgres sequence in the feedback schema. The Screener draws one
when it decides `open`, and persists it on the intake row (§2.4), so a retry never draws a second.
Gaps are allowed. A projection maps `FB-<n>` to `ticket_id`. An event-sourced counter aggregate
was rejected because it serialises every ticket open through one stream.

**Aggregate: Source** (`domain/aggregate_source/SourceAggregate.py`). One per enrolled deployment,
bound to its `source_instance_id`
(`packages/syn-shared/src/syn_shared/settings/session_inventory.py:23-27`).

| Event | Notes |
|---|---|
| `SourceEnrolled` | `source_id`, `key_id`, public key or secret hash (D2), `daily_quota` |
| `SourceKeyRotated` | the old key stays valid for an overlap window set in settings |
| `SourceThrottled` / `SourceThrottleLifted` | throttling is dispatched by SourceGuard (§2.6). The owner lifts it |
| `SourceRevoked` | terminal |

**Not aggregates** (`domain/`):
- `ScreenedText`: deterministic normalisation. Strip C0/C1 controls and zero-width and
  bidi-override code points, apply NFC, collapse whitespace, cap at 4,000 chars. It also runs a
  **best-effort secret-shape redaction** (API-key, token and private-key patterns) as defence in
  depth. **This is not a PII control.** The PII control is the publication policy in §2.7.
- `ScreeningPolicy`: `(ScreeningResult, thresholds) -> Open | Quarantine | Drop`.
- `NearDuplicateMatcher`: shingle Jaccard over `ScreenedText`. Candidates share a match bucket:
  the same route, or the same type when there is no route.
- `ResolutionPolicy`: described above.
- Ports (`ports/`):
  - `ScreeningPort`;
  - `IntakeLog` (lease, record verdict, record disposition, mark dispatched, purge);
  - `NonceLedger`;
  - `RateBuckets`;
  - `ForgeReads` (PR state, compare, releases).

`NonceLedger` is feedback's own port, and `RedisDedupAdapter`
(`packages/syn-adapters/src/syn_adapters/dedup/redis_dedup.py:28`) satisfies it structurally.
That is a **design judgment, not an ADR-062 requirement**: rule 3 forbids only *deep* imports
(`docs/adrs/ADR-062-cross-context-public-api-enforcement.md:40-43`), and `DedupPort` is public
(`packages/syn-domain/src/syn_domain/contexts/github/__init__.py:103`). Feedback keeps its own port
because replay rejection is not GitHub event dedup. The two would change for different reasons.

### 2.2 Where it runs

| Piece | Runs in | Why |
|---|---|---|
| **Relay** | syn-api, under the existing `/api/v1/feedback/…` (behind Basic Auth whenever the deployment is exposed) | The browser never holds the key and never talks to central. syn-api already knows its own build (`apps/syn-api/src/syn_api/build_info.py:95-108`) and is where the flag is decided (`apps/syn-api/src/syn_api/services/ui_feedback.py:8-14`). It is the one client-facing feedback boundary |
| **Intake** | a new container, `apps/syn-feedback-intake` (FastAPI). It has syn-shared settings, Redis, and the `feedback_intake` / `feedback_sources` / `feedback_ticket_status` tables. **No event-store client** | It is the second unauthenticated public surface after webhooks. syn-api is a single process (`docs/north-star.md:127`), whose read p95 is the north-star pass bar (`docs/north-star.md:19`). The north star *hypothesises* that this single process is a 100-tier limit (`docs/north-star.md:166`). That is a reason not to add a public flood surface to it, not a measured fact |
| **Screener** | syn-api background service, a degraded-service entry like the existing feedback one (`apps/syn-api/src/syn_api/services/lifecycle.py:941-946`) | It needs the event store and the aggregates. Its rate is bounded by a settings concurrency and a calls-per-minute budget, not by intake volume |
| **Triage, SourceGuard, FixResolver PMs** | the existing coordinator (ADR-055), subscribed to the durable clock | §2.6 |
| **PullRequestLinker** | a pipeline observer in syn-api, modelled on `apps/syn-api/src/syn_api/services/shipped_ledger.py:106-135` | There are no PR domain events to subscribe to (§1) |
| **Owner/agent read routes** | syn-api, behind Basic Auth | reading is not the abuse surface |

**Shared database.** Isolating the process does not isolate Postgres, which is one instance
(`docs/north-star.md:129`). Intake therefore gets hard global budgets (§2.3), and its connection
string is its own setting, `SYN_FEEDBACK_INTAKE_DB_URL`. That lets D1 place the intake log on a
separate instance without code change.

### 2.3 Ingest path

**Relay (local, per deployment).** `POST /api/v1/feedback/submissions` takes text and context.
`POST /api/v1/feedback/submissions/{client_submission_id}/media` takes multipart media and keeps
today's checks (`lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/api/media.py:74-84`).

1. It validates a frozen, `extra="forbid"` request with `max_length` on every string. The client
   supplies no priority and no type.
2. It **ignores the browser's version and commit**, and stamps `get_build_info()` server-side.
3. It drops `hostname`, `git_branch` and the URL query string. Today all three are client fields
   (`lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/models/feedback.py:59`, `:90-91`).
4. It allocates `client_submission_id` (UUIDv7), and writes text and media to a durable
   `feedback_outbox` in the local DB. There is no in-memory fallback (ADR-060).
5. It answers `202 {client_submission_id}`.

An outbox worker signs each item with the source key and sends it to Intake. The key is a
`SecretStr` setting or a file. It is never served and never in a browser asset. The same
`client_submission_id` is used on every retry, so a retry is idempotent at Intake.

A **status sync** runs on the same worker. It is a periodic signed poll for this source's
non-terminal submissions. It gives the local bubble its "my submissions" list (§2.8), and its
signed headers carry the current build. That is how central observes a source's build for #1628
without a separate heartbeat.

**Gateway (central).** A new `location ^~ /intake/v1/`, modelled on the webhook block
(`infra/docker/images/gateway/docker-entrypoint.sh:123-139`):
- `auth_basic off`;
- its own `feedback` zone in `infra/docker/images/gateway/rate-limit.conf`;
- `client_max_body_size 16k` on JSON paths and 5M on `/intake/v1/media`;
- `proxy_pass` to the Intake container;
- the real IP from `infra/docker/images/gateway/nginx.conf:85-87`.

It uses a distinct prefix so it cannot collide with the Relay's `/api/v1/feedback/*` on the
central deployment.

**Intake**, in order of increasing cost. No LLM and no event store at any point.

1. **Per-IP bucket** (Redis Lua, atomic) **before anything is parsed or verified.**
2. Raw-length and header-shape checks, then a parse into `SubmissionV1` (frozen, `extra="forbid"`,
   `max_length` everywhere).
3. **Global admission budget, both lanes.** All of these are settings:
   - an unscreened-backlog ceiling, where the anonymous lane sheds at a lower watermark and
     **both** lanes get `503 Retry-After` at the hard ceiling;
   - a global daily row budget;
   - a global media-bytes budget.
4. **Signed lane.** The headers are `X-Syn-Source`, `X-Syn-Key-Id`, `X-Syn-Timestamp`,
   `X-Syn-Nonce` and `X-Syn-Signature`. The signature covers
   `method \n path \n ts \n nonce \n sha256(body)`.
   1. **Source lookup.** The source id must be in an in-process set refreshed from
      `feedback_sources` every 30 s. An unknown id gets 401 with no DB read and no crypto.
   2. **Verification.** A per-source *failed-verification* bucket comes first. It is kept separate
      from the source's real quota, so forged traffic cannot drain an honest source. Then come
      constant-time verification, the ±300 s window, and the nonce via `NonceLedger` (TTL 600 s,
      longer than the window).
   3. **Quota.** Then the per-source bucket and the daily quota. A throttled source is rejected
      here.
5. **Anonymous lane** (only if D9 keeps it): an anonymous global bucket, then server-side Turnstile
   verification with a 2 s timeout. The lane fails closed.
6. **Append** to `feedback_intake`. The insert is idempotent on
   `(scope, client_submission_id)`, where `scope` is the `source_id` (signed) or the `ip_hash`
   (anonymous). A replayed retry returns the existing `submission_id`. A changed build
   commit/version for the source is written to `feedback_source_builds` (a conditional update, so
   one write per change).
7. **`202 {submission_id}`.** This is a **receipt**, not a ticket. The ticket number exists only
   after screening (I4).

**Redis down → 503 on both lanes.** This fails closed, deliberately. GitHub dedup fails open
because trigger guards back it up, and a public endpoint has no such backstop. ADR-060 forbids an
in-process fallback. The Relay outbox simply retries.

**Media (D10).** The default, recommended here, is **Relay-forwarded media**. The Relay sends each
file signed to `POST /intake/v1/media/{submission_id}`, keyed to the submission (not the ticket),
so a pending submission keeps its files. Intake then:
- re-checks the actual bytes and magic (the logic of
  `lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/api/media.py:14-27`);
- enforces at most 4 files per submission and the global and per-source byte budgets;
- writes to MinIO server-side under `submissions/<submission_id>/`.

The bucket is created eagerly per CLAUDE.md. The browser never needs a central origin, a public
MinIO URL, or CORS.

The owner's draft says "presigned". If D10 keeps presigned uploads, PR 5 must:
- implement `for_upload` in `packages/syn-adapters/src/syn_adapters/object_storage/minio.py:396`
  as a **POST policy** (`content-length-range`, a Content-Type condition, short expiry), since a
  plain PUT URL cannot cap size;
- make signing failure **raise** instead of returning the unsigned fallback at
  `packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:304-308`;
- add a finalise call that reads the object's size and magic and deletes it on mismatch.

Either way:
- media is attached to the ticket only at disposition, and only for clean tickets;
- quarantined and spam media are never served;
- a clock sweep deletes objects with no intake row after 24 h, and media of purged rows.

### 2.4 Screener: durable, idempotent processing

`feedback_intake` columns:
- `submission_id` (UUIDv7), `scope`, `client_submission_id`, `lane`, `source_id`, `ip_hash`,
  `provenance`, `raw_text`, `content_hash`, `received_at`;
- **lease:** `lease_owner`, `lease_until`, `attempts`;
- **persisted verdict:** `verdict`, `type`, `priority`, `confidence`, `screener_id`, `screened_at`;
- **persisted disposition:** `disposition` (`open`\|`report`\|`exact_duplicate`\|`quarantine`\|`spam`\|`failed`),
  `target_ticket_id`, `ticket_number`, `decided_at`;
- `dispatched_at`.

The Screener's steps:

1. **Lease.** In a *short* transaction, run `UPDATE … SET lease_owner=$w, lease_until=now()+$L,
   attempts=attempts+1 WHERE submission_id IN (SELECT … WHERE dispatched_at IS NULL AND
   (lease_until IS NULL OR lease_until < now()) ORDER BY received_at LIMIT $n FOR UPDATE SKIP
   LOCKED) RETURNING …`, then commit. **No transaction or connection is held across a model
   call.** A crashed worker's rows return when the lease expires.
2. **Verdict.** If the row has no verdict, build `ScreenedText`, call `ScreeningPort`, and write the
   verdict `WHERE lease_owner=$w`. A lost lease discards the write. If a verdict exists it is
   **reused, never recomputed**, so a retry cannot flip the outcome.
3. **Disposition.** This is one transaction, serialised per match bucket with
   `pg_advisory_xact_lock(hash(bucket))`. Concurrent near-duplicates therefore converge: the second
   worker sees the first one's decision. Candidates are read from **`feedback_intake`'s own
   disposition rows** in that same transaction, not from a lagging projection.
   - Spam gives `spam`.
   - Quarantine gives `quarantine`, with a new UUIDv7 and a number. These are never merged.
   - The same scope + `content_hash` as an earlier row inside the exact-dedup window (a setting,
     default 24 h) gives `exact_duplicate`, targeting the earlier ticket with no report.
   - A matcher hit gives `report`, targeting the existing ticket.
   - Anything else gives `open`, with a UUIDv7 and a number drawn now.

   The disposition is persisted before any command is sent.
4. **Dispatch** from the persisted disposition only:
   - `OpenTicket` on an existing stream is success;
   - `AddReport` for a submission that is already a member is success;
   - `AddReport` refused because the target is closed or resolved re-decides the row once as
     `open` with `recurrence_of`.
5. **Mark** `dispatched_at`.

A crash between any two steps resumes from the last persisted step. Model errors retry with
backoff. After `max_attempts` the row becomes `quarantine` (it fails closed) and is counted for the
alert.

Retention:
- spam rows are purged after 7 days;
- closed tickets' text is purged after a settings period;
- events hold only hashes, so purging touches no events.

### 2.5 Abuse controls, by attack

| Attack | Control | Where |
|---|---|---|
| Volumetric flood | Cloudflare rule → nginx zone → per-IP bucket (before parsing) → global backlog / row budget, shedding both lanes | edge, gateway, Intake |
| Many enrolled sources, each within quota | the global row and byte budgets; `SYN_FEEDBACK_MAX_SOURCES`; enrollment is rate-limited and new sources start low or held (D3) | Intake, Source |
| Invalid source ids | rejected from the in-process cache, with no DB read and no crypto | Intake |
| Forged signatures against a real source | a per-source failed-verification bucket, separate from its quota | Intake |
| Invalid Turnstile tokens | the anonymous bucket comes before siteverify; 2 s timeout; fails closed | Intake |
| Large bodies | 16 KB (JSON) / 5 MB (media) at nginx and again in Intake; field `max_length` | gateway, Intake |
| A leaked source key | per-key bucket, daily quota, throttle, revoke, rotate | Intake, Source |
| Replay | ±300 s window + single-use nonce (600 s TTL), both covered by the signature | Intake |
| Retry duplication | unique `(scope, client_submission_id)` | Intake |
| Spam from a known source | dropped and counted. SourceGuard throttles repeat offenders | Screener, SourceGuard |
| Prompt injection aimed at agents | quarantine. Agents read only the clean view, fenced as untrusted. Quarantined text never reaches an agent, GitHub or an event | Screener, read route |
| Injection aimed at the classifier | adversarial bench cases. A closed output schema. A parse failure becomes quarantine | ScreeningPort, bench |
| A secret or email inside a clean report | public issues carry no free text (§2.7). Secret-shape redaction in `ScreenedText` is defence in depth only | IssueFiler, `ScreenedText` |

### 2.6 ProcessManagers: durable to-dos and a wake that always comes

`process_pending()` runs only on live events
(`lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/process_manager.py:133-142`).
A ticket opened just before a crash could otherwise sit in backlog forever
(`packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py:89-105`).

Every feedback PM therefore:
- keeps its to-dos in a **durable Postgres table with a `due_at`**, written only in
  `handle_event()`;
- **subscribes to the platform clock event `InventoryReconciliationSweep`** by name, exactly as
  orchestration does
  (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_quarantine/QuarantineNoticeProcessManager.py:66-82`).

The clock appends one tick per interval
(`packages/syn-adapters/src/syn_adapters/session_inventory/clock.py:20`, interval at
`packages/syn-shared/src/syn_shared/settings/session_inventory.py:28-33`). The first live tick after
a restart drains the backlog, and a deadline is met within one interval with no other event.
Reusing a clock named for inventory is a vocabulary wart, and it is recorded in §4. A feedback-owned
clock is the alternative if that clock's interval or lifecycle ever diverges.

The managers were consolidated from five to three, by scheduling behaviour (review I6):

| Manager | Input (durable) | Due | Side effect (live only, idempotent) |
|---|---|---|---|
| **Triage** | `TicketOpened`, `TicketReportAdded`, `TicketReleasedFromQuarantine` → a to-do row per ticket | issue: opened + settle delay. Digest: the next batch boundary. Quarantine alert: immediate when the count in the window exceeds a threshold | file the issue (search for the marker `<!-- syn-ticket:<id> -->` first) then `LinkTicketToIssue`; or post a digest; or send a text-free quarantine-spike alert to the D8 destination |
| **SourceGuard** | the spam counts in `feedback_intake` (`disposition='spam'`, rows kept for 7 days), read on each tick, which is the InventoryReplication precedent of a durable non-event to-do source (`packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/replicate_session_inventory/projection.py:49-68`). Spam deliberately produces no event | each tick | `ThrottleSource` when a source crosses its threshold. The aggregate refuses a second throttle |
| **FixResolver** | `TicketPullRequestStateChanged(merged)` → a to-do per ticket and pending source | each tick, while the ticket is `fix_merged` | reads `feedback_source_builds` and the compare API, then dispatches `RecordFixObservation`. Lists releases (one call per tick) and dispatches `RecordFixReleased` for tags containing the merge commit |

**PullRequestLinker** is a pipeline observer, as in
`apps/syn-api/src/syn_api/services/shipped_ledger.py:106-135`. A `pull_request` event whose body
has `Fixes FB-<n>` dispatches `LinkTicketToPullRequest` and `RecordPullRequestState`. Both are
idempotent in the aggregate. `Fixes feedback #N` is not used, because GitHub reads `#N` as an issue
reference. Observers miss deduplicated and cold-start events
(`packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py:72-77`).
**FixResolver's tick therefore also re-reads the state of every linked non-terminal PR**, which
makes the observer a fast path and the tick the guarantee.

**Production auto-filing gate.** Triage files GitHub issues only when
`SYN_FEEDBACK_AUTOFILE_BENCH_RESULT` names a committed result file under
`evals/feedback-screening-v1/results/`. That file must:
- match the configured screener and model;
- meet the D6 bar recorded in `suite.yaml`;
- carry the owner's approval field.

Otherwise everything goes to the digest, and `/health` shows a degraded reason. The App's live
`issues: write` grant is unverified (only a fixture says so); PR 11 starts by reading it.

### 2.7 Privacy, opt-in, publication

- **Off and inert by default** (#1385, `apps/syn-api/src/syn_api/services/ui_feedback.py:1-19`):
  - no tables, no Intake (a compose profile), no widget chunk, no outbound call;
  - the OpenAPI stays identical in both states
    (`apps/syn-api/tests/test_ui_feedback_feature_flag.py:170-177`).
- **Forwarding is a second opt-in:** `SYN_FEEDBACK_FORWARD_URL` plus `syn feedback enroll`, which
  generates the key locally and registers it. Both are decided in
  `apps/syn-api/src/syn_api/services/ui_feedback.py`, which stays the one place the feature is
  decided.
- **Before the first send**, the dialog shows the destination host and the D5 copy. If the
  `anthropic` screener is configured on the receiving side, the copy also says the text is
  processed by an external model provider.
- **Publication policy (D11, default proposed): a public GitHub issue carries no submitter free
  text.**
  - It carries the FB number, type, priority, route, version, reporter count and a link to the
    owner-only ticket.
  - The text stays on central behind Basic Auth, and agents read it through the fenced agent view.
  - Publishing text needs a per-ticket owner action.

  This is the actual PII and secret control: a credential in a comment cannot reach a public
  issue, whatever the normaliser misses. It also makes erasure meaningful. Erasing a ticket's text
  (`feedback_intake`, MinIO) leaves only structured fields public. The plan says plainly that an
  issue body once published cannot be recalled from caches.
- **Minimisation:**
  - forwarded provenance is key id, surface, server-stamped version and commit, and route;
  - IPs are kept only as a keyed hash.
- **The privacy statement** lives in `apps/syn-docs/content/` (D5).

### 2.8 Read paths and reporter contract

- **Owner** (Basic Auth, syn-api):
  - `GET /feedback/tickets` (filters: status, screening, type, priority, source);
  - `GET /feedback/tickets/{number}`, which includes the PR list, per-source observations and media;
  - `POST /feedback/tickets/{number}/release` | `close` | `reopen` | `split/{submission_id}`.

  Every route has a Pydantic response model, and `just codegen` feeds the CLI.
- **Agent view:** `GET /feedback/tickets?view=agent` always applies `screening=clean`, and the
  parameter cannot be overridden. It returns `TicketBrief`: number, type, priority, route,
  selector, viewport, version, reporter count, and `ScreenedText`.
- **Reporter, signed** (the owner's "look up status by number"):
  - the local bubble reads `GET /api/v1/feedback/submissions?mine`, filled by the Relay's status
    sync;
  - `syn feedback status FB-123` asks the Relay, which asks central with a signed request;
  - central answers **only if the requesting source has a report on that ticket**, with status and
    fixing version only. Without that, FB numbers would be an enumeration oracle.
- **Reporter, anonymous:** `GET /intake/v1/receipts/{submission_id}`. The receipt id is the
  capability. It returns status and the FB number once assigned. Spam and quarantined receipts
  both answer `received` and never reveal the verdict, so a spammer gets no tuning oracle.
- **202 is a receipt.** A ticket and a number exist only for a non-spam disposition. That differs
  from "every submission gets a ticket", and the vocabulary records it.

### 2.9 Consumer migration

| Consumer | Today | After |
|---|---|---|
| syn-ui dialog create + media | `apps/syn-ui/src/shell/FeedbackDialog.svelte:205`, `:230`, `:238` | Relay submissions + media (PR 8) |
| syn-ui bubble stats + recent | `apps/syn-ui/src/shell/FeedbackBubble.svelte:62`, `:71` | Relay `?mine` list and counts (PR 8) |
| syn-ui detail get / media / PATCH resolve | `apps/syn-ui/src/shell/feedback/FeedbackDetail.svelte:37-40`, `:58` | on a ticket-hosting deployment: the owner ticket detail and the close/reopen commands. On a forwarding self-host: status only. A reporter cannot resolve a central ticket (PR 8) |
| Upload ceiling constant | `packages/syn-ui/data/src/resources/feedback.ts:23-24` | read from `/features` (PR 8) |
| Frozen React widget | `apps/syn-dashboard-ui/src/components/feedback/FeedbackWidgetChunk.tsx:44-46` | **not edited** (`docs/adrs/ADR-073-svelte-for-syn-ui.md:13`, `:22`). From PR 8, legacy `POST /feedback` and `POST /feedback/{id}/media` become a **compatibility shim into the Relay outbox**, so no new write lands in the old table. Legacy reads, PATCH and DELETE keep serving the historical table until the React app is deleted |
| CLI `syn feedback list` | `apps/syn-cli-node/src/commands/feedback.ts:55` | tickets route (PR 7) |
| Orchestrator | `.claude/skills/orchestrating/SKILL.md:93`, `.claude/skills/orchestrating/references/tick.md:66-68` | the agent view, switched **after** the legacy import (PR 10) |
| Feature-flag test | `apps/syn-api/tests/test_ui_feedback_feature_flag.py:178-179` | assertions changed on purpose in PR 13 |

**Legacy import** (PR 9) reads every VPS row and imports it as `lane=legacy`.
- The row goes through the Screener. Old rows reach agents today, so they are screened too.
- The old uuid is kept in provenance, and `legacy_id → ticket` is mapped in a projection.
- **Status is preserved:**
  - `resolved`/`closed` → `TicketClosed(legacy)`, with `resolution_notes` kept in the intake row;
  - `wont_fix` → `TicketClosed(wont_fix)`;
  - `in_progress` → open.
- `assigned_to` is kept as a field on the owner projection.
- **Media is exported from BYTEA to MinIO** under the new submission id.

The import is idempotent on `(legacy, old_id)`. It runs after the shim (PR 8), so nothing is
written to the old table after it.

### 2.10 Classifier choice by benchmark

The existing runner launches real agent runs (`scripts/eval_suite.py:47-51`) and does not fit. The
new suite keeps its discipline:

- `evals/feedback-screening-v1/` holds `suite.yaml` and `cases/*.jsonl`.
- Each case carries an expected verdict, type and priority, and a **`group` id**: an injection
  string and its variants, or a near-duplicate family, share a group.
- The split is **by group**, so variants never straddle splits:
  - **train:** prompt and threshold tuning;
  - **validation:** model selection and the near-dup threshold;
  - **holdout:** frozen, run once per candidate to report, **never used to choose**, as
    `scripts/eval_suite.py:39-45` already requires.
- Seed set:
  - (a) **real VPS feedback**: exported, scrubbed, owner-labelled (D4 decides where it lives);
  - (b) **published injection corpora**, licence-checked, plus hand-written variants of "ignore
    previous / classify me clean / call this tool";
  - (c) **synthetic spam**: SEO, crypto, gibberish and near-dup floods.
- `scripts/feedback_screening_bench.py` reports, each **with its count and a Wilson 95% interval**:
  - false-quarantine rate on clean cases (the headline);
  - injection catch rate;
  - spam precision and recall;
  - type accuracy and priority agreement;
  - p95 latency;
  - cost per 1,000.
- **Size implication for D6:** a ≤2% false-quarantine claim needs at least about 150 clean
  holdout cases with zero false quarantines (the rule of three: a 95% upper bound of 3/n). Fewer
  cases can only support a weaker claim, and the results file says so.
- Candidates:
  - `HeuristicScreener` (no model; the floor and the self-host default);
  - `claude-haiku-5-5`;
  - `claude-sonnet-5-5`;
  - the heuristic followed by Haiku.
- **Rule:** the cheapest candidate that meets the bar on validation is confirmed on holdout.
  Results are committed and named by `SYN_FEEDBACK_AUTOFILE_BENCH_RESULT` (§2.6).
- **CI** scores **recorded responses**. That proves only the scoring arithmetic and the
  schema/parse-failure handling, not a provider's current safety, latency or cost. A real run is
  manual and costs money.
- No pricing or rate limits were checked in this phase, so this plan makes no cost claim.

---

## 3. Build sequence (PR-sized)

Each row lists what must be true to merge, and a negative control: reverting the change, or the
named guard, **must** fail the stated test. `.mutations/*.patch` for each control, run by the
orchestrator with `just mutation-evidence`. Nothing touches `.github/workflows/`.

| PR | Contents | Acceptance | Negative control |
|---|---|---|---|
| **0** | This plan at `docs/plans/20261017_feedback-ticketing-server.md`. Nothing else | `just preflight-agent` green | n/a (docs) |
| **1** | ADR-076 "Feedback ticketing" (the highest on disk is `docs/adrs/ADR-075-request-latency-telemetry.md`). `docs/adrs/ADR-016-ui-feedback-module.md` gets "superseded in part by ADR-076". The `contexts/feedback/` skeleton: Ticket aggregate and all §2.1 events, `ScreenedText`, `ScreeningPolicy`, `NearDuplicateMatcher`, `ResolutionPolicy`, ports, and `__init__.py` re-exports. `docs/architecture/feedback-ubiquitous-language.md` (§4), linked from `docs/architecture/README.md`. VSA validate | Unit tests: link on a quarantined ticket raises. A quarantined report into a clean ticket raises. **The same `AddReport` twice leaves the reporter count at 2, not 3.** A second `OpenTicket` with the same id is a no-op. PR closed then reopened gives `in_progress`, not `fix_merged`. Two PRs, one merged and one open, give `in_progress`. An older `TicketPullRequestStateChanged` is ignored. Two signed sources: one observation does not resolve, both do, and an out-of-order older observation does not un-resolve. Anonymous + signed: a release resolves both. `TicketResolved.version` is set. Detach drops the count | Remove the membership check → the double-report test fails. Make `ResolutionPolicy` "any source" → the two-source test fails. Delete the vocab file → `test_every_context_has_a_vocabulary[feedback]` fails |
| **2** | Source aggregate. A pure signing/verification module (canonical string, verify, window). `feedback_sources` projection | A fixed vector verifies. A one-byte body change fails. ts ±301 s fails. A revoked key fails. A rotated old key passes inside the overlap and fails after it | Drop the ts from the canonical string → the tampered-ts test passes when it must fail |
| **3** | `apps/syn-feedback-intake`: `SubmissionV1`; lanes in the §2.3 order; Redis Lua buckets; `NonceLedger` via `RedisDedupAdapter(ttl_seconds=600)`; global budgets; `feedback_intake` with lease/verdict/disposition columns; `feedback_source_builds`; `/intake/v1/` gateway location and zone; compose profile; ADR-004 settings including `SYN_FEEDBACK_INTAKE_DB_URL`, `SYN_FEEDBACK_MAX_SOURCES`. **Needs D2, D9** | Integration (test stack): valid → 202. The same `client_submission_id` again → the same `submission_id`, one row. 16,385 B → 413. Replayed nonce → 409. Stale ts → 401. Unknown source → 401 **with zero DB queries** (counted). Bad signature ×N → the honest source's quota is unchanged. Per-IP exhausted → 429 **before** any signature work (a verify-call counter stays at 0). Backlog at the hard ceiling → both lanes 503. Redis stopped → 503. Gateway test beside the existing gateway tests asserts `auth_basic off`, 16k, and the zone | Remove the unique `(scope, client_submission_id)` → the one-row test fails. Move the IP bucket after verification → the verify-counter test fails. Exempt the signed lane from the hard ceiling → the both-lanes-503 test fails |
| **4** | **Relay** in syn-api: the submissions route, `feedback_outbox`, outbox worker, server-stamped `get_build_info()`, field stripping, key store, the forwarding decision in `apps/syn-api/src/syn_api/services/ui_feedback.py`, status sync, `syn feedback enroll`. **Needs D2, D3** | Browser-level (Playwright, a real syn-ui build) against a self-host and a **separate** central origin: central verifies the signature. The stored commit is the server's `SYN_BUILD_COMMIT`, not a tampered client value. No key bytes appear in any asset or response (a grep over the built bundle and over captured responses). Flag on and forwarding unset → the request goes to the local Intake, and the HTTP spy sees no central host. Flag off → no outbound request. Central down → the outbox retries with the same `client_submission_id`, giving one row | Pass the client `git_commit` through → the tampered-commit test fails. Ignore the forwarding gate (always forward) → the forwarding-off spy test fails. Mutate the flag gate separately → the flag-off test fails |
| **5** | Media per D10. Relay-forwarded is the default: the `/intake/v1/media` route, magic and size checks, budgets, server-side MinIO write, eager bucket, orphan sweep on the clock. If presigned: POST-policy `for_upload` in `packages/syn-adapters/src/syn_adapters/object_storage/minio.py`, no unsigned fallback, finalise-and-validate | Real MinIO round-trip. Actual bytes over the limit despite a small declared size → 413 and no object. A PNG header on HTML → 400. Media for submission A cannot be attached to B. A fifth file → 429. An unauthenticated upload → 401. (Presigned only: an expired credential is refused; a signing failure **raises**.) Quarantined media is not served | Drop the received-bytes check → the over-limit test fails. (Presigned) Restore the unsigned fallback → the signing-failure test fails |
| **6** | `ScreeningPort` adapters (`HeuristicScreener`, `AnthropicScreener` with a closed output schema), the bench script, `evals/feedback-screening-v1/` with grouped train/validation/holdout (spam + injection until D4), recorded fixtures | CI scores recorded responses to known numbers, with intervals. A malformed model reply → quarantine. `check` refuses a group that straddles splits | Default a parse error to `clean` → the fixture test fails. Allow a group to straddle → the split-check test fails |
| **7** | Screener worker (§2.4), number sequence, owner and agent routes, `just codegen`, CLI `feedback list` on tickets | Integration: an injection fixture → quarantined and absent from the agent view. Crash **after OpenTicket**, **after AddReport**, and **before `dispatched_at`**, each followed by a retry → one disposition, one membership, unchanged reporter count. A retry whose screener now returns a different verdict reuses the persisted one. 10 concurrent near-identical submissions → one ticket, count 10. No transaction is open during the model call (assert on `pg_stat_activity`). `check:api-drift` clean | Re-screen when a verdict exists → the changed-verdict test fails. Remove the advisory lock → the concurrent test opens more than one ticket. Drop `screening=clean` from the agent view → the injection text appears |
| **8** | syn-ui migration (§2.9): the dialog, bubble and detail on the Relay and ticket routes; upload limit from `/features`; legacy `POST /feedback` + media **shim** into the outbox | Playwright: submit → recent list → detail → screenshot and voice playback → owner close/reopen on the new system. A write through the legacy POST lands in the outbox and the old table gains no row | Remove the shim → the legacy-POST test finds a new old-table row |
| **9** | Legacy import: text, status, notes, assignee, and BYTEA media → MinIO; old-id map | Run twice → the same ticket count. An imported resolved item shows closed(legacy) with its notes. Its media plays. An injection string in an old row is quarantined | Skip screening for `lane=legacy` → the injection test fails |
| **10** | Orchestrating skill: `.claude/skills/orchestrating/SKILL.md:93` and `.claude/skills/orchestrating/references/tick.md:66-68` switched to the agent view, with the untrusted-text fence | **Migration lint only:** no `GET '/feedback?status=open'` remains in `.claude/skills/`. The real proof that quarantine cannot leak is PR 7's agent-view test | n/a |
| **11** | Triage and SourceGuard PMs with durable to-do tables and the clock subscription. The auto-file gate. **Needs** the live `issues: write` grant read, D4, D6, D8 and D11 | Stop before filing, restart against backlog with no new submissions → the issue is filed after the first live tick. Advance past the settle/digest deadline with no new ticket → processed. Replay with `is_catching_up=True` → zero GitHub calls. A crash after create → the marker search finds the issue and nothing is duplicated. The issue body has no free text (a test with a secret + email in the comment). The quarantine spike → one text-free alert. Bench result withheld → zero issues filed, degraded reason shown | Drop the clock subscription → the restart test never files. Call GitHub from `handle_event` → the replay counter > 0. Put `ScreenedText` in the issue body → the secret test fails |
| **12** | PullRequestLinker observer and FixResolver PM (#1628) | `Fixes FB-12` → link. `Fixes #12` → none. A PR closed unmerged then reopened → `in_progress`. Two PRs. A missed merge event → the tick re-read records it. Two sources on different commits, observations out of order. A release containing the fix → `TicketResolved(released, version)`. A reporter sees "fixed in your deployment at vX" | Invert the ancestry check → the "not ancestor" source resolves and the test fails. Remove the tick re-read → the missed-merge test stays `in_progress` |
| **13** | Removal of lib/ui-feedback's backend CRUD/media routes and BYTEA table, `just feedback-migrate` (`justfile:612-614`, `:467`), the shim. **Gated on the React app's deletion** (`docs/adrs/ADR-073-svelte-for-syn-ui.md:13`). Intentionally rewrite `apps/syn-api/tests/test_ui_feedback_feature_flag.py:178-179` to assert the new paths | The OpenAPI is still identical in both flag states. The new paths are present and the legacy paths absent. Every §2.9 consumer row is migrated or deleted (a grep shows no `/feedback/{` callers in `apps/` or `packages/`) | Re-add a legacy route → the path-absence assertion fails |

What can run in parallel:
- PR 1, PR 2 and PR 6 (spam + injection part) can proceed now, in parallel with the decisions.
- PR 3 and PR 4 need D2. PR 3 also needs D9, and PR 4 needs D3.
- PR 5 needs D10.
- PR 6's real-data part, and PR 11, need D4 and D6.
- PR 11 also needs the live grant read, D8 and D11.
- PR 12 needs D7.

---

## 4. Ubiquitous language: `docs/architecture/feedback-ubiquitous-language.md` (lands in PR 1)

The file's first lines must name `feedback`
(`ci/fitness/code_quality/test_ubiquitous_language.py:72-78`).

- **Submission:** one raw report as received by Intake. It lives in the intake log, is purgeable,
  and is not a domain object.
- **Receipt:** what a 202 returns, a `submission_id`. It is not a ticket.
- **Relay:** a deployment's server-side sender. It owns the source key, stamps build provenance,
  and keeps the outbox.
- **Intake:** the public entry point that throttles, verifies, caps and appends. It never decides
  meaning.
- **Lane:** *signed*, *anonymous* (Turnstile) or *legacy* (imported).
- **Source:** an enrolled deployment holding a signing key. It is an aggregate. It is not a GitHub
  source or a session-inventory source.
- **Provenance:** key id, surface, server-stamped version/commit, and route. Unsigned means
  `anonymous`.
- **Screening / Screening Verdict:** the classifier pass, giving `clean`, `quarantine` or `spam`
  plus type, priority and confidence.
- **Disposition:** what the Screener decided for one submission: `open`, `report`,
  `exact_duplicate`, `quarantine`, `spam` or `failed`. It is persisted before any command.
- **Screened Text:** the normalised, capped, secret-shape-redacted text. It is the only text an
  agent may read. It is **not** a PII guarantee.
- **Ticket / Ticket Number (`FB-<n>`):** the aggregate built from one or more submissions. The
  number is unique within the hosting deployment and never reused.
- **Quarantine (feedback):** a ticket whose text no agent and no public surface may see until the
  owner releases it. It is not orchestration's Quarantine Ref
  (`docs/architecture/orchestration-ubiquitous-language.md:514`).
- **Report / Reporter Count:** a submission that is a member of a ticket. Membership is unique
  per submission.
- **Exact Duplicate:** the same content hash from the same scope inside the dedup window. It is
  not a Report.
- **Near Duplicate:** above the similarity threshold. It is a Report.
- **Recurrence:** a submission matching a closed or resolved ticket. It opens a new ticket that
  links to the old one.
- **Detach:** the owner's correction of an over-merge.
- **Fix Merged / Fix Observed / Fix Released / Resolved:** the #1628 facts.
  - **Fix Observed** is per source.
  - **Resolved** follows the Resolution Policy, released or all signed reporters observed, and
    names a version.
- **Digest / Quarantine Alert:** a batched owner summary, and a spike notice. Neither ever holds
  quarantined text.
- **Screening Benchmark:** the grouped train/validation/holdout suite used to choose a screener.

**Words not used here:**
- **Shipped**: orchestration's word.
- **Eval**: orchestration's aggregate. Use Screening Benchmark.
- **Feedback item**: the legacy lib/ui-feedback term. Use Ticket or Submission.
- **low/medium/high/critical**: use P0-P3. Legacy values map critical→P0, high→P1, medium→P2,
  low→P3.
- **Pause**: there is none here either.

**Unclear:** the platform clock this context wakes on is named `InventoryReconciliationSweep`. That
is a cross-context name used by string, following orchestration's precedent. A new issue is to be
opened in PR 1 to decide whether it becomes a neutral platform tick.

---

## 5. Rejected alternatives

1. **Extend lib/ui-feedback in place.** A synchronous model call at POST makes flood cost equal
   model cost. Rows are mutable and deletable
   (`lib/ui-feedback/backend/ui-feedback-api/src/ui_feedback/api/feedback.py:92-113`), and the
   library carries no identity.
2. **Intake as a mode of syn-api.** It would put a public flood surface on the single API process
   (`docs/north-star.md:127`).
3. **`SubmissionReceived` events as the queue.** Spam would live in the store forever, erasure
   would be impossible, and injection text would reach every stream consumer.
4. **Redis Streams as the queue.** It is not durable across a Redis restart. Postgres
   `SKIP LOCKED` with leases is.
5. **An LLM "sanitised summary" for agents.** That is model output conditioned on attacker text.
6. **Embeddings for near-dup detection.** A second model, a second cost, a second eval. Jaccard
   goes first, and the bench says whether it falls short.
7. **The browser signs, or holds a key.** Any visitor could then impersonate the deployment (B1).
8. **UUIDv5 ticket ids for idempotency.** That departed from the owner's UUIDv7 and still did not
   make reports idempotent (B2). The fix is a persisted disposition.
9. **A permanent unique `(source_id, content_hash)`.** Identical text would be a duplicate forever,
   even after resolution (I3).
10. **Ticket-number lookup open to anyone.** It would be an enumeration oracle (I4).
11. **Editing the frozen React app to migrate it.** ADR-073 freezes it. A shim plus deletion gating
    is used instead.

---

## 6. Risks

| Risk | Signal |
|---|---|
| False quarantine hides real bugs | quarantine rate per source per day. An owner release rate above the bench's holdout interval means the bench is unrepresentative |
| Screening cost or backlog runaway | unscreened depth and oldest age, screening calls per minute vs budget. Alarm on age > 15 min |
| Shared Postgres pressure from Intake | intake rows per minute vs the global budget. D1 can move `SYN_FEEDBACK_INTAKE_DB_URL` |
| Redis outage blocks all feedback | the Intake 503 rate. Accepted by design. The Relay outbox absorbs it |
| GitHub budget (filer, compare, PR re-reads, release list). `docs/north-star.md:120` treats 5,000 req/h as the conservative installation minimum | `X-RateLimit-Used` on feedback calls. Per-hour caps in settings |
| PII in public issues | structurally prevented by D11's default. A test with a secret + email in the comment (PR 11) |
| Two systems drift during PR 4-13 | after PR 8 the shim means one write path. Until PR 13, both `/feedback` and `/feedback/tickets` appear in OpenAPI |
| Clock skew rejects honest self-hosters | the 401 `stale_timestamp` rate per source |
| Over-merge of distinct bugs | the `TicketReportDetached` count |
| The React app's deletion slips, holding PR 13 | legacy routes still in OpenAPI. They only read history plus the shim |

**Maintenance cost:**
- two aggregates and about 15 events;
- one new container and one Relay;
- one worker, three PMs and one observer;
- one benchmark to keep current;
- Cloudflare rules outside the repo (D8).

Line counts are not estimated.

**Seams:**
- a new classifier is a setting plus a bench run;
- a new surface is a provenance value;
- a new link type is one event;
- a GitHub PR-grammar change touches only PullRequestLinker.

---

## 7. Verification (once built)

- `uv run pytest -m unit packages/syn-domain -q -k feedback`: aggregate guards, membership,
  resolution and PR lifecycle (PR 1-2).
- `uv run pytest ci/fitness/code_quality/test_ubiquitous_language.py -q`.
- `uv run pytest apps/syn-feedback-intake -q` (test stack): the PR 3 matrix, including the
  zero-DB and zero-verify counters.
- `uv run pytest apps/syn-api/tests -q -k "feedback and (relay or screener or agent_view or triage or fix)"`.
- Playwright: the PR 4 cross-origin forwarding run, and the PR 8 consumer journey.
- `just codegen`, then `check:api-drift`.
- `just preflight-agent` and `uv run pytest -m unit -q`.
- **Flood check** (`scripts/feedback_intake_flood.py`, manual, test stack). Send 20,000 requests in
  60 s, split across the anonymous lane, 200 enrolled sources, invalid source ids, bad signatures
  and invalid Turnstile tokens, while reading `GET /executions`. Assert:
  - syn-api p95 < 500 ms (`docs/north-star.md:19`);
  - appended rows ≤ the global budget;
  - verify calls ≤ the per-IP allowance;
  - DB queries from unknown ids = 0;
  - screening calls ≤ the per-minute budget.
- Mutation evidence: a `.mutations/*.patch` per negative control.

---

## 8. Out of scope

- Canny forwarding: the issue lists it only as an open question, and no integration exists.
- Cloudflare WAF, rate rules and Turnstile site configuration: owner-managed. This plan states the
  need.
- #856 for the React widget packages: it needs a CI job, which means a workflow change this
  workspace cannot push. PR 13 retires the backend half.
- Any change in agentic-workspace: this is domain meaning, not harness knowledge.

---

## 9. Needs a human decision

- **D1:** Is central the owner's VPS (sharing its Postgres) or a separate host? And does the intake
  log get its own DB? The code supports both via `SYN_FEEDBACK_INTAKE_DB_URL`.
- **D2:** HMAC shared secret (the owner's draft) or **Ed25519** (recommended: a leaked central DB
  cannot forge any source). **First on the critical path: PR 3 and PR 4 wait on it.**
- **D3:** Enrollment. Auto-enroll at a low quota, or hold for owner approval? And the value of
  `SYN_FEEDBACK_MAX_SOURCES`.
- **D4:** Where the real VPS benchmark cases live. A public repo would publish users' words.
- **D5:** Consent copy, including the external-model disclosure, and the privacy statement in
  `apps/syn-docs/content/`.
- **D6:** The benchmark bar. Suggested: false-quarantine ≤ 2% and injection catch ≥ 95% on
  holdout. That needs roughly 150 or more clean holdout cases (§2.10).
- **D7:** The Resolution Policy. Proposed: release, or all signed reporters observed.
- **D8:** The digest and quarantine-alert destination (private), and whether Cloudflare config is
  described in the repo.
- **D9:** Is there an anonymous lane in v1? Turnstile needs a web page, so it fits a docs or landing
  widget, not the CLI.
- **D10:** Media transport. Relay-forwarded (recommended) or presigned POST policy (the owner's
  draft wording)?
- **D11:** Publication policy. Proposed: public issues carry no free text, and text needs a
  per-ticket owner release.

---

## Review disposition

| finding | accepted / rejected | what changed |
|---|---|---|
| **B1** server-side signer and trust boundary | **Accepted** | New **Relay** in syn-api (§2.2, §2.3). It owns the key, ignores browser version/commit and stamps `get_build_info()` (`apps/syn-api/src/syn_api/build_info.py:95-108`), strips fields, keeps a durable outbox with a stable `client_submission_id`, and syncs status. The browser never contacts central, and status and media go through the Relay. New PR 4 with a cross-origin Playwright acceptance, a tampered-commit control and a key-not-in-assets check |
| **B2** idempotent submission processing | **Accepted** | §2.4 rewritten: a short-transaction lease (no transaction across the model call); the verdict persisted and reused; the disposition, ticket id **UUIDv7** and number persisted before dispatch; `AddReport` membership idempotent in the aggregate; per-bucket advisory lock with candidates read from the intake table, not a lagging projection; reconcile on `dispatched_at`. UUIDv5 and old D7 dropped. The PR 7 tests now cover each crash point, a changed verdict, and concurrency with a reporter-count assertion |
| **B3** lifecycle encodes its status rules | **Accepted** | Links carry the repository and its id. `TicketPullRequestStateChanged` covers open/closed/merged and is monotonic, with several PRs allowed. Per-source `TicketFixObserved` is monotonic. `TicketResolved(rule, version)` comes from a pure `ResolutionPolicy`, and release resolves every lane, fixing the earlier inconsistency. `TicketReportDetached` and `TicketReopened` added, so the over-merge risk has a real event. The policy is decision D7. The PR 1 and PR 12 tests cover the listed scenarios |
| **B4** migration removes routes still in use | **Accepted, with one part rejected** | §2.9 enumerates every consumer with `file:line`. The UI migration (PR 8) and the legacy POST shim come **before** the import (PR 9) and the orchestrator switch (PR 10). The import preserves status, notes, assignee and BYTEA media. **Rejected:** migrating the React app's HTTP contract. It is frozen and gets no new features (`docs/adrs/ADR-073-svelte-for-syn-ui.md:13`, `:22`), so it is not edited. Its writes go through the shim, and PR 13 is gated on its deletion. PR 13's acceptance is the consumer journey plus a caller grep, not DELETE absence |
| **B5** presigned upload not implemented | **Accepted** | §1 now records that `for_upload` is ignored and that the helper falls back to an unsigned URL (`packages/syn-adapters/src/syn_adapters/object_storage/minio.py:396`, `packages/syn-adapters/src/syn_adapters/object_storage/minio_helpers.py:304-308`). Media is keyed to the submission (pending-safe), with real-byte and magic validation, per-submission and global quotas, and an orphan sweep. The default transport is Relay-forwarded. If the owner keeps presigned (D10), PR 5 implements a POST policy, removes the unsigned fallback and adds finalise. PR 5 acceptance uses real MinIO |
| **B6** PM restart and delayed-work progress | **Accepted** | §2.6: durable to-do tables with `due_at`, and a subscription to the existing durable clock (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_quarantine/QuarantineNoticeProcessManager.py:66-82`). SourceGuard reads spam counts from the intake table on each tick (spam deliberately emits no event). The PR 11 tests cover restart against backlog, deadline-only progress, and replay with zero calls |
| **B7** safety gates deferred | **Accepted** | A hard global backlog/row/byte budget sheds **both** lanes. The per-IP bucket comes before parsing and verification. Unknown sources are rejected from cache. A separate failed-verification bucket. A Turnstile timeout. `SYN_FEEDBACK_MAX_SOURCES` and enrollment limits. `SYN_FEEDBACK_INTAKE_DB_URL` for the shared-Postgres concern (`docs/north-star.md:129`). The auto-filing gate requires an approved bench result, and PR 11 depends on D4 and D6. `ScreenedText` is explicitly not a PII control. Publication policy D11: no free text in public issues. External-model disclosure in the consent copy |
| **I1** citation reasoning and paths | **Accepted** | ADR-062 rule 3 restated as forbidding deep imports only. The feedback-owned port is now argued as design judgment. All citations are full root paths. North-star `:166` is described as a hypothesis |
| **I2** untouched final set | **Accepted** | Grouped train/validation/holdout. Selection on validation, holdout report-only (per `scripts/eval_suite.py:39-45`). Counts and Wilson intervals. The ~150-case size implication for D6. Recorded-response CI is labelled as scoring-only |
| **I3** exact-dedup lifetime and anonymous identity | **Accepted** | Retry idempotency is now `(scope, client_submission_id)`. Content exact-dedup happens at the Screener, inside a window setting, only against an open target. After resolution a match is a Recurrence. The anonymous scope is `ip_hash`, neither NULL nor a shared sentinel. Two users behind one deployment with identical text are an exact duplicate, a stated limitation |
| **I4** reporter contract and quarantine alerting | **Accepted** | Number lookup for signed sources that have a report on the ticket. Anonymous lookup by receipt capability that never reveals the verdict. 202 is defined as a receipt. Triage sends a text-free quarantine-spike alert to the D8 destination |
| **I5** negative controls proving the wrong property | **Accepted** | PR 4 has separate forwarding-gate and flag-gate mutations. PR 13 rewrites `apps/syn-api/tests/test_ui_feedback_feature_flag.py:178-179` on purpose. PR 10's grep is labelled a migration lint, with PR 7's agent-view test as the real control |
| **I6** speculative structure and scope | **Accepted** | LOC counts removed. Five PMs reduced to three plus one observer, by scheduling behaviour. The Relay is the single client-facing boundary, and `apps/syn-api/src/syn_api/services/ui_feedback.py` stays the one decision point. ADR-076 and the ADR-016 edit moved from PR 0 to PR 1, so PR 0 is the plan doc only |
| *(self-check)* PR events | **Corrected in this revision** | The earlier plan said PullRequestLinker consumes "the github context's PR events". The github public API exports none (`packages/syn-domain/src/syn_domain/contexts/github/__init__.py`, with no `PullRequest` symbol). It is now a pipeline observer after `apps/syn-api/src/syn_api/services/shipped_ledger.py:106-135`, plus a FixResolver tick re-read, because observers miss deduplicated and cold-start events (`packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py:72-77`) |
| *(self-check)* path collision | **Corrected in this revision** | Intake moved to `/intake/v1/`, so it cannot collide with the Relay's `/api/v1/feedback/submissions` on the central deployment |

## Readiness

Ready to implement PRs 0, 1, 2 and the synthetic part of PR 6 now. PR 3 onward is blocked on
**D2: HMAC shared secret or Ed25519 for source signing**, the first owner decision on the critical
path.

