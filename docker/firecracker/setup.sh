#!/usr/bin/env bash
# Firecracker Setup Script for AEF
#
# This script sets up Firecracker for running AEF isolated workspaces.
# Works on Linux systems with KVM support.
#
# Usage:
#   ./docker/firecracker/setup.sh              # Full setup
#   ./docker/firecracker/setup.sh --check      # Just check requirements
#   ./docker/firecracker/setup.sh --skip-rootfs # Skip rootfs build (faster)
#
# See docker/firecracker/README.md for details

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRECRACKER_VERSION="${FIRECRACKER_VERSION:-v1.7.0}"
INSTALL_DIR="${AEF_FIRECRACKER_DIR:-/var/lib/aef/firecracker}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Parse arguments
CHECK_ONLY=false
SKIP_ROOTFS=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --check)
            CHECK_ONLY=true
            shift
            ;;
        --skip-rootfs)
            SKIP_ROOTFS=true
            shift
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# =============================================================================
# Requirement Checks
# =============================================================================

check_requirements() {
    info "Checking requirements..."
    
    local failed=false
    
    # Check Linux
    if [[ "$(uname -s)" != "Linux" ]]; then
        error "Firecracker requires Linux. Your OS: $(uname -s)"
        failed=true
    else
        info "✓ Linux detected"
    fi
    
    # Check KVM
    if [[ ! -e /dev/kvm ]]; then
        error "/dev/kvm not found. Enable virtualization in BIOS."
        failed=true
    elif [[ ! -r /dev/kvm ]] || [[ ! -w /dev/kvm ]]; then
        warn "/dev/kvm exists but not accessible. Run: sudo usermod -aG kvm $USER"
        # Not a hard failure, might work with sudo
    else
        info "✓ KVM accessible"
    fi
    
    # Check CPU virtualization
    if ! grep -qE 'vmx|svm' /proc/cpuinfo 2>/dev/null; then
        error "CPU virtualization not detected. Enable VT-x/AMD-V in BIOS."
        failed=true
    else
        local virt_type
        if grep -q vmx /proc/cpuinfo; then
            virt_type="Intel VT-x"
        else
            virt_type="AMD-V"
        fi
        info "✓ CPU virtualization: $virt_type"
    fi
    
    # Check kernel version
    local kernel_version
    kernel_version=$(uname -r | cut -d. -f1-2)
    if [[ $(echo "$kernel_version >= 4.14" | bc -l 2>/dev/null || echo 1) -eq 0 ]]; then
        warn "Kernel $kernel_version may be too old. Recommend 4.14+"
    else
        info "✓ Kernel version: $(uname -r)"
    fi
    
    # Check required tools
    for tool in curl tar docker; do
        if command -v $tool &>/dev/null; then
            info "✓ $tool installed"
        else
            error "$tool not found. Please install it."
            failed=true
        fi
    done
    
    if [[ "$failed" == "true" ]]; then
        error "Requirements check failed"
        return 1
    fi
    
    info "All requirements met!"
    return 0
}

# =============================================================================
# Installation
# =============================================================================

install_firecracker() {
    info "Installing Firecracker ${FIRECRACKER_VERSION}..."
    
    local arch
    arch=$(uname -m)
    if [[ "$arch" == "x86_64" ]]; then
        arch="x86_64"
    elif [[ "$arch" == "aarch64" ]]; then
        arch="aarch64"
    else
        error "Unsupported architecture: $arch"
        return 1
    fi
    
    local download_url="https://github.com/firecracker-microvm/firecracker/releases/download/${FIRECRACKER_VERSION}/firecracker-${FIRECRACKER_VERSION}-${arch}.tgz"
    local temp_dir
    temp_dir=$(mktemp -d)
    
    info "Downloading from: $download_url"
    curl -L "$download_url" | tar xz -C "$temp_dir"
    
    # Find and install binaries
    local release_dir
    release_dir=$(find "$temp_dir" -type d -name "release-*" | head -1)
    
    if [[ -z "$release_dir" ]]; then
        error "Could not find release directory in archive"
        rm -rf "$temp_dir"
        return 1
    fi
    
    sudo mv "$release_dir/firecracker-${FIRECRACKER_VERSION}-${arch}" /usr/local/bin/firecracker
    sudo mv "$release_dir/jailer-${FIRECRACKER_VERSION}-${arch}" /usr/local/bin/jailer
    sudo chmod +x /usr/local/bin/firecracker /usr/local/bin/jailer
    
    rm -rf "$temp_dir"
    
    # Verify installation
    if firecracker --version &>/dev/null; then
        info "✓ Firecracker installed: $(firecracker --version)"
    else
        error "Firecracker installation failed"
        return 1
    fi
}

