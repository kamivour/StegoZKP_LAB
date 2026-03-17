#!/usr/bin/env bash
# =============================================================================
#  ZK-SNARK DICOM Steganography — Verifier Setup Script (Linux / macOS)
# =============================================================================
#  Checks every required dependency and installs missing ones automatically.
#
#  Requirements:
#    Python  >= 3.9     (pydicom, Pillow, numpy, scipy)
#    Node.js >= 18
#    snarkjs >= 0.7.6
#    verification_key.json  (must be placed here by the image sender)
# =============================================================================

set -uo pipefail

# ── colour helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC}  $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERRORS=0

echo ""
echo "============================================================"
echo "  ZK-SNARK DICOM Steganography — Verifier Dependency Setup"
echo "============================================================"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
#  1. PYTHON >= 3.9
# ─────────────────────────────────────────────────────────────────────────────
echo "--- [1/4] Python 3.9+ ---"

_install_python() {
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            info "Installing Python via Homebrew..."
            brew install python@3.12
        else
            err "Homebrew not found. Install it from https://brew.sh then re-run."
            return 1
        fi
    elif command -v apt-get &>/dev/null; then
        info "Installing Python via apt..."
        sudo apt-get update -q
        sudo apt-get install -y python3 python3-pip python3-venv
    elif command -v dnf &>/dev/null; then
        info "Installing Python via dnf..."
        sudo dnf install -y python3 python3-pip
    elif command -v pacman &>/dev/null; then
        info "Installing Python via pacman..."
        sudo pacman -Sy --noconfirm python python-pip
    else
        err "Cannot detect package manager. Install Python 3.9+ manually from https://www.python.org/downloads/"
        return 1
    fi
}

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        _ver=$("$cmd" -c "import sys; print(sys.version_info.major*100+sys.version_info.minor)" 2>/dev/null || echo 0)
        if [ "$_ver" -ge 309 ]; then
            PYTHON="$cmd"
            ok "Found $("$cmd" --version 2>&1) (command: '$cmd')"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python 3.9+ not found. Attempting auto-install..."
    if _install_python; then
        for cmd in python3 python; do
            if command -v "$cmd" &>/dev/null; then
                _ver=$("$cmd" -c "import sys; print(sys.version_info.major*100+sys.version_info.minor)" 2>/dev/null || echo 0)
                if [ "$_ver" -ge 309 ]; then
                    PYTHON="$cmd"
                    ok "Python installed: $($cmd --version 2>&1)"
                    break
                fi
            fi
        done
    fi
    if [ -z "$PYTHON" ]; then
        err "Python 3.9+ unavailable after install attempt. Install manually: https://www.python.org/downloads/"
        ERRORS=$((ERRORS+1))
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
#  2. PYTHON PACKAGES (installed into .venv to avoid externally-managed-env)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- [2/4] Python packages ---"

