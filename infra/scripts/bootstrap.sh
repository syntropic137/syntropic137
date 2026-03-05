#!/usr/bin/env bash
# =============================================================================
# Syntropic137 — Self-Host Bootstrap Script
# =============================================================================
# Installs all prerequisites for running the Syntropic137 stack on a bare
# machine. Supports macOS (Intel & Apple Silicon) and Linux (Debian/Ubuntu,
# Fedora/RHEL).
#
# ⚠  SECURITY NOTE: Piping curl to bash is convenient but skips inspection.
#    For production systems, download the script first, review it, then run:
#
#      curl --proto '=https' --tlsv1.2 -fsSL \
#        https://raw.githubusercontent.com/Syntropic137/syntropic137/main/infra/scripts/bootstrap.sh \
#        -o bootstrap.sh
#      less bootstrap.sh          # review
#      chmod +x bootstrap.sh && ./bootstrap.sh
#
# Idempotent: safe to run multiple times. Already-installed tools are skipped.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { printf "${BLUE}[info]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$*"; }
err()   { printf "${RED}[error]${NC} %s\n" "$*" >&2; }

has() { command -v "$1" &>/dev/null; }

# Secure curl wrapper — enforces TLS 1.2+ on every invocation
scurl() { curl --proto '=https' --tlsv1.2 -fsSL "$@"; }

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"

info "Platform: ${OS} / ${ARCH}"

if [[ "$OS" != "Darwin" && "$OS" != "Linux" ]]; then
    err "Unsupported OS: ${OS}. This script supports macOS and Linux."
    exit 1
fi

# ---------------------------------------------------------------------------
# macOS: Homebrew
# ---------------------------------------------------------------------------
install_homebrew() {
    if has brew; then
        ok "Homebrew already installed"
        return
    fi
    info "Installing Homebrew..."
    /bin/bash -c "$(scurl https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Add to PATH for Apple Silicon
    if [[ "$ARCH" == "arm64" && -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    ok "Homebrew installed"
}

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
install_docker() {
    if has docker; then
        ok "Docker already installed ($(docker --version 2>/dev/null | head -1))"
        return
    fi

    if [[ "$OS" == "Darwin" ]]; then
        info "Installing Docker Desktop via Homebrew..."
        brew install --cask docker
        info "Docker Desktop installed. Please open it from Applications to complete setup."
        warn "You may need to restart this script after Docker Desktop is running."
    else
        info "Installing Docker via official install script..."
        local tmpfile
        tmpfile="$(mktemp)"
        scurl https://get.docker.com -o "$tmpfile"
        sh "$tmpfile"
        rm -f "$tmpfile"
        # Add current user to docker group
        if ! groups "$USER" | grep -q docker; then
            sudo usermod -aG docker "$USER"
            warn "Added $USER to docker group. You may need to log out and back in."
        fi
        # Enable and start Docker
        sudo systemctl enable docker
        sudo systemctl start docker
        ok "Docker installed and started"
    fi
}

# ---------------------------------------------------------------------------
# just (command runner)
# ---------------------------------------------------------------------------
install_just() {
    if has just; then
        ok "just already installed ($(just --version 2>/dev/null))"
        return
    fi

    if [[ "$OS" == "Darwin" ]]; then
        info "Installing just via Homebrew..."
        brew install just
    else
        info "Installing just via official installer..."
        local tmpfile
        tmpfile="$(mktemp)"
        scurl https://just.systems/install.sh -o "$tmpfile"
        sh "$tmpfile" --to /usr/local/bin
        rm -f "$tmpfile"
    fi
    ok "just installed"
}

# ---------------------------------------------------------------------------
# uv (Python package manager)
# ---------------------------------------------------------------------------
install_uv() {
    if has uv; then
        ok "uv already installed ($(uv --version 2>/dev/null))"
        return
    fi

    info "Installing uv..."
    local tmpfile
    tmpfile="$(mktemp)"
    scurl https://astral.sh/uv/install.sh -o "$tmpfile"
    sh "$tmpfile"
    rm -f "$tmpfile"

    # Source env so uv is available in this session
    if [[ -f "$HOME/.local/bin/env" ]]; then
        # shellcheck disable=SC1091
        source "$HOME/.local/bin/env"
    elif [[ -d "$HOME/.local/bin" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    ok "uv installed"
}

# ---------------------------------------------------------------------------
# Python 3.12
# ---------------------------------------------------------------------------
install_python() {
    # Check if Python 3.12+ is available
    if has python3; then
        PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
        if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 12 ]]; then
            ok "Python ${PY_VERSION} already installed"
            return
        fi
    fi

    info "Installing Python 3.12 via uv..."
    uv python install 3.12
    ok "Python 3.12 installed"
}

# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
install_git() {
    if has git; then
        ok "Git already installed ($(git --version 2>/dev/null))"
        return
    fi

    if [[ "$OS" == "Darwin" ]]; then
        info "Installing git via Homebrew..."
        brew install git
    else
        info "Installing git via package manager..."
        if has apt-get; then
            sudo apt-get update -qq && sudo apt-get install -y -qq git
        elif has dnf; then
            sudo dnf install -y git
        else
            err "Cannot detect package manager. Please install git manually."
            return 1
        fi
    fi
    ok "Git installed"
}

# ---------------------------------------------------------------------------
# Node.js + pnpm
# ---------------------------------------------------------------------------
install_node() {
    if has node; then
        ok "Node.js already installed ($(node --version 2>/dev/null))"
    else
        if [[ "$OS" == "Darwin" ]]; then
            info "Installing Node.js via Homebrew..."
            brew install node
        else
            info "Installing Node.js via NodeSource..."
            if has apt-get; then
                local tmpfile
                tmpfile="$(mktemp)"
                scurl https://deb.nodesource.com/setup_lts.x -o "$tmpfile"
                sudo bash "$tmpfile"
                rm -f "$tmpfile"
                sudo apt-get install -y -qq nodejs
            elif has dnf; then
                local tmpfile
                tmpfile="$(mktemp)"
                scurl https://rpm.nodesource.com/setup_lts.x -o "$tmpfile"
                sudo bash "$tmpfile"
                rm -f "$tmpfile"
                sudo dnf install -y nodejs
            else
                err "Cannot detect package manager. Install Node.js manually:"
                err "  https://nodejs.org/en/download/"
                return 1
            fi
        fi
        ok "Node.js installed"
    fi

    if has pnpm; then
        ok "pnpm already installed ($(pnpm --version 2>/dev/null))"
    else
        info "Installing pnpm..."
        npm install -g pnpm
        ok "pnpm installed"
    fi
}

# ===========================================================================
# Main
# ===========================================================================
echo ""
echo "=============================================="
echo "  Syntropic137 — Self-Host Bootstrap"
echo "=============================================="
echo ""

if [[ "$OS" == "Darwin" ]]; then
    install_homebrew
fi

install_docker
install_just
install_uv
install_python
install_git
install_node

echo ""
echo "=============================================="
echo "  Bootstrap complete!"
echo "=============================================="
echo ""
info "All prerequisites installed. Next steps:"
echo ""
echo "  git clone --recursive https://github.com/Syntropic137/syntropic137.git"
echo "  cd syntropic137"
echo "  just onboard"
echo ""

if [[ "$OS" == "Darwin" ]]; then
    if ! docker info &>/dev/null 2>&1; then
        warn "Docker Desktop is installed but not running."
        warn "Open Docker Desktop from Applications, then run 'just onboard'."
    fi
fi

if [[ "$ARCH" == "arm64" ]]; then
    info "Apple Silicon detected — first event-store build may take 5-10 minutes."
fi
