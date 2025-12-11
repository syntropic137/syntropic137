# Firecracker MicroVM Setup

Firecracker provides the **strongest isolation** for AEF workspaces using lightweight
MicroVMs. Each agent runs in its own VM with a separate kernel, providing true
kernel-level isolation.

**Perfect for:**
- 🏠 Home lab servers (Linux + KVM)
- 🖥️ Local development on Linux
- 🏢 Production bare-metal deployments
- ☁️ Self-hosted cloud infrastructure

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Linux (kernel 4.14+) |
| **Hardware** | Intel VT-x or AMD-V (virtualization) |
| **KVM** | `/dev/kvm` must be accessible |
| **Memory** | ~5MB overhead per MicroVM |
| **Boot time** | ~125ms |

### Check Requirements

```bash
# Check for KVM support
ls -la /dev/kvm

# Check CPU virtualization support
grep -E 'vmx|svm' /proc/cpuinfo

# Check kernel version
uname -r
```

## Quick Setup

```bash
# Run the setup script (downloads everything)
./docker/firecracker/setup.sh

# Test the installation
./docker/firecracker/test.sh
```

## Manual Setup

### 1. Install Firecracker

```bash
# Download latest release
FIRECRACKER_VERSION="v1.7.0"
curl -L "https://github.com/firecracker-microvm/firecracker/releases/download/${FIRECRACKER_VERSION}/firecracker-${FIRECRACKER_VERSION}-x86_64.tgz" | tar xz

# Install binaries
sudo mv release-*/firecracker-${FIRECRACKER_VERSION}-x86_64 /usr/local/bin/firecracker
sudo mv release-*/jailer-${FIRECRACKER_VERSION}-x86_64 /usr/local/bin/jailer

# Verify installation
firecracker --version
```

### 2. Get Kernel Image

You can either download a pre-built kernel or compile your own:

#### Option A: Download Pre-built (Recommended)
```bash
# Download AEF-optimized kernel
./docker/firecracker/download-kernel.sh

# Or manually download:
curl -L https://s3.amazonaws.com/spec.ccfc.min/ci-artifacts/kernels/x86_64/vmlinux-5.10.204 \
    -o /var/lib/aef/firecracker/vmlinux
```

#### Option B: Build Custom Kernel
```bash
./docker/firecracker/build-kernel.sh
```

### 3. Create Root Filesystem

The rootfs is an ext4 image containing the OS for workspaces:

```bash
# Build rootfs from our Dockerfile
./docker/firecracker/build-rootfs.sh

# This creates:
#   /var/lib/aef/firecracker/rootfs.ext4
```

## Directory Structure

After setup, you'll have:

```
/var/lib/aef/firecracker/
├── vmlinux              # Linux kernel (uncompressed)
├── rootfs.ext4          # Root filesystem (ext4 image)
├── config/              # Firecracker VM configs
└── sockets/             # API sockets for running VMs
```

## Home Lab Configuration

For home lab deployments, consider these optimizations:

### Resource Allocation

```bash
# In .env file:
AEF_WORKSPACE_ISOLATION_BACKEND=firecracker
AEF_WORKSPACE_POOL_SIZE=10           # Pre-warm 10 VMs
AEF_WORKSPACE_MAX_CONCURRENT=50      # Max 50 concurrent agents

# Per-workspace limits
AEF_SECURITY_MAX_MEMORY=1Gi          # 1GB per workspace
AEF_SECURITY_MAX_CPU=1.0             # 1 vCPU per workspace
```

### KVM Permissions

```bash
# Add your user to kvm group
sudo usermod -aG kvm $USER

# Verify access
ls -la /dev/kvm
# Should show: crw-rw---- 1 root kvm ...
```

### Networking (Optional)

By default, workspaces have **no network access** for security.
If you need network access for specific use cases:

```bash
# Create a bridge network
sudo ip link add br0 type bridge
sudo ip addr add 172.16.0.1/24 dev br0
sudo ip link set br0 up

# Enable IP forwarding
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward

# In .env:
AEF_SECURITY_ALLOW_NETWORK=true
```

## Comparison: Home Lab vs Cloud

| Feature | Firecracker (Home Lab) | E2B (Cloud) |
|---------|------------------------|-------------|
| **Isolation** | Kernel-level (strongest) | Provider-managed |
| **Latency** | ~125ms boot | ~500ms-2s |
| **Cost** | $0 (your hardware) | Pay per use |
| **Scale** | Limited by hardware | Unlimited |
| **Network** | Full control | Provider-managed |
| **Best for** | Consistent workloads | Burst capacity |

## Troubleshooting

### "Permission denied: /dev/kvm"

```bash
# Check if KVM is enabled in BIOS
dmesg | grep -i kvm

# Add user to kvm group
sudo usermod -aG kvm $USER
# Log out and back in

# Alternatively, change permissions (not recommended for production)
sudo chmod 666 /dev/kvm
```

### "Kernel not found"

```bash
# Verify kernel exists
ls -la /var/lib/aef/firecracker/vmlinux

# Re-download if needed
./docker/firecracker/download-kernel.sh
```

### "Failed to boot VM"

```bash
# Check Firecracker logs
journalctl -u aef-firecracker -f

# Verify rootfs is valid
file /var/lib/aef/firecracker/rootfs.ext4
# Should show: ext4 filesystem data

# Test manually
firecracker --api-sock /tmp/firecracker-test.socket &
curl --unix-socket /tmp/firecracker-test.socket \
    -X PUT "http://localhost/boot-source" \
    -H "Content-Type: application/json" \
    -d '{"kernel_image_path": "/var/lib/aef/firecracker/vmlinux"}'
```

### VM Doesn't Start

```bash
# Enable debug logging
FIRECRACKER_LOG_LEVEL=debug firecracker --api-sock /tmp/test.socket

# Check dmesg for KVM errors
dmesg | tail -50
```

## Security Considerations

Firecracker provides strong isolation but follow these practices:

1. **Never run Firecracker as root in production** - Use jailer
2. **Limit KVM access** - Only authorized users should access /dev/kvm
3. **Network isolation** - Keep `AEF_SECURITY_ALLOW_NETWORK=false` unless required
4. **Resource limits** - Always set memory and CPU limits
5. **Jailer** - Use Firecracker's jailer for additional isolation

```bash
# Example: Running with jailer (production)
jailer --id my-vm --exec-file /usr/local/bin/firecracker --uid 1000 --gid 1000
```

## Related Documentation

- [Firecracker Documentation](https://github.com/firecracker-microvm/firecracker/tree/main/docs)
- [ADR-021: Isolated Workspace Architecture](../../docs/adrs/ADR-021-isolated-workspace-architecture.md)
- [Workspace README](../../packages/aef-adapters/src/aef_adapters/workspaces/README.md)
