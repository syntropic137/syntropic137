# Syn137 Envoy Proxy
# Pure Envoy — credential injection handled by the token-injector service (ext_authz)
#
# Build: docker build -t envoy-proxy:latest .

# Pinned to a specific patch version. v1.31-latest was last pushed 2025-07-18
# and its baked Debian apt sources went stale, breaking apt-get install (#736).
# Bumping to v1.34.14 (pushed 2026-04-10). Update via the same PR pattern.
FROM envoyproxy/envoy:v1.34.14

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
