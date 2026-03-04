# Syn137 Sidecar Proxy
# Envoy-based proxy for secure token injection and observability
#
# Build: docker build -t syn-sidecar:latest .
# Run: docker run -e SYN_EXECUTION_ID=exec-123 -p 8081:8081 syn-sidecar:latest

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
