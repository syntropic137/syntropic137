# Egress Proxy for AEF Isolated Workspaces
#
# This proxy enforces network allowlisting for agent containers.
# Only traffic to allowed hosts (e.g., api.anthropic.com, github.com)
# passes through; all other traffic is blocked.
#
# See ADR-021: Isolated Workspace Architecture - Network Allowlist
#
# Build:
#   docker build -t aef-egress-proxy:latest -f docker/egress-proxy/Dockerfile docker/egress-proxy/
#
# Run:
#   docker run -d --name egress-proxy -p 8080:8080 \
#     -e ALLOWED_HOSTS="api.anthropic.com,github.com,pypi.org" \
#     aef-egress-proxy:latest

FROM mitmproxy/mitmproxy:10.1.1

# Install Python dependencies for the addon
USER root
RUN pip install --no-cache-dir pyyaml

# Copy the allowlist addon script
COPY allowlist_addon.py /app/allowlist_addon.py

# Set default allowed hosts (can be overridden via environment)
ENV ALLOWED_HOSTS="api.anthropic.com,github.com,api.github.com,pypi.org,files.pythonhosted.org"

# Expose the proxy port
EXPOSE 8080

# Run mitmproxy with the allowlist addon
# --listen-host 0.0.0.0: Listen on all interfaces
# --listen-port 8080: Default proxy port
# -s /app/allowlist_addon.py: Load our allowlist script
# --set block_global=false: Allow connections to global IPs
ENTRYPOINT ["mitmdump", "--listen-host", "0.0.0.0", "--listen-port", "8080", "-s", "/app/allowlist_addon.py", "--set", "block_global=false"]
