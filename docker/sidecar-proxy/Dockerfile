# Syn137 Envoy Proxy
# Pure Envoy — credential injection handled by the token-injector service (ext_authz)
#
# Build: docker build -t syn-envoy-proxy:latest .

FROM envoyproxy/envoy:v1.31-latest

# Install CA certificates for TLS verification
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

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
