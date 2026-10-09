#!/bin/sh
# syn-db-backup - back up, verify, prune and restore the Syn137 database.
#
# Runs inside the selfhost `db-backup` service, which uses the same
# timescale/timescaledb image as the database so pg_dump/pg_restore always
# match the server. `just selfhost-backup` / `just selfhost-restore` and the
# scheduled service all call this one script; nothing else writes a backup.
#
# Connection comes from the libpq environment (PGHOST, PGUSER, PGDATABASE)
# plus POSTGRES_PASSWORD_FILE, the same secret the database reads. The just
# targets pass PGUSER/PGDATABASE as read from the running timescaledb
# container; the schedule reads them from SYN_DB_IDENTITY_FILE, which that
# container's healthcheck writes. No credential is ever printed.
#
#   backup   DIR                     dump DIR/syn-<UTC>.dump, verify, report
#   prune    DIR DAYS                delete backups older than DAYS days
#   schedule DIR "CRON" DAYS         backup + prune whenever CRON matches (UTC)
#   restore  FILE [--force]          recreate PGDATABASE from FILE; exits 3,
#                                    changing nothing, if it holds rows and
#                                    --force is absent
#   cron-match "CRON" "M H DOM MON DOW"   exit 0 match, 1 no match, 2 invalid
set -eu

fail() {
    echo "syn-db-backup: $*" >&2
    exit 1
}

if [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -z "${PGPASSWORD:-}" ]; then
    PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
    export PGPASSWORD
fi

# Number of TABLE DATA entries in an archive. Fails if pg_restore cannot read
# it, so a truncated or non-custom-format file never counts as a backup.
table_data_count() {
    listing=$(pg_restore --list "$1") || fail "pg_restore cannot read $1"
    printf '%s\n' "$listing" | grep -c ' TABLE DATA ' || true
}

require_days() {
    case $1 in
        '' | *[!0-9]*) fail "retention days must be a whole number, got '$1'" ;;
    esac
    # 0 would delete the backup that was just taken.
    [ "$1" -ge 1 ] || fail "retention days must be at least 1, got '$1'"
}

backup() {
    dir=$1
    [ -d "$dir" ] || fail "backup directory $dir does not exist"
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    umask 077
    # Written under a unique name prune never matches, and published only once
    # verified: a dump that dies half way never looks like a backup, and two
    # backups in the same second (schedule + manual) never share a file.
    # busybox mktemp (this image) needs the X run at the very end.
    partial=$(mktemp "$dir/.syn-$stamp.dump.partial.XXXXXX") ||
        fail "cannot create a file in $dir"
    trap 'rm -f "$partial"' EXIT
    pg_dump --format=custom --file="$partial"
    tables=$(table_data_count "$partial")
    [ "$tables" -gt 0 ] || fail "archive lists no table data; refusing to keep it"
    # ln refuses an existing name, so publishing never replaces another
    # backup: a same-second collision takes the next free -N suffix.
    name="syn-$stamp.dump" n=0
    until ln "$partial" "$dir/$name" 2>/dev/null; do
        n=$((n + 1))
        [ "$n" -le 99 ] || fail "no free name for a $stamp backup in $dir"
        name="syn-$stamp-$n.dump"
    done
    rm -f "$partial"
    trap - EXIT
    size=$(du -h "$dir/$name" | cut -f1)
    echo "backup ok: $dir/$name ($size, $tables tables)"
}

prune() {
    dir=$1
    require_days "$2"
    # -mmin, not -mtime: -mtime truncates to whole days, so +7 keeps 7.9 days.
    find "$dir" -maxdepth 1 -type f -name 'syn-*.dump' -mmin "+$(($2 * 1440))" \
        -print -exec rm -f {} \; | sed 's|.*/|pruned: |'
    find "$dir" -maxdepth 1 -type f -name '.syn-*.dump.partial.*' -mmin +1440 -exec rm -f {} \;
}

