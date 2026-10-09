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
#   backup   DIR                 dump DIR/syn-<UTC>.dump and DIR/syn-<UTC>.dump.manifest
#                                (sha256 of the dump, row count of every table),
#                                published only after every row was read back
#   prune    DIR DAYS            delete backups older than DAYS days: only files
#                                this script created and recorded in DIR's ledger
#                                (.syn-db-backup.ledger), nothing else in DIR
#   schedule DIR "CRON" DAYS     backup + prune whenever CRON matches (UTC)
#   restore  FILE [--force]      check FILE against its manifest, restore it into
#                                a new staging database, verify every table's row
#                                count, then rename PGDATABASE aside (kept, never
#                                dropped) and the staging database into its
#                                place. Any failure leaves PGDATABASE untouched.
#                                Exits 3, changing nothing, if PGDATABASE holds
#                                rows and --force is absent. --force first backs
#                                PGDATABASE up into SYN_BACKUP_DIR (default
#                                /backups) and stops if that backup fails.
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

MANIFEST_HEADER="syn-db-backup manifest 1"
# Append-only record of every file this script creates in a backup directory,
# as `INODE NAME`. prune deletes a file only when its name has the generated
# shape AND the ledger records that name with that file's inode: a file an
# operator put there, whatever it is called, is never in it.
LEDGER=".syn-db-backup.ledger"

# The only names this script ever publishes or leaves behind. prune deletes
# nothing else. Shell patterns are anchored and [..] never matches '/' or a
# newline, so no other file name can satisfy one.
D8='[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
T6='[0-9][0-9][0-9][0-9][0-9][0-9]'
STAMP="${D8}T${T6}Z"
A='[A-Za-z0-9]'

# 0 if $1 (a base name) is a backup or manifest this script published.
is_published_name() {
    case $1 in
        syn-$STAMP.dump | syn-$STAMP-[1-9].dump | syn-$STAMP-[1-9][0-9].dump) return 0 ;;
        syn-$STAMP.dump.manifest | syn-$STAMP-[1-9].dump.manifest | syn-$STAMP-[1-9][0-9].dump.manifest) return 0 ;;
    esac
    return 1
}

# 0 if $1 (a base name) is a temporary file of an unfinished backup.
is_partial_name() {
    case $1 in
        .syn-$STAMP.dump.partial.$A$A$A$A$A$A) return 0 ;;
    esac
    return 1
}

inode() {
    ls -di -- "$1" | awk '{ print $1 }'
}

# Record DIR/NAME, just created by this script, in DIR's ledger. A file that
# cannot be recorded is only ever kept, never pruned: that is the safe side.
track() {
    tr_ino=$(inode "$1/$2") && [ -n "$tr_ino" ] &&
        printf '%s %s\n' "$tr_ino" "$2" >>"$1/$LEDGER" ||
        echo "syn-db-backup: could not record $2 in $1/$LEDGER; it will never be pruned" >&2
}

# Hard-link SRC to exactly DEST, never replacing or entering anything there:
# fails, leaving nothing behind, if DEST exists in any form (file, directory,
# symlink, dangling symlink), including one that appears during the call.
publish_link() {
    if [ -e "$2" ] || [ -L "$2" ]; then
        return 1
    fi
    ln "$1" "$2" 2>/dev/null || return 1
    if [ -L "$2" ] || [ ! -f "$2" ] || ! [ "$2" -ef "$1" ]; then
        # A directory appeared at DEST, so ln linked inside it under SRC's
        # own unique name: remove exactly that link, which is ours.
        pl_stray="$2/${1##*/}"
        if [ -f "$pl_stray" ] && [ ! -L "$pl_stray" ] && [ "$pl_stray" -ef "$1" ]; then
            rm -f -- "$pl_stray"
        fi
        return 1
    fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum <"$1"
    else
        shasum -a 256 <"$1"
    fi | cut -d' ' -f1
}

# Number of TABLE DATA entries in an archive. Fails if pg_restore cannot read
# its table of contents.
table_data_count() {
    listing=$(pg_restore --list "$1") || fail "pg_restore cannot read $1"
    printf '%s\n' "$listing" | grep -c ' TABLE DATA ' || true
}

