#!/usr/bin/env bash
# Upgrade rehearsal: replay a production event-store backup through the
# release a stack runs today, upgrade it in place to a candidate, and check
# that nothing was lost. Runs entirely on this machine; never touches a VPS.
#
# Usage:
#   scripts/rehearse_upgrade.sh --dump <events.dump> [options]
#
#   --dump PATH            pg_dump -Fc of the `events` table (required)
#   --from TAG             released version the stack runs today (default v0.33.1).
#                          Uses that GitHub Release's digest-pinned compose asset.
#   --to-ref REF           candidate ref (default origin/main). Its published
#                          compose file and entrypoint are used.
#   --to-api-image IMG     candidate syn-api image (default: build from --to-ref)
#   --to-collector-image IMG  candidate syn-collector image (default: build)
#   --to-event-store IMG   candidate event store image (default: the --to-ref
#                          compose's own pin, which is :latest when unpinned)
#   --port N               host port for the API (default 38000)
#   --timeout SECONDS      max wait for each catch-up (default 3600)
#   --workdir DIR          working dir; must NOT exist yet (default: mktemp)
#   --keep                 leave the stack up at the end (default: tear down)
#   --verify-only          re-run only the verify step on --workdir's saved out/.
#                          Reads files only: no docker, no compose, no writes
#                          outside out/.
#
# Safe by construction: it refuses to start unless every property below holds,
# rather than trusting the caller to pass safe flags.
#   - Docker target: DOCKER_CONTEXT must be unset, DOCKER_HOST unset or a unix
#     socket, and the selected context's endpoint a local unix socket. That
#     endpoint is pinned for every later docker call.
#   - Project: generated (syn137rehearse-<UTC timestamp>-<pid>), never a flag.
#     It refuses if any container, volume or network whose name starts with
#     syn137rehearse- already exists. Each version's compose is rendered in a
#     staging dir and validated there before it replaces the active config: it
#     must name no volume, network or container outside the generated project,
#     bind-mount nothing outside the workdir, use no external or driver_opts
#     volume, no host namespace and no privileged service.
#   - Credentials: compose runs under `env -i`, so no host variable reaches
#     interpolation or a `KEY: null` passthrough; every credential the API or
#     collector reads is set to "" and 1Password tokens with them. The created
#     containers' env is checked (names only) before restore and again once
#     running. No docker socket is reachable from inside the stack, so a
#     restored queued execution can never start an agent.
#   - 1Password: APP_ENVIRONMENT stays selfhost (durable stores), so the
#     resolver would run; instead `op` is shadowed in the API and collector by
#     a stub that always fails, and each image's own op_available() is probed
#     in a one-off container before anything starts. A version whose resolver
#     cannot be shown disabled is refused.
#   - Workdir: created fresh; an existing path (file, dir or symlink) is refused.
#   - Cleanup: an EXIT trap removes the git worktree and only its own
#     registration, then containers, networks and volumes by explicit name, each
#     carrying the generated project prefix. Teardown never runs compose, so no
#     compose file (validated or not) decides what is deleted.
#
# Exit status: 0 PASS, 1 FAIL (lost rows, mismatch, held/halted projection,
# timeout), 2 usage, 3 refused (a safety property did not hold).
set -euo pipefail
export LC_ALL=C  # sort and join must agree on collation

DUMP=""; FROM="v0.33.1"; TO_REF="origin/main"
TO_API=""; TO_COLLECTOR=""; TO_ES=""; TO_SHA="(verify-only)"
PORT=38000; TIMEOUT=3600; WORK=""; KEEP=0; VERIFY_ONLY=0
usage() { sed -n '2,46p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
refuse() { echo "REFUSED: $*" >&2; exit 3; }
while [ $# -gt 0 ]; do
    case "$1" in
        --dump) DUMP="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --to-ref) TO_REF="$2"; shift 2 ;;
        --to-api-image) TO_API="$2"; shift 2 ;;
        --to-collector-image) TO_COLLECTOR="$2"; shift 2 ;;
        --to-event-store) TO_ES="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        --workdir) WORK="$2"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --verify-only) VERIFY_ONLY=1; KEEP=1; shift ;;
        *) usage ;;
    esac
done
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
T0=$(date +%s)
step() { printf '\n==> [%s +%ss] %s\n' "$(date -u +%H:%M:%SZ)" "$(( $(date +%s) - T0 ))" "$*"; }

if [ "$VERIFY_ONLY" = 1 ]; then
    [ -n "$WORK" ] && [ -d "$WORK/out/from" ] && [ -d "$WORK/out/to" ] || { echo "--verify-only needs --workdir with out/from and out/to" >&2; exit 2; }
    WORK="$(cd "$WORK" && pwd -P)"
