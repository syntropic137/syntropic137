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
#   --project NAME         compose project name (default syn-rehearsal)
#   --port N               host port for the API (default 38000)
#   --timeout SECONDS      max wait for each catch-up (default 3600)
#   --workdir DIR          working dir (default: mktemp)
#   --keep                 leave the stack up at the end (default: tear down)
#   --verify-only          re-run only the verify step on --workdir's saved out/
#
# Isolation: its own compose project, container names, volume and network
# names, so a dev, test or selfhost stack on the same machine is untouched.
# The docker socket proxy is replaced by an idle container, so the API cannot
# reach the host Docker daemon (no reaping, no workspaces). No GitHub App or
# session-store credentials are configured, so nothing calls out.
#
# Exit status: 0 PASS, 1 FAIL (count mismatch, held/halted projection, timeout).
set -euo pipefail
export LC_ALL=C  # sort and join must agree on collation

DUMP=""; FROM="v0.33.1"; TO_REF="origin/main"
TO_API=""; TO_COLLECTOR=""; TO_ES=""; TO_SHA="(verify-only)"
PROJECT="syn-rehearsal"; PORT=38000; TIMEOUT=3600; WORK=""; KEEP=0; VERIFY_ONLY=0
usage() { sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
while [ $# -gt 0 ]; do
    case "$1" in
        --dump) DUMP="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --to-ref) TO_REF="$2"; shift 2 ;;
        --to-api-image) TO_API="$2"; shift 2 ;;
        --to-collector-image) TO_COLLECTOR="$2"; shift 2 ;;
        --to-event-store) TO_ES="$2"; shift 2 ;;
        --project) PROJECT="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        --workdir) WORK="$2"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --verify-only) VERIFY_ONLY=1; KEEP=1; shift ;;
        *) usage ;;
    esac
done
[ "$VERIFY_ONLY" = 1 ] || [ -f "$DUMP" ] || { echo "--dump file not found: $DUMP" >&2; usage; }
for bin in docker gh jq curl git; do command -v "$bin" >/dev/null || { echo "missing $bin" >&2; exit 2; }; done
timeout 20 docker info >/dev/null || { echo "docker daemon not reachable" >&2; exit 2; }

REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
[ -z "$DUMP" ] || DUMP="$(cd "$(dirname "$DUMP")" && pwd)/$(basename "$DUMP")"
WORK="${WORK:-$(mktemp -d -t syn-rehearsal)}"; mkdir -p "$WORK"; cd "$WORK"
OUT="$WORK/out"; mkdir -p "$OUT"
API="http://127.0.0.1:${PORT}"
T0=$(date +%s)
step() { printf '\n==> [%s +%ss] %s\n' "$(date -u +%H:%M:%SZ)" "$(( $(date +%s) - T0 ))" "$*"; }
FAIL=0; fail() { echo "FAIL: $*" | tee -a "$OUT/failures.txt"; FAIL=1; }
dc() { docker compose -p "$PROJECT" --env-file "$WORK/.env" -f "$WORK/docker-compose.syntropic137.yaml" -f "$WORK/override.yaml" "$@"; }
psql_q() { dc exec -T timescaledb psql -U syn -d syn -tAc "$1"; }

teardown() {
    if [ "$VERIFY_ONLY" = 1 ]; then return; fi
    if [ "$KEEP" = 1 ]; then echo "stack kept: docker compose -p $PROJECT ... down -v"; return; fi
    step "tear down"
    dc down -v --remove-orphans >/dev/null 2>&1 || true
}
trap teardown EXIT

# --- override: isolation, names, prod-like limits ---------------------------
write_override() {  # $1 api image, $2 collector image, $3 event-store image ("" = keep)
    {
        echo "services:"
        for s in timescaledb event-store collector api gateway minio redis envoy-proxy token-injector cloudflared; do
            echo "  ${s}:"
            echo "    container_name: ${PROJECT}-${s}"
            case "$s" in
                api) echo "    ports: !override [\"127.0.0.1:${PORT}:8000\"]"; [ -n "$1" ] && echo "    image: $1" ;;
                collector) [ -n "$2" ] && echo "    image: $2" ;;
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
    } | sed "s/PROJECT/${PROJECT}/g" > "$WORK/override.yaml"
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
rm -rf init-db; mkdir init-db
git -C "$REPO" archive "$FROM" docker/init-db | tar -x -C init-db --strip-components=2
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
    SRC="$WORK/src"; git -C "$REPO" worktree add --detach -f "$SRC" "$TO_REF" >/dev/null
    git -C "$SRC" submodule update --init --quiet lib/event-sourcing-platform lib/agent-paradise-standards-system lib/agentic-workspace
    if [ -z "$TO_API" ]; then
        TO_API="syn-api:rehearsal-$TO_SHA"
        docker build -q -f "$SRC/infra/docker/images/syn-api/Dockerfile" --build-arg INCLUDE_DOCKER_CLI=1 \
            --build-arg SYN_BUILD_COMMIT="$TO_SHA" --build-arg SYN_BUILD_IMAGE_TAG="rehearsal-$TO_SHA" -t "$TO_API" "$SRC" >/dev/null
    fi
    if [ -z "$TO_COLLECTOR" ]; then
        TO_COLLECTOR="syn-collector:rehearsal-$TO_SHA"
        docker build -q -f "$SRC/packages/syn-collector/Dockerfile" -t "$TO_COLLECTOR" "$SRC" >/dev/null
    fi
    git -C "$REPO" worktree remove --force "$SRC"
fi

fi  # VERIFY_ONLY (prepare)

use_version() {  # $1 from|to
    cp "$1/docker-compose.syntropic137.yaml" "$1/selfhost-entrypoint.sh" "$WORK/"
    if [ "$1" = from ]; then write_override "" "" ""; else write_override "$TO_API" "$TO_COLLECTOR" "$TO_ES"; fi
    dc config -q
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

snapshot() {  # $1 label
    local d="$OUT/$1"; mkdir -p "$d"
    psql_q "select count(*), coalesce(max(global_nonce),0) from events" > "$d/events.txt"
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
docker cp "$DUMP" "${PROJECT}-timescaledb:/tmp/events.dump" 2>/dev/null \
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
dc up -d --wait --remove-orphans api
echo $(( $(date +%s) - UP0 )) > "$OUT/to-api-ready-seconds"
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
