# Syn137 Envoy Proxy
# Pure Envoy — credential injection handled by the token-injector service (ext_authz)
#
# Build: docker build -t envoy-proxy:latest .

# Pinned to a specific patch version. Older envoy tags ship with stale baked
# Debian apt sources, breaking `apt-get install`:
#   - v1.31-latest (last pushed 2025-07-18) - original break (#736)
#   - v1.34.14 - libcurl4 deps (libbrotli1, libpsl5, librtmp1) unsatisfiable
# When the next bump is needed, build locally first to confirm
# `apt-get install -y ca-certificates curl` resolves cleanly.
FROM envoyproxy/envoy:v1.35.10

# Install CA certificates for TLS verification and curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*

# Copy Envoy configuration
COPY envoy.yaml /etc/envoy/envoy.yaml

# Expose proxy port
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:9901/ready || exit 1

# Run Envoy
ENTRYPOINT ["/usr/local/bin/envoy"]
CMD ["-c", "/etc/envoy/envoy.yaml", "--log-level", "info"]
