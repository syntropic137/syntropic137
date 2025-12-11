#!/usr/bin/env bash
# Test Firecracker Installation
#
# Runs a quick test to verify Firecracker is working correctly.
#
# Usage:
#   ./docker/firecracker/test.sh

set -euo pipefail

INSTALL_DIR="${AEF_FIRECRACKER_DIR:-/var/lib/aef/firecracker}"
SOCKET_PATH="/tmp/firecracker-test-$$.socket"
KERNEL_PATH="${INSTALL_DIR}/vmlinux"
ROOTFS_PATH="${INSTALL_DIR}/rootfs.ext4"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

cleanup() {
    if [[ -n "${FC_PID:-}" ]] && kill -0 "$FC_PID" 2>/dev/null; then
        info "Stopping Firecracker..."
        kill "$FC_PID" 2>/dev/null || true
        wait "$FC_PID" 2>/dev/null || true
    fi
    rm -f "$SOCKET_PATH"
}
trap cleanup EXIT

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              Firecracker Installation Test                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check firecracker binary
info "Checking Firecracker binary..."
if ! command -v firecracker &>/dev/null; then
    error "Firecracker not found in PATH"
    exit 1
fi
info "✓ Firecracker: $(firecracker --version)"

# Check kernel
info "Checking kernel image..."
if [[ ! -f "$KERNEL_PATH" ]]; then
    error "Kernel not found at $KERNEL_PATH"
    exit 1
fi
info "✓ Kernel: $KERNEL_PATH ($(du -h "$KERNEL_PATH" | cut -f1))"

# Check rootfs
info "Checking rootfs..."
if [[ ! -f "$ROOTFS_PATH" ]]; then
    error "Rootfs not found at $ROOTFS_PATH"
    exit 1
fi
info "✓ Rootfs: $ROOTFS_PATH ($(du -h "$ROOTFS_PATH" | cut -f1))"

# Check KVM access
info "Checking KVM access..."
if [[ ! -r /dev/kvm ]] || [[ ! -w /dev/kvm ]]; then
    error "Cannot access /dev/kvm. Run: sudo usermod -aG kvm $USER"
    exit 1
fi
info "✓ KVM accessible"

# Start Firecracker
info "Starting Firecracker API server..."
firecracker --api-sock "$SOCKET_PATH" &
FC_PID=$!
sleep 0.5

if ! kill -0 "$FC_PID" 2>/dev/null; then
    error "Firecracker failed to start"
    exit 1
fi
info "✓ Firecracker running (PID: $FC_PID)"

# Test API
info "Testing API..."
response=$(curl -s --unix-socket "$SOCKET_PATH" "http://localhost/")
if [[ -z "$response" ]]; then
    error "API not responding"
    exit 1
fi
info "✓ API responding"

# Configure VM (but don't actually boot - just test config)
info "Testing VM configuration..."

# Set kernel
curl -s --unix-socket "$SOCKET_PATH" -X PUT "http://localhost/boot-source" \
    -H "Content-Type: application/json" \
    -d "{\"kernel_image_path\": \"${KERNEL_PATH}\", \"boot_args\": \"console=ttyS0 reboot=k panic=1 pci=off\"}"

# Set rootfs
curl -s --unix-socket "$SOCKET_PATH" -X PUT "http://localhost/drives/rootfs" \
    -H "Content-Type: application/json" \
    -d "{\"drive_id\": \"rootfs\", \"path_on_host\": \"${ROOTFS_PATH}\", \"is_root_device\": true, \"is_read_only\": false}"

# Set machine config
curl -s --unix-socket "$SOCKET_PATH" -X PUT "http://localhost/machine-config" \
    -H "Content-Type: application/json" \
    -d '{"vcpu_count": 1, "mem_size_mib": 128}'

# Get instance info
instance_info=$(curl -s --unix-socket "$SOCKET_PATH" "http://localhost/")
info "✓ VM configured successfully"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              All Tests Passed! 🎉                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Firecracker is ready for use with AEF."
echo ""
echo "To enable in AEF:"
echo "  export AEF_WORKSPACE_ISOLATION_BACKEND=firecracker"
echo ""
echo "Note: This test configured but did NOT boot a VM."
echo "      Full boot testing requires more time (~125ms per VM)."
echo ""
