# Test Deploy - putting the current code on a host

A **test deploy** moves the images you just built onto a host so you can look at
the thing running. It is not a release. It produces no git tag, no GitHub
Release entry, no npm publish, and no release notes, because there is no
audience for it other than you.

This exists because we stopped distinguishing the two. Seven `v0.28.0-beta.*`
prereleases were created on GitHub in roughly 48 hours, one per test deploy,
and none of them marked anything a reader would care about. The habit came
from [the release process doc](../release-process.md#published-beta-a-release-entry-with-an-audience),
whose Beta Release section says to run `gh release create` - correct for a beta
you are asking people to install, wrong for "put the current code on the VPS so
I can look at it", which is what actually happens most of the time.

Everything below was executed against the selfhost VPS on 2026-09-05 deploying
`v0.28.0-beta.9`, which created no GitHub Release. Two things went wrong on that
run. Both have a section here, because both were invisible until something else
broke.

Facts about the repository (recipe bodies, build args, status vocabularies) are
cited to the file that carries them and can be checked from a clone. Facts about
the host are operator-reported from that run, and every one of them has a
command here to re-derive it - run the command, do not trust the sample.

**Order matters.** Sections 2 to 4 are preparation and can take as long as they
take. Section 1 must be re-run immediately before any container is recreated
([section 5, step 3](#step-3-re-run-the-drain-check)), and section 5 is the only
one that touches the running host.

---

## 1. Drain check - first, last, and unskippable

**Never recreate containers while executions are in flight.** Doing it on an
earlier deploy orphaned two running executions: their containers were destroyed
mid-phase, and the work in them was not recoverable. The aggregate is still
consistent afterwards, so nothing in the system reports this as a failure. You
just lose the work.

Ask the API what statuses exist right now:

```bash
curl -su "admin:$PW" 'https://<host>/api/v1/executions?page_size=1' | jq '.status_counts'
```

Expected on a drained host is an object whose keys are **only** terminal
statuses. The counts are whatever your host's history happens to be; the key set
is the whole signal:

```json
{
  "completed": <n>,
  "failed": <n>,
  "cancelled": <n>
}
```

The terminal statuses are `completed`, `failed`, `cancelled` and `interrupted`.
**Any other key in that object means work is in flight.** Get the ids:

```bash
curl -su "admin:$PW" 'https://<host>/api/v1/executions?statuses=running,paused,not_started&page_size=100' \
  | jq '{total, rows: [.executions[] | {workflow_execution_id, status, workflow_name, started_at}]}'
```

Expected when drained:

```json
{ "total": 0, "rows": [] }
```

If it is not zero, **wait**, or cancel deliberately:

```bash
curl -su "admin:$PW" -X POST 'https://<host>/api/v1/executions/<id>/cancel' \
  -H 'Content-Type: application/json' -d '{"reason":"draining for test deploy"}'
```

Never deploy through a non-empty result. Waiting costs minutes; deploying
through it costs someone's phase.

### Why read `status_counts` rather than filtering the rows

The obvious form - fetch a page and filter it in `jq` - lies in two independent
ways, and the two combine into a confident empty result.

**It reads a page, not the collection.** `page_size=30` returns the 30 newest
executions. A `total` that describes the whole filtered collection was only made
truthful in #1119 and #1159; the rows never described it. `status_counts` is
tallied over every record matching the non-status filters *before* the status
filter is applied (`paginate()` in `packages/syn-domain/src/syn_domain/pagination.py`),
so one request with `page_size=1` answers for the whole store.

**A hand-written status list is an allowlist over a vocabulary you guessed.**
`pending` is not an execution status at all - it is a *phase* status
(`PhaseStatus` in `.../aggregate_execution/value_objects.py`), so a filter
containing it matches nothing and looks like it is doing work. The execution
statuses are `not_started`, `running`, `paused`, `completed`, `failed`,
`cancelled`, `interrupted`. Reading the counts object enumerates what is
actually there, so a status nobody thought of shows up instead of being
filtered out.

> **A `paused` execution reads as `running` on this surface.** The list
> projection (`WorkflowExecutionListProjection`, `workflow_executions` v6) has
> handlers for started, completed, failed, cancelled and interrupted, and none
> for paused - so pausing does not change the listed status. That errs safe for
> a drain check, which is the only reason it is a footnote here and not a bug
> report. Do not rely on it to *find* paused work.

### The trap: doing this too early

On the beta.9 deploy the drain check passed, then a new workflow was dispatched
minutes later while the build was still running, and it had to be cancelled at
deploy time. A drain check is a statement about one instant.

**Do the drain check last, immediately before you recreate containers
([section 5, step 3](#step-3-re-run-the-drain-check)), and do not dispatch work
while preparing a deploy.** If preparation takes an hour, the check you ran at
the start of it is worth nothing.

Until [PR #1181](https://github.com/syntropic137/syntropic137/pull/1181) lands
this is entirely manual - nothing refuses to deploy on your behalf.

---

## 2. Version bump

```bash
just bump-version 0.28.0-beta.9
```

Expected:

```
OK: all 15 version-carrying files at v0.28.0-beta.9
```

Read the count. Until #1224 the same command reported `OK: All 11 files` and
four generated files were left stale, which put an image on the host
advertising the previous version:

| Also carries the version | What was stale | Regenerated by |
|---|---|---|
| `uv.lock` | one record per workspace package | `just lock`, which `just bump-version` now runs for you |
| `schemas/plugin/phase-frontmatter.schema.json` | `$id` | `uv run python scripts/export_plugin_schemas.py` |
| `schemas/plugin/triggers.schema.json` | `$id` | same |
| `schemas/plugin/workflow.schema.json` | `$id` | same |

`just bump-version` now writes the schema `$id` values, regenerates `uv.lock`,
and re-runs `--check` itself, so a green result is evidence the bump is
complete rather than evidence that eleven of fifteen files agree. `just
check-version` re-runs the same check on demand.

**Regenerate; do not hand-edit.** `just preflight` and CI both re-derive these
and compare, so an edited-by-hand file that happens to read correctly still
fails the drift gate - and more to the point, a `$id` you typed is not evidence
of anything.

Only three of the five files in `schemas/plugin/` are generated. The exporter
stamps `$id` from the root `pyproject.toml` version, so those three follow the
bump automatically once you run it. `marketplace.schema.json` and
`plugin-manifest.schema.json` are not in `SCHEMA_REGISTRY` at all - the models
that produced them went away with `syn-cli`, so they are hand-maintained files
(see the `TODO` on `SCHEMA_REGISTRY` in `scripts/export_plugin_schemas.py`).
Their `$id` still reads `v0.18.0`. **That is not something a deploy fixes**,
running the exporter will not touch them, and hand-bumping them to make the set
look consistent would only make a stale schema advertise a version it was not
generated from.

> **A fresh worktree needs its submodules before either command works:**
>
> ```bash
> git submodule update --init --recursive
> ```
>
> Without it, both fail with `Distribution not found at .../agentic_logging` -
> `agentic-logging` is a path dependency into `lib/agentic-primitives`, so the
> directory does not exist until the submodule is checked out. The error names
> a Python distribution and says nothing about submodules, which is why it costs
> ten minutes the first time.

---

## 3. Build

Two paths. Neither requires `gh release create`.

### (a) Direct - simplest for one host of known architecture

No registry, no login, no tags to reconcile. **Both** tag-pinned images have to
move - [section 4](#4-which-images-actually-need-to-move) is where you confirm
it is exactly these two - so build both:

```bash
docker buildx build --platform linux/amd64 \
  --build-arg INCLUDE_DOCKER_CLI=1 \
  -t ghcr.io/syntropic137/syn-api:v0.28.0-beta.9 --load \
  -f infra/docker/images/syn-api/Dockerfile .

docker buildx build --platform linux/amd64 \
  -t ghcr.io/syntropic137/syn-gateway:v0.28.0-beta.9 --load \
  -f infra/docker/images/gateway/Dockerfile .
```

`syn-gateway` takes no `INCLUDE_DOCKER_CLI`: its Dockerfile
(`infra/docker/images/gateway/Dockerfile` - note the directory is `gateway`, not
`syn-gateway`) declares no such arg, and CI passes `0` for it. Only `syn-api`
needs it, for the reason in
[the #1216 trap](#how-this-lies-to-you-the-missing-docker-cli-1216).

Transfer both in one stream. `docker save` takes several images and writes their
shared layers once:

```bash
docker save \
  ghcr.io/syntropic137/syn-api:v0.28.0-beta.9 \
  ghcr.io/syntropic137/syn-gateway:v0.28.0-beta.9 \
  | ssh root@<host> 'docker load'
```

Expected tail from the `docker load` - **two** lines, one per image. One line
means one image never moved, and the deploy will be half old:

```
Loaded image: ghcr.io/syntropic137/syn-api:v0.28.0-beta.9
Loaded image: ghcr.io/syntropic137/syn-gateway:v0.28.0-beta.9
```

Those tags now exist **only in the host's docker daemon**. Nothing pushed them
anywhere. That is the point of this path, and it is why
[section 5, step 4](#step-4-recreate-branch-by-build-path) must not run
`docker compose pull` after it.

### (b) Registry - for reproducibility, or a host you cannot reach

```bash
just release-local 0.28.0-beta.9
```

Use this when someone else needs to pull the same bytes, or when the host pulls
rather than being pushed to. It builds all six core images
(`token-injector`, `sidecar-proxy`, `syn-collector`, `syn-dashboard-ui`,
`syn-api`, `syn-gateway`) for **`linux/amd64` and `linux/arm64`**. If the target
is a single known architecture, half of that build is discarded - which is most
of the wall-clock cost of the recipe.

It also does not pass build args. See below.

### How this lies to you: the missing docker CLI (#1216)

**This is the section that broke the beta.9 deploy.**

`infra/docker/images/syn-api/Dockerfile:70` declares `ARG INCLUDE_DOCKER_CLI=0`.
CI overrides it - `.github/workflows/release-containers.yaml` sets it to `1` for
`syn-api` and `0` for everything else. `just release-local` passes no
`--build-arg` at all, so a locally built `syn-api` takes the default and ships
**with no docker CLI**.

The API needs that binary to resolve workspace images before creating a
workspace. Without it, every workflow execution fails at bootstrap:

```
Cannot resolve local workspace image 'omni-fable51:2.1.258': docker was not found on PATH.
```

(`_resolve_local_image_id()` in
`packages/syn-adapters/src/syn_adapters/workspace_backends/image_verification.py:203`.)

**Nothing surfaces this until a workflow is dispatched.** The container starts.
`/health` reports healthy. The dashboard loads. Every list endpoint returns
correct data. Executions, sessions, costs, insights - all fine, because none of
them create a workspace. The defect is confined to the one code path no
smoke check exercises, so a deploy can be declared good and stay broken until
the next person dispatches something.

Until [#1216](https://github.com/syntropic137/syntropic137/issues/1216) is
fixed, a local `syn-api` build **must** pass the arg:

```bash
docker buildx build --platform linux/amd64 \
  --build-arg INCLUDE_DOCKER_CLI=1 \
  -f infra/docker/images/syn-api/Dockerfile \
  -t ghcr.io/syntropic137/syn-api:v0.28.0-beta.9 --push .
```

Path (a) already passes it. Path (b) cannot - `just release-local` passes no
build args at all - so after `release-local`, rebuild and re-push `syn-api` with
the command above. The other five images take `INCLUDE_DOCKER_CLI=0` in CI too,
so for them `release-local` matches CI.

**On path (b), that rebuild must be the last thing that writes the `v`-prefixed
`syn-api` tag.** It pushes `v0.28.0-beta.9` directly, so `syn-api` needs no
retag in [section 4](#the-tag-convention-does-not-match) - and running one there
afterwards copies the argless `release-local` manifest back over this tag,
restoring the exact defect this section is about. Retag `syn-gateway` only.

Note the platform: this command builds `linux/amd64` only, and pushing it
replaces the multi-arch index `release-local` published for that tag. That is
fine for the single known-architecture host a test deploy targets; build
`linux/arm64` instead if that is what the host is.

The verification for this is in
[section 5, step 5](#step-5-verify-the-deploy-took) and it is one line. Run it
every time.

---

## 4. Which images actually need to move

Fewer than you think. **Read the compose file that is actually deployed** - not
the template in this repo, which uses `${SYN_VERSION:-latest}` uniformly for all
six `ghcr.io/syntropic137/*` services and tells you nothing about what the host
has been pinned to since:

```bash
ssh root@<host> "grep -E '^\s+image:' /root/.syntropic137/docker-compose.syntropic137.yaml | sort -u"
```

Run on the VPS before the beta.9 deploy, the operator reported only two pinned
by **tag**, and both still on the version then deployed - beta.8, not the one
being deployed (digests elided):

```
    image: ghcr.io/syntropic137/syn-api:v0.28.0-beta.8
    image: ghcr.io/syntropic137/syn-gateway:v0.28.0-beta.8
    image: ghcr.io/syntropic137/event-store@sha256:...
    image: ghcr.io/syntropic137/sidecar-proxy@sha256:...
    image: ghcr.io/syntropic137/syn-collector@sha256:...
    image: ghcr.io/syntropic137/token-injector@sha256:...
```

**Write down the tag you see.** It is the currently deployed version, and
[section 5, step 2](#step-2-repoint-the-tag-pins-to-the-new-version) needs it
twice: to name the backup, and as the string it replaces.

A **digest**-pinned service does not move when you change `SYN_VERSION`, by
definition - the reference names content, not a version. So only `syn-api` and
`syn-gateway` need building and only those two lines need editing. Building the
other four is wasted time, and *expecting* them to have changed is how you end
up debugging a service that was never redeployed.

Check this every time rather than trusting the list above: which services are on
digests is a property of the deployed file, which the release pipeline rewrites
and operators subsequently hand-edit.

### The tag convention does not match

The compose uses **`v`-prefixed** tags (`v0.28.0-beta.9`), because that is what
`docker/metadata-action` produces in CI. `just release-local 0.28.0-beta.9`
pushes the **bare** form (`0.28.0-beta.9`) - the recipe interpolates
`{{version}}` with no prefixing logic. Pulling then 404s.

Retag rather than rebuild - **`syn-gateway` only**:

```bash
just release-retag syn-gateway 0.28.0-beta.9 v0.28.0-beta.9
```

It calls `docker buildx imagetools create`, which copies the manifest
server-side: no pull, no rebuild, and the multi-arch index survives.

`syn-api` is deliberately absent. Its `v`-prefixed tag was already pushed by the
`INCLUDE_DOCKER_CLI=1` rebuild in
[section 3](#how-this-lies-to-you-the-missing-docker-cli-1216), and retagging it
from the bare `release-local` tag would copy the argless manifest over that -
reintroducing #1216, which step 5 then catches after the deploy, one round trip
too late.

None of this applies to the direct path (3a). It never touches a registry, so
the tags are whatever you passed to `-t`: write them `v`-prefixed there and
there is nothing to reconcile.

---

## 5. Update, recreate, and verify

Five steps, in this order. Steps 1 and 2 do not touch a running container;
step 4 does, which is why the drain check sits immediately before it and not at
the top.

### Step 1. Back up the deployed compose

It carries hand-applied digest pins that exist nowhere else - not in this repo,
not in the release assets. Name the backup after the tag it still contains, so
whoever reaches for it later can tell what rolling back to it would get them:

```bash
ssh root@<host> 'cd /root/.syntropic137 \
  && cp docker-compose.syntropic137.yaml docker-compose.syntropic137.yaml.bak-beta8'
```

### Step 2. Repoint the tag pins to the new version

**This is the step whose absence makes a deploy do nothing.** `up -d` recreates
a container from whatever the compose file names. If the file still names the
old tag, Compose recreates the old image, reports success, and every check that
watches only container state agrees with it.

Replace both tags. The old one is what you read in
[section 4](#4-which-images-actually-need-to-move):

```bash
ssh root@<host> 'cd /root/.syntropic137 \
  && sed -i "s#syn-api:v0.28.0-beta.8#syn-api:v0.28.0-beta.9#; \
             s#syn-gateway:v0.28.0-beta.8#syn-gateway:v0.28.0-beta.9#" \
       docker-compose.syntropic137.yaml'
```

Then verify with two counts, not one:

```bash
ssh root@<host> "grep -c 'v0.28.0-beta.8' /root/.syntropic137/docker-compose.syntropic137.yaml"
ssh root@<host> "grep -c 'v0.28.0-beta.9' /root/.syntropic137/docker-compose.syntropic137.yaml"
```

```
0
2
```

Both matter. `0` old on its own is also what a `sed` that wrote a **typo'd** new
tag produces; `2` new on its own is also what an already-current file produces
when `sed` matched nothing. Together they say the two lines you meant to change
are the two lines that changed.

Run them as separate commands: **`grep -c` exits non-zero when the count is
`0`**, so chaining the first with `&&` aborts on exactly the answer you wanted.

If the deployed file pins with `${SYN_VERSION}` rather than a literal tag - the
form the repo template ships - there is nothing to `sed`. Set `SYN_VERSION` in
`/root/.syntropic137/.env` instead, and check it with
`docker compose -f docker-compose.syntropic137.yaml config | grep image:`, which
prints the resolved values.

### Step 3. Re-run the drain check

[Section 1](#1-drain-check---first-last-and-unskippable), in full, now - not the
result you got before you started building. Nothing below step 3 is reversible
for an execution that is mid-phase.

### Step 4. Recreate (branch by build path)

**The command depends on which path you built with in [section 3](#3-build).**
This is not a style choice: the wrong one either fails outright or deploys bytes
other than the ones you built.

`api` and `gateway` below are **service** names. The images are called `syn-api`
and `syn-gateway`; `docker compose pull` and `up` take services, and given an
image name they exit with `no such service`.

**Registry path (3b) - pull, then up:**

```bash
ssh root@<host> 'cd /root/.syntropic137 \
  && docker compose -f docker-compose.syntropic137.yaml pull api gateway \
  && docker compose -f docker-compose.syntropic137.yaml up -d api gateway'
```

**Direct path (3a) - up only. Do not pull.**

First confirm the `docker load` from 3(a) actually landed. Expect two lines:

```bash
ssh root@<host> "docker images --format '{{.Repository}}:{{.Tag}}' | grep 'v0.28.0-beta.9'"
```

```
ghcr.io/syntropic137/syn-api:v0.28.0-beta.9
ghcr.io/syntropic137/syn-gateway:v0.28.0-beta.9
```

One line means one image never transferred, and `up -d` is about to fail on the
other with a pull it cannot satisfy. Then:

```bash
ssh root@<host> 'cd /root/.syntropic137 \
  && docker compose -f docker-compose.syntropic137.yaml up -d api gateway'
```

`docker save`/`docker load` already put those images in the host's daemon, and
Compose's default pull policy is `missing` - it uses a local image when one is
present - so `up -d` alone deploys exactly the bytes you transferred. Adding a
`pull` does one of two things, both bad. Either the tag is not in GHCR, `pull`
fails, and the `&&` means `up` never runs at all, so nothing deploys; or a tag
by that name **is** in GHCR from some earlier build, `pull` overwrites your
image with it, and the deploy succeeds loudly while running code you did not
build.

### Step 5. Verify the deploy took

"It looks right" is not a check. Three things, in this order.

**1. The containers are running the images you think they are.** Both of them:

```bash
ssh root@<host> "docker inspect syn137-api syn137-gateway --format '{{.Name}} {{.Config.Image}}'"
```

```
/syn137-api ghcr.io/syntropic137/syn-api:v0.28.0-beta.9
/syn137-gateway ghcr.io/syntropic137/syn-gateway:v0.28.0-beta.9
```

A stale answer means step 2 did not take, or `up -d` found nothing to change.
Checking only `syn137-api` is how a half-deploy passes: the gateway is the image
the browser actually talks to.

**2. The docker CLI is present** - this is the guard against
[the #1216 trap](#how-this-lies-to-you-the-missing-docker-cli-1216):

```bash
ssh root@<host> "docker exec syn137-api sh -c 'command -v docker'"
```

```
/usr/local/bin/docker
```

Empty output with a non-zero exit is the failure. Every execution will fail at
bootstrap; rebuild with `--build-arg INCLUDE_DOCKER_CLI=1` and redeploy.

**3. Dispatch one real workflow and confirm it gets past bootstrap.**

This is the step that would have caught the beta.9 failure, and nothing cheaper
substitutes for it. A healthy `/health` is not evidence that executions can run
- on the broken beta.9 build `/health` was healthy for the entire time every
execution was failing.

```bash
syn workflow run <a-short-workflow> --repo <org>/<repo>
curl -su "admin:$PW" 'https://<host>/api/v1/executions/<id>' \
  | jq '{status, error_message, phases: [.phases[] | {name, status}]}'
```

**Watch a PHASE reach `running`, not the execution.** The execution goes to
`running` the instant it is accepted, before any workspace exists, so this is
green during exactly the window in which the #1216 build is about to fail:

```json
{
  "status": "running",
  "error_message": null,
  "phases": [{ "name": "<phase>", "status": "running" }]
}
```

A phase only reaches `running` after the workspace was created, which is the
step that needs the docker CLI. Poll until a phase says `running` or the
execution says `failed`; do not stop at the first response.

The failure looks like this, and arrives quickly:

```json
{
  "status": "failed",
  "error_message": "Cannot resolve local workspace image '...': docker was not found on PATH.",
  "phases": [{ "name": "<phase>", "status": "failed" }]
}
```

A `404` on an execution that was just dispatched is probably
[section 6](#6-the-projection-rebuild-window), not a failure - check that before
concluding anything.

Only after a phase reaches `running` is the deploy good.

---

## 6. The projection rebuild window

A version change can bump projection versions, which clears those projections
and restarts the single shared subscription from global nonce 0. While it
replays, **no** projection advances, and freshly dispatched executions can 404
from the API despite running perfectly.

This is already documented, including how to watch
`GET /api/v1/health` -> `subscription.status`, and what not to conclude from a
404 during the window. Read it there rather than here:
[v0.28.0 Rollout Constraints -> The projection rebuild window](../release-process.md#the-projection-rebuild-window).

> **That section is marked for deletion once v0.28.0 ships**, and it is where
> this mechanism is written down. The mechanism is not release-specific - any
> deploy that changes a projection's `VERSION` constant opens the same window -
> so whoever deletes it needs to move the "how to watch it" part somewhere
> durable rather than dropping it. This link is one of the things that will
> break when they do.

**The window is not guaranteed to appear.** beta.8 -> beta.9 triggered no
rebuild at all: the v0.28.0 projection version bumps are relative to v0.27, and
beta.8 already carried them, so beta.9 changed no projection version. A deploy
that skips the window proves nothing about the next one - the trigger is a
changed `VERSION` constant, not a changed release number.

---

## 7. Validation

For the read-path checks after the stack is up - counts, time windows, and
pagination across the list surfaces - use
[section 8.1 of the release validation runbook](../testing/release-validation.md#81-list-surfaces---counts-time-windows-and-pagination).
Those checks apply unchanged to a test deploy; they are not restated here.

Note what a test deploy does **not** need from that runbook: sections that
validate published release artifacts (GHCR release digests, the npm package, the
GitHub Release itself) have no subject here, because a test deploy publishes
none of them.