else
[ -f "$DUMP" ] || { echo "--dump file not found: $DUMP" >&2; usage; }
for bin in docker gh jq curl git openssl; do command -v "$bin" >/dev/null || { echo "missing $bin" >&2; exit 2; }; done
DUMP="$(cd "$(dirname "$DUMP")" && pwd)/$(basename "$DUMP")"

# --- guard: local Docker daemon only ------------------------------------------
[ -z "${DOCKER_CONTEXT:-}" ] || refuse "DOCKER_CONTEXT is set; unset it so only the local default context is used"  # guard:docker-context-env
case "${DOCKER_HOST:-}" in ""|unix://*) ;; *) refuse "DOCKER_HOST is not a local unix socket" ;; esac  # guard:docker-host-env
CONTEXT_ENDPOINT="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker context inspect --format '{{.Endpoints.docker.Host}}')"
case "$CONTEXT_ENDPOINT" in unix://*) ;; *) refuse "the selected docker context's endpoint is not a local unix socket" ;; esac  # guard:docker-context-endpoint
DOCKER_ENDPOINT="${DOCKER_HOST:-$CONTEXT_ENDPOINT}"
# Every docker call: pinned local endpoint, and no other host variable.
dk() { env -i PATH="$PATH" HOME="$HOME" DOCKER_HOST="$DOCKER_ENDPOINT" docker "$@"; }
timeout 20 env -i PATH="$PATH" HOME="$HOME" DOCKER_HOST="$DOCKER_ENDPOINT" docker info >/dev/null || { echo "docker daemon not reachable" >&2; exit 2; }

# --- guard: a project that cannot be anyone else's ----------------------------
PREFIX="syn137rehearse-"
PROJECT="${PREFIX}$(date -u +%Y%m%dt%H%M%S)-$$"
case "$PROJECT" in syn|syn137|syntropic137|syn-rehearsal) refuse "project $PROJECT is reserved" ;; "$PREFIX"*) ;; *) refuse "project $PROJECT lacks the $PREFIX prefix" ;; esac
# Each listing must succeed: a failed one proves nothing about the namespace.
containers="$(dk ps -a --format '{{.Names}}')" || refuse "could not list docker containers; the ${PREFIX}* namespace is unproven"  # guard:inventory-containers
volumes="$(dk volume ls --format '{{.Name}}')" || refuse "could not list docker volumes; the ${PREFIX}* namespace is unproven"  # guard:inventory-volumes
networks="$(dk network ls --format '{{.Name}}')" || refuse "could not list docker networks; the ${PREFIX}* namespace is unproven"  # guard:inventory-networks
existing="$(printf '%s\n%s\n%s\n' "$containers" "$volumes" "$networks" | grep "^${PREFIX}" || true)"
[ -z "$existing" ] || refuse "docker resources named ${PREFIX}* already exist (an earlier rehearsal?): $(echo $existing)"  # guard:existing-resources

# --- guard: a fresh workdir ---------------------------------------------------
if [ -n "$WORK" ]; then
    [ ! -e "$WORK" ] && [ ! -L "$WORK" ] || refuse "--workdir $WORK already exists; give a path that does not"  # guard:fresh-workdir
    mkdir "$WORK"  # no -p: fails rather than adopt a directory created meanwhile
else
    WORK="$(mktemp -d -t syn-rehearsal.XXXXXX)"
fi
WORK="$(cd "$WORK" && pwd -P)"; cd "$WORK"
fi  # VERIFY_ONLY (guards)

OUT="$WORK/out"; mkdir -p "$OUT"
API="http://127.0.0.1:${PORT}"
FAIL=0; fail() { echo "FAIL: $*" | tee -a "$OUT/failures.txt"; FAIL=1; }
# Compose against the config in dir $1. Relative paths always resolve against
# $WORK, so a staged config renders exactly as it will run once promoted.
dcin() { local d="$1"; shift; dk compose -p "$PROJECT" --project-directory "$WORK" --env-file "$WORK/.env" -f "$d/docker-compose.syntropic137.yaml" -f "$d/override.yaml" "$@"; }
dc() { dcin "$WORK" "$@"; }  # the active config: only ever a validated one
psql_q() { dc exec -T timescaledb psql -U syn -d syn -tAc "$1"; }

SRC=""; COMPOSE_USED=0