setup_directories() {
    info "Setting up directories..."
    
    sudo mkdir -p "${INSTALL_DIR}"/{config,sockets}
    sudo chown -R "$(id -u):$(id -g)" "${INSTALL_DIR}"
    
    info "✓ Created ${INSTALL_DIR}"
}

download_kernel() {
    info "Downloading kernel image..."
    
    local kernel_url="https://s3.amazonaws.com/spec.ccfc.min/ci-artifacts/kernels/x86_64/vmlinux-5.10.204"
    local kernel_path="${INSTALL_DIR}/vmlinux"
    
    if [[ -f "$kernel_path" ]]; then
        info "Kernel already exists at ${kernel_path}"
        return 0
    fi
    
    curl -L "$kernel_url" -o "$kernel_path"
    chmod 644 "$kernel_path"
    
    info "✓ Kernel downloaded to ${kernel_path}"
}

build_rootfs() {
    info "Building rootfs from workspace Dockerfile..."
    
    local rootfs_path="${INSTALL_DIR}/rootfs.ext4"
    local rootfs_size="${AEF_ROOTFS_SIZE:-2G}"
    
    if [[ -f "$rootfs_path" ]]; then
        info "Rootfs already exists at ${rootfs_path}"
        read -p "Rebuild? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            return 0
        fi
    fi
    
    # Build workspace Docker image
    info "Building workspace Docker image..."
    docker build -t aef-workspace:latest -f "${SCRIPT_DIR}/../workspace/Dockerfile" "${SCRIPT_DIR}/../.."
    
    # Create container and export filesystem
    info "Exporting filesystem..."
    local container_id
    container_id=$(docker create aef-workspace:latest)
    
    # Create empty ext4 image
    dd if=/dev/zero of="$rootfs_path" bs=1 count=0 seek="$rootfs_size" 2>/dev/null
    mkfs.ext4 -F "$rootfs_path"
    
    # Mount and copy filesystem
    local mount_point
    mount_point=$(mktemp -d)
    sudo mount -o loop "$rootfs_path" "$mount_point"
    
    docker export "$container_id" | sudo tar -x -C "$mount_point"
    
    sudo umount "$mount_point"
    rmdir "$mount_point"
    docker rm "$container_id"
    
    info "✓ Rootfs created at ${rootfs_path} (${rootfs_size})"
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         Firecracker Setup for AEF Isolated Workspaces        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    check_requirements || exit 1
    
    if [[ "$CHECK_ONLY" == "true" ]]; then
        info "Check complete. Run without --check to install."
        exit 0
    fi
    
    echo ""
    read -p "Continue with installation? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        info "Installation cancelled"
        exit 0
    fi
    
    # Check if already installed
    if command -v firecracker &>/dev/null; then
        info "Firecracker already installed: $(firecracker --version)"
    else
        install_firecracker
    fi
    
    setup_directories
    download_kernel
    
    if [[ "$SKIP_ROOTFS" != "true" ]]; then
        build_rootfs
    else
        info "Skipping rootfs build (--skip-rootfs)"
    fi
    
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    Setup Complete! 🎉                         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Files created:"
    echo "  ${INSTALL_DIR}/vmlinux      - Linux kernel"
    echo "  ${INSTALL_DIR}/rootfs.ext4  - Root filesystem"
    echo ""
    echo "To test:"
    echo "  ./docker/firecracker/test.sh"
    echo ""
    echo "To configure AEF to use Firecracker:"
    echo "  export AEF_WORKSPACE_ISOLATION_BACKEND=firecracker"
    echo ""
}

main "$@"