# Standard five-field cron: numbers, '*', lists, ranges and '/step'. Day of
# month and day of week match on either when both are restricted, and 7 is
# Sunday. Names (MON, JAN) and @aliases are rejected rather than ignored, so a
# schedule that could never fire fails at startup instead of silently.
cron_match() {
    printf '%s\n' "$2" | awk -v expr="$1" '
    function invalid(why) { print "invalid cron expression \"" expr "\": " why > "/dev/stderr"; bad = 1; exit 2 }
    function num(s, lo, hi) {
        if (s !~ /^[0-9]+$/) invalid("\"" s "\" is not a number")
        if (s + 0 < lo || s + 0 > hi) invalid(s " is outside " lo "-" hi)
        return s + 0
    }
    # Every list element and range is checked before anything matches, so
    # validity never depends on the time it is asked at.
    function field_ok(spec, v, lo, hi,    n, parts, i, p, step, r, a, b, hit) {
        n = split(spec, parts, ",")
        hit = 0
        for (i = 1; i <= n; i++) {
            p = parts[i]; step = 1
            if (index(p, "/")) {
                if (split(p, r, "/") != 2) invalid("bad step in \"" p "\"")
                p = r[1]; step = num(r[2], 1, hi)
            }
            if (p == "*") { a = lo; b = hi }
            else if (index(p, "-")) {
                if (split(p, r, "-") != 2) invalid("bad range in \"" p "\"")
                a = num(r[1], lo, hi); b = num(r[2], lo, hi)
                if (a > b) invalid("descending range \"" p "\"")
            }
            else { a = num(p, lo, hi); b = (step > 1 ? hi : a) }
            if (v >= a && v <= b && (v - a) % step == 0) hit = 1
        }
        return hit
    }
    {
        if (split(expr, f, " ") != 5) invalid("need 5 fields")
        min = field_ok(f[1], $1 + 0, 0, 59)
        hour = field_ok(f[2], $2 + 0, 0, 23)
        dom = field_ok(f[3], $3 + 0, 1, 31)
        mon = field_ok(f[4], $4 + 0, 1, 12)
        dow = field_ok(f[5], $5 + 0, 0, 7)
        if ($5 + 0 == 0 && field_ok(f[5], 7, 0, 7)) dow = 1
        if (f[3] != "*" && f[5] != "*") day = dom || dow
        else day = dom && dow
        matched = min && hour && mon && day
    }
    END { if (bad) exit 2; exit matched ? 0 : 1 }'
}

# PGUSER/PGDATABASE as the running database container says, from the file its
# healthcheck writes (user and database name only). Read again for every
# backup, so a recreated container with a new identity is followed.
container_identity() {
    f=${SYN_DB_IDENTITY_FILE:-}
    [ -n "$f" ] || return 0
    [ -r "$f" ] || fail "no database identity at $f; is timescaledb healthy?"
    PGUSER=$(sed -n 's/^PGUSER=//p' "$f")
    PGDATABASE=$(sed -n 's/^PGDATABASE=//p' "$f")
    [ -n "$PGUSER" ] && [ -n "$PGDATABASE" ] || fail "incomplete database identity in $f"
    export PGUSER PGDATABASE
}

