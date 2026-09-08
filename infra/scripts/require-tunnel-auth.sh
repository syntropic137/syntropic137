#!/bin/sh
# Refuse to start a tunnel that has no way to authenticate what it publishes.
#
# A tunnel is not a port: there is no host interface to pin to loopback, and
# binding one would delete the feature rather than secure it. What is left of
# "reaching the network and requiring auth are coupled" is the auth half, so a
# stack that runs a tunnel must have SYN_API_PASSWORD set (#1148).
#
# The authority for that rule is the gateway entrypoint
# (infra/docker/images/gateway/docker-entrypoint.sh), because that is the only
# place that also reaches a self-hoster running the published compose with no
# justfile at all. This script is the same rule stated early, on the host, for
# the `just` recipes: `up -d` returns 0 while the gateway exits and restarts
# behind it, so without this the operator's first sign of trouble is a
# restarting container rather than a sentence naming the variable to set.
#
# Two statements of one rule is a drift risk, so
# infra/scripts/tests/test_gateway_auth_binding.py drives both this script and
# the entrypoint with the same unsafe combination and requires both to refuse.
#
# Reads the environment rather than taking arguments: the caller has already
# resolved .env, infra/.env and any vault secrets, and the answer must be about
# what the stack will actually be started with.
set -e

[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] || exit 0
[ -z "${SYN_API_PASSWORD:-}" ] || exit 0

cat >&2 <<'ERROR'
refusing to start: this stack would be published with no authentication.

  CLOUDFLARE_TUNNEL_TOKEN is set, so cloudflared will publish this stack to the
  internet, and SYN_API_PASSWORD is empty, so nothing would ask a caller for
  credentials. The dashboard and the whole API would be open to anyone with the
  hostname.

  Set SYN_API_PASSWORD (generate one with: openssl rand -hex 32) in .env or
  infra/.env, or unset CLOUDFLARE_TUNNEL_TOKEN to start the stack without its
  tunnel.

  Point the tunnel at http://gateway:8081, which is the listener that password
  guards. Routing lives in the Cloudflare Zero Trust dashboard, so no check in
  this repo can see it: Zero Trust -> Networks -> Connectors -> your tunnel ->
  Public Hostname.
ERROR
exit 1