if [ -n "$PYTHON" ]; then
    VENV_DIR="$SCRIPT_DIR/.venv"

    # Create virtualenv if it doesn't exist yet
    if [ ! -f "$VENV_DIR/bin/python" ]; then
        info "Creating virtual environment at .venv ..."
        "$PYTHON" -m venv "$VENV_DIR"
        if [ ! -f "$VENV_DIR/bin/python" ]; then
            err "venv creation failed. Try: sudo apt-get install python3-venv"
            ERRORS=$((ERRORS+1))
        fi
    else
        ok "Virtual environment exists (.venv)"
    fi

    # Switch to venv Python for all package operations
    PYTHON="$VENV_DIR/bin/python"

    # Map: package_name -> import_name
    declare -A PKG_MAP
    PKG_MAP=([pydicom]="pydicom" [Pillow]="PIL" [numpy]="numpy" [scipy]="scipy")
    MISSING=()

    for pkg in pydicom Pillow numpy scipy; do
        imp="${PKG_MAP[$pkg]}"
        if "$PYTHON" -c "import $imp" 2>/dev/null; then
            ok "  $pkg"
        else
            warn "  $pkg — not found"
            MISSING+=("$pkg")
        fi
    done

    if [ ${#MISSING[@]} -gt 0 ]; then
        info "Installing: ${MISSING[*]}"
        "$PYTHON" -m pip install --upgrade "${MISSING[@]}"
        # Re-verify
        for pkg in "${MISSING[@]}"; do
            imp="${PKG_MAP[$pkg]}"
            if "$PYTHON" -c "import $imp" 2>/dev/null; then
                ok "  $pkg installed"
            else
                err "  $pkg installation failed"
                ERRORS=$((ERRORS+1))
            fi
        done
    fi
else
    warn "Skipping Python package check (Python unavailable)."
fi

# ─────────────────────────────────────────────────────────────────────────────
#  3. NODE.JS >= 18
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- [3/4] Node.js 18+ ---"

_install_nodejs() {
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            info "Installing Node.js via Homebrew..."
            brew install node@20
            brew link --overwrite node@20 2>/dev/null || true
        else
            err "Homebrew not found. Install Node.js 18+ from https://nodejs.org"
            return 1
        fi
    elif command -v apt-get &>/dev/null; then
        info "Installing Node.js 20.x via NodeSource..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    elif command -v dnf &>/dev/null; then
        info "Installing Node.js 20.x via NodeSource..."
        curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
        sudo dnf install -y nodejs
    elif command -v pacman &>/dev/null; then
        info "Installing Node.js via pacman..."
        sudo pacman -Sy --noconfirm nodejs npm
    else
        err "Cannot detect package manager. Install Node.js 18+ from https://nodejs.org"
        return 1
    fi
}

NODE_OK=false
if command -v node &>/dev/null; then
    NODE_VER=$(node -e "process.stdout.write(process.version)" 2>/dev/null || echo "v0.0.0")
    NODE_MAJ=$(echo "$NODE_VER" | sed 's/v\([0-9]*\).*/\1/')
    if [ "${NODE_MAJ:-0}" -ge 18 ] 2>/dev/null; then
        ok "Node.js $NODE_VER"
        NODE_OK=true
    else
        warn "Node.js $NODE_VER found but version 18+ required. Attempting upgrade..."
        _install_nodejs || true
    fi
else
    warn "Node.js not found. Attempting auto-install..."
    _install_nodejs || true
fi

if ! $NODE_OK; then
    if command -v node &>/dev/null; then
        NODE_VER=$(node -e "process.stdout.write(process.version)" 2>/dev/null || echo "v0.0.0")
        NODE_MAJ=$(echo "$NODE_VER" | sed 's/v\([0-9]*\).*/\1/')
        if [ "${NODE_MAJ:-0}" -ge 18 ] 2>/dev/null; then
            ok "Node.js $NODE_VER"
            NODE_OK=true
        else
            err "Node.js $NODE_VER is still below v18. Install manually: https://nodejs.org/en/download"
            ERRORS=$((ERRORS+1))
        fi
    else
        err "Node.js unavailable after install attempt. Install manually: https://nodejs.org/en/download"
        ERRORS=$((ERRORS+1))
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
#  4. SNARKJS >= 0.7.6
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- [4/4] snarkjs 0.7.6+ ---"

_version_ge() {
    # Returns 0 (true) if version $1 >= $2, both in M.m.p form
    IFS='.' read -r a1 a2 a3 <<< "$1"
    IFS='.' read -r b1 b2 b3 <<< "$2"
    a1=${a1:-0}; a2=${a2:-0}; a3=${a3:-0}
    b1=${b1:-0}; b2=${b2:-0}; b3=${b3:-0}
    if   [ "$a1" -gt "$b1" ]; then return 0
    elif [ "$a1" -lt "$b1" ]; then return 1
    elif [ "$a2" -gt "$b2" ]; then return 0
    elif [ "$a2" -lt "$b2" ]; then return 1
    elif [ "$a3" -ge "$b3" ]; then return 0
    else return 1
    fi
}

_check_snarkjs_ver() {
    if command -v snarkjs &>/dev/null; then
        SJS_VER=$(snarkjs --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "0.0.0")
        if _version_ge "$SJS_VER" "0.7.6"; then
            ok "snarkjs $SJS_VER"
            return 0
        else
            warn "snarkjs $SJS_VER found but 0.7.6+ required."
            return 1
        fi
    fi
    return 1
}

if ! _check_snarkjs_ver; then
    info "Installing/upgrading snarkjs..."
    npm install -g snarkjs
    if ! _check_snarkjs_ver; then
        err "snarkjs installation failed. Try manually: npm install -g snarkjs"
        ERRORS=$((ERRORS+1))
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
#  5. VERIFICATION KEY CHECK
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "--- Verification artifacts ---"

KEY_FILE="$SCRIPT_DIR/circuits/compiled/build/chaos_zk_stego_verification_key.json"
if [ -f "$KEY_FILE" ]; then
    KEY_SIZE=$(wc -c < "$KEY_FILE" | tr -d ' ')
    ok "verification_key.json found ($KEY_SIZE bytes)"
else
    warn "verification_key.json not found at:"
    warn "  $KEY_FILE"
    warn "Obtain this file from the image sender and place it at the path above."
fi

CHAOS_KEY="$SCRIPT_DIR/chaos_key.txt"
if [ -f "$CHAOS_KEY" ]; then
    ok "chaos_key.txt found"
else
    warn "chaos_key.txt not found — required for full metadata extraction (authorized recipient)."
    warn "Not required for public-auditor ZK verification only."
fi

# ─────────────────────────────────────────────────────────────────────────────
#  SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}  All dependencies satisfied.${NC}"
    echo ""
    echo "  Public-auditor ZK verification:"
    echo "    python3 scripts/verify.py <stego_image.png>"
    echo ""
    echo "  Authorized recipient (metadata + RDH restore):"
    echo "    python3 scripts/dicom_extract.py <stego_image.png> --restore-output restored.png"
else
    echo -e "${RED}  Setup finished with $ERRORS error(s). Fix the issues above before proceeding.${NC}"
fi
echo "============================================================"
echo ""
exit $ERRORS
