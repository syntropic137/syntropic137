#!/usr/bin/env bash
# Guard: nothing in this repo may publish a container port to every interface.
#
# WHY THIS EXISTS. A sibling repo's `just pg-up` ran `docker run ... -p 5433:5432`,
# which binds 0.0.0.0. On a laptop behind NAT that is invisible. On a host with a
# public IP it put a superuser Postgres on the internet, and `COPY ... FROM
# PROGRAM` turned that into remote code execution in 35 minutes. The host mined
# crypto for 21 days on about half its cores before anyone noticed.
#
# Two things make this worse than it sounds:
#
#   1. A host firewall does NOT save you. Docker's NAT rewrites the destination
#      before the routing decision, so a published port never traverses the
#      INPUT chain that ufw/pf manages. The compromised host had ufw enabled,
#      default-deny, the whole time.
#   2. There is no patch. `COPY ... FROM PROGRAM` is deliberate Postgres
#      behaviour: to Postgres, a superuser IS the OS account. An exposed
#      database is not "a database at risk", it is a shell at risk.
#
# THE RULE: every publish names its host interface. `127.0.0.1:5432:5432`, or a
# variable that DEFAULTS to a loopback address (`${SYN_ENV_BIND:-127.0.0.1}:`).
# A publish that names only ports is a defect regardless of the machine it was
# written on, because the machine it runs on is not the machine it was written
# on.
#
# Note that a variable HOST PORT is not an interface. `"${SYN_ENV_PORT_DB}:5432"`
# looks parameterised and still binds 0.0.0.0. This guard rejects it.
#
# SCOPE is what actually starts containers: compose files under docker/ and
# infra/, the justfile, and scripts/. Prose in docs and READMEs is out of scope
# on purpose. .github/workflows is out of scope too: GitHub Actions
# `services.ports` has no interface syntax to name, and those runners are
# ephemeral and network-isolated.
set -euo pipefail

cd "$(dirname "$0")/.."

status=0
flag() {
    printf 'no_public_ports: %s\n' "$1" >&2
    status=1
}

self="scripts/no_public_ports.sh"

targets=(justfile)
while IFS= read -r f; do targets+=("$f"); done < <(
    git ls-files \
        'docker/*.yml' 'docker/*.yaml' 'docker/**/*.yml' 'docker/**/*.yaml' \
        'infra/**/*.yml' 'infra/**/*.yaml' \
        'scripts/*.sh' 2>/dev/null
)

for f in "${targets[@]}"; do
    [ -f "$f" ] || continue
    # This file necessarily quotes both bad shapes in its own comments.
    [ "$f" = "$self" ] && continue

    # `docker run -p 5432:5432` / `--publish 5432:5432`: no host part at all.
    while IFS= read -r hit; do
        flag "$f:$hit -- bare publish; bind an explicit interface (127.0.0.1:HOST:CONTAINER)"
    done < <(grep -nE '(^|[[:space:]])(-p|--publish)[[:space:]]+[0-9$]' "$f" \
             | grep -vE '(-p|--publish)[[:space:]]+[0-9.]+\.[0-9]+:' || true)

    # Compose `ports:` entries. A valid publish has at least two colons once
    # ${...} expansions are removed, because the first field is the interface.
    #   "127.0.0.1:5432:5432"              -> 2 colons  ok
    #   "${BIND:-127.0.0.1}:${PORT}:5432"  -> 2 colons  ok
    #   "5432:5432"                        -> 1 colon   REJECT
    #   "${SYN_ENV_PORT_DB}:5432"          -> 1 colon   REJECT (port, not interface)
    while IFS= read -r line; do
        n=${line%%:*}
        entry=${line#*:}
        # Only consider list items that look like a publish, not env/volumes.
        case "$entry" in
            *-\ *) ;;
            *) continue ;;
        esac
        value=${entry#*- }
        value=${value%%#*}                       # strip trailing comment
        value=$(printf '%s' "$value" | tr -d '"'"'"' ')
        # Remove ${...} so a default like ${X:-127.0.0.1} does not add colons.
        stripped=$(printf '%s' "$value" | sed 's/\${[^}]*}//g')
        colons=$(printf '%s' "$stripped" | tr -cd ':' | wc -c | tr -d ' ')
        [ "$colons" -ge 2 ] && continue
        flag "$f:$n -- '$value' publishes to every interface; prefix a host interface (e.g. \${SYN_ENV_BIND:-127.0.0.1}:)"
    done < <(awk '
        /^[[:space:]]*ports:[[:space:]]*$/ { inports=1; next }
        inports && /^[[:space:]]*-[[:space:]]/ { print NR ":" $0; next }
        inports && !/^[[:space:]]*-/ { inports=0 }
    ' "$f")
done

if [ "$status" -ne 0 ]; then
    echo "no_public_ports: FAIL. See the comment at the top of $self." >&2
    exit 1
fi

echo "no_public_ports: ok (every published port names its host interface)"