# `rows N TABLE` for every table in the archive, TABLE as pg_dump quotes it.
# Reads every row of every table, so an archive cut short anywhere fails here:
# pg_restore errors, or a COPY block never reaches its terminator.
archive_rows() {
    rc_file=$(mktemp) || return 1
    rows=$({
        rc=0
        pg_restore --data-only --file=- "$1" || rc=$?
        echo "$rc" >"$rc_file"
    } | awk '
    # The table name of a COPY line: one or more identifiers, bare or
    # "quoted" (with "" escapes), joined by dots.
    function ident(s,    out, i, j, c) {
        out = ""; i = 1
        while (1) {
            if (substr(s, i, 1) == "\"") {
                j = i + 1
                while (1) {
                    c = substr(s, j, 1)
                    if (c == "") return ""
                    if (c == "\"") { if (substr(s, j + 1, 1) == "\"") { j += 2; continue } break }
                    j++
                }
                out = out substr(s, i, j - i + 1); i = j + 1
            } else {
                if (!match(substr(s, i), /^[^ ."]+/)) return ""
                out = out substr(s, i, RLENGTH); i += RLENGTH
            }
            if (substr(s, i, 1) != ".") return out
            out = out "."; i++
        }
    }
    copying { if ($0 == "\\.") { print "rows " n " " table; copying = 0 } else n++; next }
    /^COPY / && / FROM stdin;$/ {
        table = ident(substr($0, 6))
        if (table == "") { bad = 1; exit 1 }
        copying = 1; n = 0
    }
    END { if (bad || copying) exit 1 }') || {
        rm -f "$rc_file"
        return 1
    }
    rc=$(cat "$rc_file")
    rm -f "$rc_file"
    [ "$rc" = 0 ] || return 1
    printf '%s\n' "$rows"
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
    # Written under unique temporary names and published only once verified:
    # a dump that dies half way never looks like a backup, and two backups in
    # the same second (schedule + manual) never share a file.
    # busybox mktemp (this image) needs the X run at the very end.
    partial=$(mktemp "$dir/.syn-$stamp.dump.partial.XXXXXX") ||
        fail "cannot create a file in $dir"
    trap 'rm -f "$partial"' EXIT
    track "$dir" "${partial##*/}"
    manifest_partial=$(mktemp "$dir/.syn-$stamp.dump.partial.XXXXXX") ||
        fail "cannot create a file in $dir"
    trap 'rm -f "$partial" "$manifest_partial"' EXIT
    track "$dir" "${manifest_partial##*/}"
    pg_dump --format=custom --file="$partial" || fail "pg_dump failed"
    tables=$(table_data_count "$partial")
    [ "$tables" -gt 0 ] || fail "archive lists no table data; refusing to keep it"
    rows=$(archive_rows "$partial") ||
        fail "cannot read every row back from the archive; refusing to keep it"
    copied=$(printf '%s\n' "$rows" | grep -c '^rows ' || true)
    [ "$copied" -eq "$tables" ] ||
        fail "archive lists $tables tables but holds data for $copied; refusing to keep it"
    sum=$(sha256 "$partial")
    [ "${#sum}" -eq 64 ] || fail "cannot checksum the archive"
    {
        echo "$MANIFEST_HEADER"
        echo "sha256 $sum"
        printf '%s\n' "$rows"
        echo "tables $tables"
    } >"$manifest_partial"
    # Publishing never replaces or enters anything already there: a taken
    # name (same-second collision, or anything an operator put there) moves
    # on to the next free -N suffix. The manifest is claimed first, so a
    # published dump always has its manifest.
    name="syn-$stamp.dump" n=0
    while :; do
        if publish_link "$manifest_partial" "$dir/$name.manifest"; then
            publish_link "$partial" "$dir/$name" && break
            # Remove the manifest just linked, and only if it still is ours.
            if [ ! -L "$dir/$name.manifest" ] && [ "$dir/$name.manifest" -ef "$manifest_partial" ]; then
                rm -f -- "$dir/$name.manifest"
            fi
        fi
        n=$((n + 1))
        [ "$n" -le 99 ] || fail "no free name for a $stamp backup in $dir"
        name="syn-$stamp-$n.dump"
    done
    track "$dir" "$name.manifest"
    track "$dir" "$name"
    rm -f "$partial" "$manifest_partial"
    trap - EXIT
    size=$(du -h "$dir/$name" | cut -f1)
    total=$(printf '%s\n' "$rows" | awk '{ s += $2 } END { print s + 0 }')
    echo "backup ok: $dir/$name ($size, $tables tables, $total rows)"
}

# Age-based retention over files this script created, and only those: each
# must be named in the generated shape and recorded in DIR's ledger with its
# current inode. Anything else in DIR, however old or however named, is never
# touched. Without a ledger nothing is pruned.
prune() {
    dir=$1
    require_days "$2"
    [ -d "$dir" ] || fail "backup directory $dir does not exist"
    ledger="$dir/$LEDGER"
    if [ ! -f "$ledger" ] || [ -L "$ledger" ]; then
        return 0
    fi
    while read -r ino name; do
        if is_published_name "$name"; then
            minutes=$(($2 * 1440))
        elif is_partial_name "$name"; then
            # Abandoned temp files of a backup that died; a live one is minutes old.
            minutes=1440
        else
            continue
        fi
        path="$dir/$name"
        # A regular file, never a symlink (which could point anywhere).
        if [ ! -f "$path" ] || [ -L "$path" ]; then
            continue
        fi
        # Still the file this script created, not one put in its place.
        [ "$(inode "$path")" = "$ino" ] || continue
        # -mmin, not -mtime: -mtime truncates to whole days, so +7 keeps 7.9 days.
        [ -n "$(find "$path" -prune -type f -mmin "+$minutes")" ] || continue
        rm -f -- "$path"
        case $name in .syn-*) ;; *) echo "pruned: $name" ;; esac
    done <"$ledger"
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

# The manifest is whole and the archive is byte for byte the one it describes.
# Runs before anything is changed, so a truncated or altered file stops here.
check_manifest() {
    cm_file=$1 cm_manifest=$2
    [ "$(sed -n 1p "$cm_manifest")" = "$MANIFEST_HEADER" ] || fail "$cm_manifest is not a backup manifest"
    want=$(sed -n 's/^sha256 \([0-9a-f]\{64\}\)$/\1/p' "$cm_manifest")
    [ "${#want}" -eq 64 ] || fail "$cm_manifest has no sha256"
    have=$(sha256 "$cm_file")
    [ "$have" = "$want" ] ||
        fail "$cm_file does not match its manifest (sha256 $have, expected $want): truncated or altered; nothing was changed"
    listed=$(sed -n 's/^tables \([0-9][0-9]*\)$/\1/p' "$cm_manifest")
    counted=$(grep -c '^rows [0-9][0-9]* ' "$cm_manifest" || true)
    [ -n "$listed" ] && [ "$listed" -eq "$counted" ] && [ "$counted" -gt 0 ] ||
        fail "$cm_manifest is incomplete; nothing was changed"
}

# Every table in DB holds the rows the manifest recorded, the hypertables
# answer queries, and TimescaleDB is out of restore mode. Counts are exact,
# except an extension's own configuration tables (TimescaleDB's catalog), which
# CREATE EXTENSION seeds before the archive's rows arrive: those must hold at
# least the archived rows.
verify_restored() {
    # POSIX sh has no locals: these names must not shadow restore's.
    vr_db=$1 vr_manifest=$2
    checks=$(awk '/^rows [0-9]+ / {
        t = $0; sub(/^rows [0-9]+ /, "", t); lit = t; gsub(/'\''/, "'\'''\''", lit)
        print "select count(*) || '\'' '\'' || case when exists (select 1 from pg_depend" \
            " where classid = '\''pg_class'\''::regclass and objid = to_regclass('\''" lit "'\'')" \
            " and deptype = '\''e'\'') then '\''extension'\'' else '\''exact'\'' end from only " t ";"
    }' "$vr_manifest")
    actual=$(printf '%s\n' "$checks" | psql -X -At -v ON_ERROR_STOP=1 -d "$vr_db") || {
        echo "syn-db-backup: a table in the manifest is missing from the restored database" >&2
        return 1
    }
    printf '%s\n' "$actual" | awk -v m="$vr_manifest" '
        BEGIN { while ((getline l < m) > 0) if (l ~ /^rows [0-9]+ /) { n++; want[n] = l } }
        {
            split(want[NR], w, " "); t = want[NR]; sub(/^rows [0-9]+ /, "", t)
            got = $1 + 0; need = w[2] + 0
            if ($2 == "extension" ? got < need : got != need) {
                print "syn-db-backup: " t ": restored " got " rows, backup holds " need > "/dev/stderr"
                bad = 1
            }
        }
        END { if (NR != n) { print "syn-db-backup: checked " NR " tables, manifest lists " n > "/dev/stderr"; bad = 1 }
              exit bad }' || return 1
    psql -X -At -v ON_ERROR_STOP=1 -d "$vr_db" >/dev/null <<'SQL' || return 1
select format('select count(*) from %I.%I', hypertable_schema, hypertable_name)
from timescaledb_information.hypertables \gexec
SQL
    [ "$(psql -X -At -v ON_ERROR_STOP=1 -d "$vr_db" -c 'show timescaledb.restoring')" = off ] || {
        echo "syn-db-backup: '$vr_db' is still in TimescaleDB restore mode" >&2
        return 1
    }
}

restore() {
    file=$1 force=${2:-}
    case $force in '' | --force) ;; *) fail "usage: restore FILE [--force]" ;; esac
    [ -f "$file" ] || fail "no such backup: $file"
    manifest="$file.manifest"
    [ -f "$manifest" ] ||
        fail "no manifest at $manifest; refusing to restore an archive that cannot be verified"
    check_manifest "$file" "$manifest"
    db=${PGDATABASE:?PGDATABASE must name the database to restore}

    # psql interpolates :'db' from stdin only, never in -c.
    exists=$(echo "select count(*) from pg_database where datname = :'db'" |
        psql -X -At -v ON_ERROR_STOP=1 -d postgres -v db="$db")
    if [ "$exists" = 1 ]; then
        populated=$(nonempty_tables "$db")
        if [ -n "$populated" ]; then
            if [ "$force" != "--force" ]; then
                echo "syn-db-backup: database '$db' already holds data in:" >&2
                printf '%s\n' "$populated" | sed 's/^/  /' >&2
                echo "syn-db-backup: refusing to replace it; re-run with --force (which backs it up and keeps it aside)" >&2
                exit 3
            fi
            # A fresh backup of what is about to be replaced, in its own
            # process so its `set -e` holds. No backup, no restore.
            echo "backing up '$db' before replacing it"
            PGDATABASE=$db sh "$0" backup "${SYN_BACKUP_DIR:-/backups}" ||
                fail "could not back up '$db' first; refusing to restore, nothing was changed"
        fi
    fi

    # Unique, generated names: create fails rather than reuse an existing one.
    stamp=$(date -u +%Y%m%d_%H%M%S)_$$
    staging="syn_restore_$stamp"
    aside="syn_pre_restore_$stamp"
    # :"db" quotes the name as an identifier, whatever it contains.
    echo 'create database :"db";' | psql -X -q -v ON_ERROR_STOP=1 -d postgres -v db="$staging" ||
        fail "cannot create staging database '$staging'; nothing was changed"
    # Only ever the database created on the line above, and only until it
    # has taken the live name.
    swapped=0
    trap '[ "$swapped" = 1 ] || echo "drop database if exists :\"db\" with (force);" |
        psql -X -q -d postgres -v db="$staging" >/dev/null 2>&1' EXIT
    echo "restoring into staging database '$staging'"
    # Hypertables restore only between pre_restore and post_restore, and only
    # serially (no -j): docs/deployment/timescaledb-2.29-upgrade.md.
    psql -X -q -v ON_ERROR_STOP=1 -d "$staging" \
        -c "create extension if not exists timescaledb" \
        -c "select timescaledb_pre_restore()" >/dev/null
    rc=0
    pg_restore --exit-on-error --no-owner --no-acl --dbname="$staging" "$file" || rc=$?
    psql -X -q -v ON_ERROR_STOP=1 -d "$staging" -c "select timescaledb_post_restore()" >/dev/null
    [ "$rc" -eq 0 ] || fail "pg_restore failed (exit $rc); '$db' was not changed"
    verify_restored "$staging" "$manifest" ||
        fail "restored data does not match the manifest; '$db' was not changed"

    # One transaction: both renames happen or neither does.
    if [ "$exists" = 1 ]; then
        psql -X -q -v ON_ERROR_STOP=1 -d postgres -v live="$db" -v staging="$staging" -v aside="$aside" <<'SQL' >/dev/null ||
select pg_terminate_backend(pid) from pg_stat_activity
where datname = :'live' and pid <> pg_backend_pid();
begin;
alter database :"live" rename to :"aside";
alter database :"staging" rename to :"live";
commit;
SQL
            fail "could not swap '$staging' into place; '$db' was not changed"
    else
        echo 'alter database :"staging" rename to :"live";' |
            psql -X -q -v ON_ERROR_STOP=1 -d postgres -v live="$db" -v staging="$staging" ||
            fail "could not rename '$staging' to '$db'"
    fi
    swapped=1
    trap - EXIT
    echo "restore ok: '$db' from $(basename "$file")"
    if [ "$exists" = 1 ]; then
        echo "previous '$db' kept as database '$aside'; drop it yourself once the restore is verified"
    fi
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