schedule() {
    dir=$1 expr=$2 days=$3
    require_days "$days"
    # Validate once against any time: exit 2 is a bad expression.
    rc=0
    cron_match "$expr" "0 0 1 1 0" || rc=$?
    [ "$rc" -ne 2 ] || fail "BACKUP_SCHEDULE is not a valid cron expression"
    echo "scheduled backups: '$expr' (UTC), keeping $days days, into $dir"
    last=""
    while :; do
        stamp=$(date -u +%Y%m%d%H%M)
        if [ "$stamp" != "$last" ] && cron_match "$expr" "$(date -u '+%M %H %d %m %w')"; then
            last=$stamp
            # A child shell, so `set -e` and the EXIT trap in backup apply
            # and a failed backup does not end the schedule.
            if (container_identity && sh "$0" backup "$dir"); then
                sh "$0" prune "$dir" "$days" || echo "syn-db-backup: prune failed" >&2
            else
                echo "syn-db-backup: scheduled backup FAILED; previous backups kept" >&2
            fi
        fi
        s=$(date -u +%S)
        sleep $((60 - ${s#0}))
    done
}

# Every user table that holds at least one row, schema-qualified, one per line.
# Exact (not pg_stat estimates): this decides whether data is about to be lost.
nonempty_tables() {
    psql -X -At -v ON_ERROR_STOP=1 -d "$1" <<'SQL'
select format('%I.%I', table_schema, table_name)
from information_schema.tables
where table_type = 'BASE TABLE'
  and table_schema not in ('pg_catalog', 'information_schema')
  and table_schema not like '\_timescaledb%'
  and table_schema not like 'timescaledb\_%'
  and (xpath('/row/x/text()', query_to_xml(
        format('select exists (select 1 from %I.%I) as x', table_schema, table_name),
        false, true, '')))[1]::text = 'true'
order by 1;
SQL
}

restore() {
    file=$1 force=${2:-}
    [ -f "$file" ] || fail "no such backup: $file"
    [ "$(table_data_count "$file")" -gt 0 ] || fail "$file lists no table data; not a usable backup"
    db=${PGDATABASE:?PGDATABASE must name the database to restore}

    # psql interpolates :'db' from stdin only, never in -c.
    exists=$(echo "select count(*) from pg_database where datname = :'db'" |
        psql -X -At -v ON_ERROR_STOP=1 -d postgres -v db="$db")
    if [ "$exists" = 1 ]; then
        populated=$(nonempty_tables "$db")
        if [ -n "$populated" ] && [ "$force" != "--force" ]; then
            echo "syn-db-backup: database '$db' already holds data in:" >&2
            printf '%s\n' "$populated" | sed 's/^/  /' >&2
            echo "syn-db-backup: refusing to replace it; re-run with --force to discard that data" >&2
            exit 3
        fi
    fi

    # Recreate rather than restore over: tables the api created on startup
    # would otherwise collide with the archive's own CREATE TABLEs.
    echo "recreating database '$db'"
    # :"db" quotes the name as an identifier, whatever it contains.
    printf '%s\n' 'drop database if exists :"db" with (force);' 'create database :"db";' |
        psql -X -q -v ON_ERROR_STOP=1 -d postgres -v db="$db"
    # Hypertables restore only between pre_restore and post_restore, and only
    # serially (no -j): docs/deployment/timescaledb-2.29-upgrade.md.
    psql -X -q -v ON_ERROR_STOP=1 -d "$db" \
        -c "create extension if not exists timescaledb" \
        -c "select timescaledb_pre_restore()" >/dev/null
    rc=0
    pg_restore --no-owner --no-acl --dbname="$db" "$file" || rc=$?
    psql -X -q -v ON_ERROR_STOP=1 -d "$db" -c "select timescaledb_post_restore()" >/dev/null
    [ "$rc" -eq 0 ] || fail "pg_restore reported errors (exit $rc); inspect '$db' before starting writers"
    echo "restore ok: '$db' from $(basename "$file")"
}

cmd=${1:-}
[ $# -gt 0 ] && shift
case $cmd in
    backup) [ $# -eq 1 ] || fail "usage: backup DIR"; backup "$1" ;;
    prune) [ $# -eq 2 ] || fail "usage: prune DIR DAYS"; prune "$1" "$2" ;;
    schedule) [ $# -eq 3 ] || fail "usage: schedule DIR CRON DAYS"; schedule "$1" "$2" "$3" ;;
    restore) [ $# -ge 1 ] && [ $# -le 2 ] || fail "usage: restore FILE [--force]"; restore "$@" ;;
    cron-match) [ $# -eq 2 ] || fail "usage: cron-match CRON 'M H DOM MON DOW'"; cron_match "$1" "$2" ;;
    *) fail "usage: syn-db-backup backup|prune|schedule|restore|cron-match ..." ;;
esac