# The one place anything docker is deleted. A name is ours only if it carries
# this run's generated project and a separator: the namespace guard proved no
# such name existed before this run.
rm_owned() {  # $1 container|volume|network, $2 name
    case "$2" in "${PROJECT}-"*|"${PROJECT}_"*) ;; *) echo "teardown: not deleting $1 $2 (not this rehearsal's)" >&2; return 0 ;; esac  # owned-delete
    case "$1" in
        container) dk rm -f -v "$2" >/dev/null || true ;;  # -v: anonymous volumes only
        volume|network) dk "$1" rm "$2" >/dev/null || true ;;
    esac
}
owned_names() {  # $1 container|volume|network -> names carrying this run's project
    case "$1" in container) dk ps -a --format '{{.Names}}' ;; *) dk "$1" ls --format '{{.Name}}' ;; esac \
        | grep -E "^${PROJECT}[-_]" || true
}
# Removes this run's worktree directory and its own registration only (no
# global `worktree prune`, which would drop other worktrees' registrations).
forget_worktree() {
    local common d
    [ "$SRC" = "$WORK/src" ] || return 0
    git -C "$REPO" worktree remove --force "$SRC" >/dev/null 2>&1 && return 0
    rm -rf "$WORK/src"
    common="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)" || return 0
    for d in "$common"/worktrees/*/; do
        [ "$(cat "${d}gitdir" 2>/dev/null)" = "$WORK/src/.git" ] && rm -rf "${d%/}"
    done
    return 0
}
cleanup() {
    local rc=$? kind name
    trap - EXIT
    if [ -n "$SRC" ]; then forget_worktree; fi
    if [ "$COMPOSE_USED" = 1 ] && [ "$KEEP" = 1 ]; then echo "stack kept: remove every container, network and volume named ${PROJECT}-* / ${PROJECT}_* when done"
    elif [ "$COMPOSE_USED" = 1 ]; then
        step "tear down $PROJECT"
        # By explicit name, never `compose down`: compose would delete whatever
        # the current compose file names, validated or not.
        for kind in container network volume; do
            for name in $(owned_names "$kind"); do rm_owned "$kind" "$name"; done  # teardown:by-name
        done
    fi
    exit "$rc"
}
[ "$VERIFY_ONLY" = 1 ] || trap cleanup EXIT

# Credentials the published compose forwards from the host (`KEY: null` or
# `${KEY:-}`). Each is pinned to "" in the override; compose itself runs under
# env -i, so none can be interpolated from the caller's shell either.
CRED_VARS="ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN CODEX_AUTH_JSON OPENAI_API_KEY
 SYN_GIT_TOKEN GH_TOKEN GITHUB_TOKEN SYN_GITHUB_APP_ID SYN_GITHUB_APP_NAME SYN_GITHUB_WEBHOOK_SECRET
 SYN_GITHUB_PRIVATE_KEY SYN_SESSION_STORE_URL SYN_SESSION_STORE_AUTH_TOKEN SYN_SESSION_STORE_READ_TOKEN
 SYN_SESSION_INVENTORY_REPLICATION_STORE_URL SYN_SESSION_INVENTORY_REPLICATION_WRITE_TOKEN
 SYN_SESSION_INVENTORY_CAPTURE_WRITE_TOKEN SYN_WORKSPACE_CLOUD_API_KEY S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY
 COLLECTOR_API_KEY SYN_DISK_PAGE_WEBHOOK_URL OP_SERVICE_ACCOUNT_TOKEN OP_SERVICE_ACCOUNT_TOKEN_SYNTROPIC137
 OP_SERVICE_ACCOUNT_TOKEN_SYN137_DEV OP_SERVICE_ACCOUNT_TOKEN_SYN137_BETA OP_SERVICE_ACCOUNT_TOKEN_SYN137_STAGING
 OP_SERVICE_ACCOUNT_TOKEN_SYN137_PROD OP_CONNECT_TOKEN OP_CONNECT_HOST OP_SESSION"
# Names that are a credential when non-empty, whatever the compose calls them.
CRED_RE="^(OP_[A-Z0-9_]*|[A-Z0-9_]*(_TOKEN|_API_KEY|_SECRET|_SECRET_KEY|_PRIVATE_KEY|_AUTH_JSON)|$(echo $CRED_VARS | tr ' ' '|')|DOCKER_HOST)$"

# Abort if any service container carries a non-empty credential or a docker
# host. Prints variable names only, never values.
check_container_env() {  # $1 label
    local svc cid env leaked=""
    for svc in api collector; do
        cid="$(dc ps -a -q "$svc")"
        [ -n "$cid" ] || refuse "$1: no $svc container to inspect"
        env="$(dk inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$cid")"
        grep -qx 'APP_ENVIRONMENT=selfhost' <<<"$env" || refuse "$1: $svc is not APP_ENVIRONMENT=selfhost, so it would not use durable stores"  # guard:durable-env
        leaked="$leaked $(printf '%s\n' "$env" \
            | awk -F= -v re="$CRED_RE" 'NF && $1 ~ re && substr($0, length($1) + 2) != "" {print svc ":" $1}' svc="$svc" | tr '\n' ' ')"
    done
    [ -z "${leaked// /}" ] || refuse "$1: credentials present in rehearsal containers:$leaked"  # guard:container-credentials
}

# `op` inside the rehearsal: always fails, so op_available() is False even
# when a cached login would make `op whoami` succeed.
write_op_stub() {
    mkdir -p "$WORK/rehearsal-bin"
    printf '#!/bin/sh\necho "op is disabled in an upgrade rehearsal" >&2\nexit 1\n' > "$WORK/rehearsal-bin/op"
    cat > "$WORK/rehearsal-bin/op-probe.py" <<'PY'
import shutil
try:
    from syn_shared.settings import op_resolver  # noqa: F401
except ImportError:
    op_resolver = None
try:
    from syn_shared.settings.op_client import op_available
except ImportError:
    op_available = None
found = shutil.which("op")
if op_resolver is not None and op_available is None:
    print("op-unknown: this image resolves 1Password but has no op_available() to probe")
elif found not in (None, "/rehearsal-bin/op") or (op_available is not None and op_available()):
    print(f"op-reachable: {found}")
else:
    print("op-disabled")
PY
    chmod 755 "$WORK/rehearsal-bin/op"
}

# Run each image's own op_available() in a one-off container with the
# service's env and mounts, before the service itself ever starts.
check_op_disabled() {  # $1 label
    local svc said
    for svc in api collector; do
        said="$(dc run --rm --no-deps -T --entrypoint python "$svc" /rehearsal-bin/op-probe.py 2>/dev/null | tail -n1)" || said="probe failed"
        [ "$said" = op-disabled ] || refuse "$1: 1Password resolution is not disabled in $svc ($said)"  # guard:op-disabled
    done
}

# The config staged in dir $1 must name nothing outside this project, touch no
# host path outside $WORK and mount no docker socket; a new pinned name or
# mount in a future compose file is caught here, before it is ever active.
check_rendered() {  # $1 staging dir
    local cfg foreign
    cfg="$(dcin "$1" config --format json)" || refuse "compose could not render the staged config"
    foreign="$(jq -r --arg p "^${PROJECT}[-_]" '[(.volumes // {} | .[] | .name), (.networks // {} | .[] | .name), (.services[] | .container_name // empty)] | .[] | select(test($p) | not)' <<<"$cfg")"
    [ -z "$foreign" ] || refuse "compose names resources outside $PROJECT: $(echo $foreign)"  # guard:rendered-names
    ! jq -e '[.services[] | .volumes // [] | .[] | (.source // "")] | any(test("docker\\.sock"))' <<<"$cfg" >/dev/null || refuse "a service mounts a docker socket"  # guard:docker-socket-mount
    foreign="$(jq -r --arg w "$WORK/" '[(.services[] | .volumes // [] | .[] | select(.type == "bind" or (.type | IN("volume", "tmpfs") | not)) | .source // "?"), ((.secrets // {}), (.configs // {}) | .[] | .file // empty)] | .[] | select(startswith($w) | not)' <<<"$cfg")"
    [ -z "$foreign" ] || refuse "compose mounts host paths outside $WORK: $(echo $foreign)"  # guard:host-paths
    foreign="$(jq -r '(.volumes // {} | to_entries[] | select(.value.external or .value.driver_opts != null or ((.value.driver // "local") != "local")) | "volume:" + .key), (.services | to_entries[] | select(.value.privileged or ([.value.network_mode, .value.pid, .value.ipc, .value.userns_mode] | any(. == "host")) or (.value.volumes_from != null)) | "service:" + .key)' <<<"$cfg")"
    [ -z "$foreign" ] || refuse "compose uses host-backed volumes or host namespaces: $(echo $foreign)"  # guard:host-backed
}

# --- override: isolation, names, prod-like limits ---------------------------
# python:3.12-slim's PATH behind the venv, with the `op` stub in front.
REHEARSAL_PATH="/rehearsal-bin:/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
blank_credentials() {  # every credential "", no docker host, no usable `op`
    echo "    volumes:"
    echo "      - \"$WORK/rehearsal-bin:/rehearsal-bin:ro\""
    echo "      - \"$WORK/rehearsal-bin/op:/usr/local/bin/op:ro\""
    echo "    environment:"
    echo "      APP_ENVIRONMENT: selfhost  # durable stores; test/offline would be in-memory"
    echo "      PATH: \"$REHEARSAL_PATH\""  # guard:op-shadow
    echo "      DOCKER_HOST: \"\""
    for v in $CRED_VARS; do echo "      ${v}: \"\""; done
}
write_override() {  # $1 out dir, $2 api image, $3 collector image, $4 event-store image ("" = keep)
    local out="$1"; shift
    {
        echo "services:"
        for s in timescaledb event-store collector api gateway minio redis envoy-proxy token-injector cloudflared; do
            echo "  ${s}:"
            echo "    container_name: ${PROJECT}-${s}"
            case "$s" in
                api) echo "    ports: !override [\"127.0.0.1:${PORT}:8000\"]"; [ -n "$1" ] && echo "    image: $1"; blank_credentials ;;
                collector) [ -n "$2" ] && echo "    image: $2"; blank_credentials ;;
                event-store) [ -n "$3" ] && echo "    image: $3" ;;
                gateway|cloudflared|envoy-proxy|token-injector) echo "    profiles: [\"rehearsal-disabled\"]" ;;
            esac
        done
        cat <<'EOF'
  docker-socket-proxy:
    container_name: PROJECT-docker-socket-proxy
    image: alpine:3.20
    entrypoint: !override ["sleep", "infinity"]
    command: !reset []
    volumes: !reset []
    environment: !reset {}
volumes:
  db_data: {name: PROJECT_db_data}
  api_logs: {name: PROJECT_api_logs}
  minio_data: {name: PROJECT_minio_data}
  redis_data: {name: PROJECT_redis_data}
networks:
  syn-internal: {name: PROJECT_internal}
EOF
    } | sed "s/PROJECT/${PROJECT}/g" > "$out/override.yaml"
}

if [ "$VERIFY_ONLY" = 0 ]; then
# --- prepare ----------------------------------------------------------------
step "prepare $WORK (from $FROM, to $TO_REF)"
mkdir -p from to secrets workspaces
gh release download "$FROM" -R syntropic137/syntropic137 --clobber -D from \
    -p docker-compose.syntropic137.yaml -p selfhost-entrypoint.sh
git -C "$REPO" fetch -q origin
TO_SHA="$(git -C "$REPO" rev-parse --short "$TO_REF")"
git -C "$REPO" show "$TO_REF:docker/docker-compose.syntropic137.yaml" > to/docker-compose.syntropic137.yaml
git -C "$REPO" show "$TO_REF:docker/selfhost-entrypoint.sh" > to/selfhost-entrypoint.sh
mkdir "$WORK/init-db"  # $WORK is fresh, so nothing to remove first
git -C "$REPO" archive "$FROM" docker/init-db | tar -x -C "$WORK/init-db" --strip-components=2
write_op_stub
for s in db-password redis-password minio-password; do openssl rand -hex 24 > "secrets/$s.secret"; done
: > secrets/github-app-private-key.pem
chmod 644 secrets/*
cat > .env <<EOF
APP_ENVIRONMENT=selfhost
SYN_INSTALL_DIR=$WORK
API_MEMORY_LIMIT=2g
API_CPU_LIMIT=4.0
EVENT_STORE_MEMORY_LIMIT=2g
POSTGRES_CPU_LIMIT=3.0
COLLECTOR_MEMORY_LIMIT=512m
MINIO_MEMORY_LIMIT=1g
EOF

if [ -z "$TO_API" ] || [ -z "$TO_COLLECTOR" ]; then
    step "build candidate images from $TO_REF ($TO_SHA)"
    SRC="$WORK/src"  # set before the add: the EXIT trap removes it on any failure from here
    git -C "$REPO" worktree add --detach -f "$SRC" "$TO_REF" >/dev/null
    git -C "$SRC" submodule update --init --quiet lib/event-sourcing-platform lib/agent-paradise-standards-system lib/agentic-workspace
    if [ -z "$TO_API" ]; then
        TO_API="syn-api:rehearsal-$TO_SHA"
        dk build -q -f "$SRC/infra/docker/images/syn-api/Dockerfile" --build-arg INCLUDE_DOCKER_CLI=1 \
            --build-arg SYN_BUILD_COMMIT="$TO_SHA" --build-arg SYN_BUILD_IMAGE_TAG="rehearsal-$TO_SHA" -t "$TO_API" "$SRC" >/dev/null
    fi
    if [ -z "$TO_COLLECTOR" ]; then
        TO_COLLECTOR="syn-collector:rehearsal-$TO_SHA"
        dk build -q -f "$SRC/packages/syn-collector/Dockerfile" -t "$TO_COLLECTOR" "$SRC" >/dev/null
    fi
    git -C "$REPO" worktree remove --force "$SRC"; SRC=""
fi

fi  # VERIFY_ONLY (prepare)

use_version() {  # $1 from|to
    # Render and validate in a staging dir; only a validated config is ever
    # promoted to the active one in $WORK.
    local stage="$WORK/stage-$1"
    rm -rf "$stage"; mkdir "$stage"
    cp "$1/docker-compose.syntropic137.yaml" "$stage/"
    if [ "$1" = from ]; then write_override "$stage" "" "" ""; else write_override "$stage" "$TO_API" "$TO_COLLECTOR" "$TO_ES"; fi
    check_rendered "$stage"  # refuses (exit 3) with the active config untouched
    cp "$stage/docker-compose.syntropic137.yaml" "$stage/override.yaml" "$1/selfhost-entrypoint.sh" "$WORK/"  # promote:validated
    # Create (not start) the containers and read their env before anything
    # runs: restore, API start and upgrade all come after this check.
    COMPOSE_USED=1
    dc create --force-recreate api collector >/dev/null
    check_container_env "$1 (created)"
    check_op_disabled "$1"
}

health() { curl -sf --max-time 10 "$API/health" || curl -sf --max-time 10 "$API/api/v1/health"; }
api_get() { curl -sf --max-time 30 "$API$1"; }

# Wait until the read path reaches the store head. Done = no projection
# lagging except ones that are held (a held projection never catches up, so
# waiting on it is pointless; it is reported instead). Prints seconds taken.
wait_caught_up() {  # $1 label
    local start now st lag behind held halted
    start=$(date +%s)
    while true; do
        now=$(date +%s)
        [ $(( now - start )) -gt "$TIMEOUT" ] && { fail "$1: catch-up timed out after ${TIMEOUT}s"; break; }
        if h="$(health 2>/dev/null)"; then
            echo "$h" > "$OUT/$1-health-last.json"
            st=$(jq -r '.subscription.status // "?"' <<<"$h")
            lag=$(jq -r '.subscription.lag // "?"' <<<"$h")
            held=$(jq -c '[.subscription.held_projections // [] | .[].projection]' <<<"$h")
            halted=$(jq -r '.subscription.halted_at // empty' <<<"$h")
            behind=$(jq --argjson held "$held" '[.subscription.lagging_projections // [] | .[] | select(.projection as $p | $held | index($p) | not)] | length' <<<"$h")
            printf '   %s +%ss status=%s lag=%s behind=%s held=%s halted=%s\n' "$1" $(( now - start )) "$st" "$lag" "$behind" "$held" "${halted:-none}" | tee -a "$OUT/$1-poll.log"
            if [ "$behind" = 0 ] && [ "$st" != catching_up ] && [ "$st" != "?" ]; then break; fi
            [ "$st" = stalled ] && { fail "$1: subscription stalled"; break; }
        fi
        sleep 10
    done
    echo $(( $(date +%s) - start )) > "$OUT/$1-catchup-seconds"
}

# Normalised view of one execution detail: what a rebuild must preserve.
# Timestamps are compared as UTC instants (one release prints Z, another +00:00).
DETAIL_PICK='def ts: if . == null then null else sub("\\+00:00$"; "Z") end;
  {status, workflow_id, started_at: (.started_at|ts), completed_at: (.completed_at|ts),
   total_phases, total_tokens, total_input_tokens, total_output_tokens,
   artifacts: ((.artifact_ids // []) | length),
   phases: [(.phases // [])[] | {phase_id, status}]}'

list_all_executions() {  # -> TSV "id<TAB>status", every page
    local page=1 total got=0 body
    : > "$1"
    while true; do
        body="$(api_get "/executions?page_size=200&page=$page")"
        total=$(jq '.total' <<<"$body")
        jq -r '.executions[] | [.workflow_execution_id, .status] | @tsv' <<<"$body" >> "$1"
        got=$(wc -l < "$1"); [ "$got" -ge "$total" ] || [ "$(jq '.executions | length' <<<"$body")" = 0 ] && break
        page=$(( page + 1 ))
    done
    sort -o "$1" "$1"
}

# Row count of every base table outside the system and timescale catalogs:
# the event store (events, aggregates, idempotency) and every projection.
# One "schema.table<TAB>count" line each; %I quotes odd identifiers.
TABLE_COUNTS_SQL="select format('%I.%I', table_schema, table_name) || E'\\t' ||
  (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
  from information_schema.tables where table_type = 'BASE TABLE'
  and table_schema not in ('pg_catalog', 'information_schema')
  and table_schema not like E'\\\\_timescaledb%' and table_schema not like 'timescaledb\\_%' order by 1"
# Tables allowed to shrink across the upgrade, each with its reason. Empty:
# no table is known to be legitimately rebuilt smaller. Add "schema.table"
# here only with the reason beside it.
REBUILT_TABLES=""

snapshot() {  # $1 label
    local d="$OUT/$1"; mkdir -p "$d"
    psql_q "select count(*), coalesce(max(global_nonce),0) from events" > "$d/events.txt"
    psql_q "$TABLE_COUNTS_SQL" | sort > "$d/tables.tsv"
    health > "$d/health.json"
    api_get "/executions?page_size=1" > "$d/executions.json"
    list_all_executions "$d/executions.tsv"
    api_get "/sessions?page_size=1" > "$d/sessions.json" || echo '{}' > "$d/sessions.json"
    api_get "/evals?page_size=1" > "$d/evals.json" || echo '{"unavailable":true}' > "$d/evals.json"
    for id in $(cat "$OUT/spot-ids.txt" 2>/dev/null); do
        api_get "/executions/$id" > "$d/exec-$id.json" || echo '{"missing":true}' > "$d/exec-$id.json"
    done
}

if [ "$VERIFY_ONLY" = 0 ]; then
# --- phase 1: baseline at FROM ----------------------------------------------
step "phase 1: start $FROM storage + event store"
use_version from
dc up -d --wait timescaledb event-store
step "restore events dump"
dk cp "$DUMP" "${PROJECT}-timescaledb:/tmp/events.dump" 2>/dev/null \
    || dc exec -T timescaledb sh -c 'cat > /tmp/events.dump' < "$DUMP"
dc exec -T timescaledb pg_restore -U syn -d syn --data-only --disable-triggers --table=events /tmp/events.dump
# The backup holds `events` only. The event store keeps stream heads in
# `aggregates` for optimistic concurrency; rebuild them from the events so a
# restored stream accepts its next append.
psql_q "insert into aggregates (tenant_id, aggregate_id, aggregate_type, last_nonce, last_global_nonce)
        select tenant_id, aggregate_id, max(aggregate_type), max(aggregate_nonce), max(global_nonce)
        from events group by tenant_id, aggregate_id
        on conflict (tenant_id, aggregate_id) do update set last_nonce = excluded.last_nonce, last_global_nonce = excluded.last_global_nonce" >/dev/null
psql_q "select setval('events_global_nonce_seq', (select max(global_nonce) from events))" >/dev/null
echo "   restored: $(psql_q 'select count(*) from events') events"
dc restart event-store >/dev/null; dc up -d --wait event-store

step "start $FROM API, wait for projections"
dc up -d --wait api
check_container_env "from (running)"
wait_caught_up from
# Spot-check ids: one per status, then fill to 5 from the newest.
api_get "/executions?page_size=50" > "$OUT/list-for-ids.json"
jq -r '[.executions | group_by(.status)[] | .[0].workflow_execution_id // .[0].execution_id // .[0].id] + [.executions[] | .workflow_execution_id // .execution_id // .id] | unique | .[:5][]' \
    "$OUT/list-for-ids.json" > "$OUT/spot-ids.txt" || true
snapshot from

# --- phase 2: upgrade in place to TO ----------------------------------------
step "phase 2: upgrade in place to $TO_REF ($TO_SHA)"
use_version to
UP0=$(date +%s)
dc up -d --wait api
echo $(( $(date +%s) - UP0 )) > "$OUT/to-api-ready-seconds"
check_container_env "to (running)"
wait_caught_up to
snapshot to

fi  # VERIFY_ONLY

# --- verify -----------------------------------------------------------------
# The upgraded API is live, so it may append events of its own (orphan
# reconciliation, queued starts, inventory sweeps). A difference is EXPLAINED
# only when the execution's own stream gained events after the baseline head;
# anything else is a rebuild that lost or changed data, and fails.
step "verify"
read -r EV_FROM HEAD_FROM < <(tr '|' ' ' < "$OUT/from/events.txt")
read -r EV_TO HEAD_TO < <(tr '|' ' ' < "$OUT/to/events.txt")
[ "$EV_TO" -ge "$EV_FROM" ] && [ "$HEAD_TO" -ge "$HEAD_FROM" ] || fail "event count went down: $EV_FROM -> $EV_TO"
if [ "$VERIFY_ONLY" = 0 ]; then
psql_q "select distinct aggregate_id from events where global_nonce > $HEAD_FROM" | sort > "$OUT/touched-after-baseline.txt"
psql_q "select event_type || ' ' || count(*) from events where global_nonce > $HEAD_FROM group by event_type order by count(*) desc" > "$OUT/events-after-baseline.txt"
fi
touched() { grep -qxF "$1" "$OUT/touched-after-baseline.txt"; }

# Every table, before and after: a decrease or a vanished table fails.
join -t $'\t' -a1 -a2 -e MISSING -o 0,1.2,2.2 <(sort "$OUT/from/tables.tsv") <(sort "$OUT/to/tables.tsv") \
  | while IFS=$'\t' read -r t before after; do
        if [ "$after" = MISSING ]; then v="FAIL table gone"
        elif [ "$before" = MISSING ]; then v="ok new table"
        elif [ "$after" -ge "$before" ]; then v=ok
        elif [[ " $REBUILT_TABLES " == *" $t "* ]]; then v="allowed (rebuilt)"
        else v="FAIL rows lost"; fi
        printf '%-60s %10s %10s  %s\n' "$t" "$before" "$after" "$v"
    done > "$OUT/table-counts.txt"
printf '   %-60s %10s %10s\n' table before after
sed 's/^/   /' "$OUT/table-counts.txt"
[ -s "$OUT/table-counts.txt" ] || fail "no table counts captured"
grep -q ' FAIL ' "$OUT/table-counts.txt" && fail "rows lost or tables gone (see table-counts.txt)"

: > "$OUT/execution-diffs.txt"
join -t $'\t' -a1 -a2 -e MISSING -o 0,1.2,2.2 "$OUT/from/executions.tsv" "$OUT/to/executions.tsv" \
  | while IFS=$'\t' read -r id before after; do
        [ "$before" = "$after" ] && continue
        if [ "$after" = MISSING ]; then echo "FAIL $id $before -> missing after upgrade"
        elif touched "$id"; then echo "explained $id $before -> $after (new events on its stream)"
        elif [ "$before" = MISSING ] && [ "$after" = queued ]; then echo "explained $id new row, queued (requested, never started)"
        else echo "FAIL $id $before -> $after with no new events"; fi
    done > "$OUT/execution-diffs.txt"
{ grep "^FAIL" "$OUT/execution-diffs.txt" || true; } | sed "s/^/   /"
grep -q '^FAIL' "$OUT/execution-diffs.txt" && fail "executions changed without new events (see execution-diffs.txt)"
for v in from to; do jq -cS '{total, status_counts}' "$OUT/$v/executions.json" > "$OUT/$v/exec-totals.json"; done

S_FROM=$(jq '.total // 0' "$OUT/from/sessions.json"); S_TO=$(jq '.total // 0' "$OUT/to/sessions.json")
[ "$S_TO" -ge "$S_FROM" ] && [ "$S_TO" -gt 0 ] || fail "sessions: $S_FROM -> $S_TO"
E_TO=$(jq '.total // "unavailable"' "$OUT/to/evals.json")
[ "$E_TO" != unavailable ] || fail "evals endpoint unavailable after upgrade"
jq -e '(.subscription.held_projections // []) == [] and (.subscription.halted_at == null)' "$OUT/to/health.json" >/dev/null \
    || fail "held/halted after upgrade: $(jq -c '{held: .subscription.held_projections, halted_at: .subscription.halted_at}' "$OUT/to/health.json")"

: > "$OUT/spot-check.txt"
for id in $(cat "$OUT/spot-ids.txt"); do
    a=$(jq -cS "$DETAIL_PICK" "$OUT/from/exec-$id.json"); b=$(jq -cS "$DETAIL_PICK" "$OUT/to/exec-$id.json")
    if jq -e '.missing' "$OUT/to/exec-$id.json" >/dev/null 2>&1; then echo "FAIL $id 404 after upgrade"
    elif [ "$a" = "$b" ]; then echo "ok $id $(jq -c '{status, workflow_id, phases: (.phases|length), total_tokens}' <<<"$b")"
    elif touched "$id"; then echo "explained $id changed by new events: $(jq -c .status <<<"$a") -> $(jq -c .status <<<"$b")"
    else echo "FAIL $id differs: $a -> $b"; fi
done >> "$OUT/spot-check.txt"
sed 's/^/   /' "$OUT/spot-check.txt"
grep -q '^FAIL' "$OUT/spot-check.txt" && fail "spot-check detail mismatch"

cat <<SUMMARY | tee "$OUT/summary.txt"

RESULT: $([ "$FAIL" = 0 ] && echo PASS || echo FAIL)
from $FROM -> $TO_REF ($TO_SHA)  api=$TO_API  event-store=${TO_ES:-compose default}
events: $EV_FROM (head $HEAD_FROM) -> $EV_TO (head $HEAD_TO)
baseline catch-up: $(cat "$OUT/from-catchup-seconds")s; upgrade: api ready $(cat "$OUT/to-api-ready-seconds")s + catch-up $(cat "$OUT/to-catchup-seconds")s
executions: $(cat "$OUT/from/exec-totals.json") -> $(cat "$OUT/to/exec-totals.json")
execution diffs: $(grep -c "^explained" "$OUT/execution-diffs.txt" || true) explained, $(grep -c "^FAIL" "$OUT/execution-diffs.txt" || true) unexplained
sessions: $S_FROM -> $S_TO   evals (after): $E_TO
artifacts: $OUT
SUMMARY
exit "$FAIL"
