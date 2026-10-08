#!/bin/sh
# Turn the workspace -> API route on only when platform access is ON (ADR-072).
#
# envoy.yaml gates both /syn-platform routes on the runtime key
# syn_platform.access_enabled, default 0%. Writing 100 here is the only way to
# open them, so an unset or unrecognised value leaves the route absent and no
# workspace request is ever forwarded to the API. Accepts the spellings
# pydantic reads as true for the same variable in the API.
set -eu

switch=/var/lib/syn-envoy-runtime/envoy/syn_platform/access_enabled
mkdir -p "$(dirname "$switch")"
case "$(printf '%s' "${SYN_PLATFORM_ACCESS_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')" in
  1 | true | t | yes | y | on) echo 100 > "$switch" ;;
  *) rm -f "$switch" ;;
esac

exec /usr/local/bin/envoy "$@"
