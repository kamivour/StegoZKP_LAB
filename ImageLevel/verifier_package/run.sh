#!/usr/bin/env bash
# =============================================================================
#  ZK-SNARK DICOM Steganography — Single-Command Verifier Entry Point
# =============================================================================
#  Usage:
#    ./run.sh                        # auto-detects stego image in sent_image/
#    ./run.sh path/to/stego.png      # specify image explicitly
#    ./run.sh path/to/stego.png -v   # verbose output
#    ./run.sh path/to/stego.png --json  # JSON output
#
#  This script:
#    1. Checks and installs all dependencies (Python, Node.js, snarkjs, packages)
#    2. Auto-detects the stego image if none is provided
#    3. Runs ZK proof verification (+ metadata extraction if chaos_key.txt present)
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 1 — Dependency setup
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Phase 1: Dependency check"
echo "============================================================"

bash "$SCRIPT_DIR/setup.sh"
SETUP_EXIT=$?

if [ $SETUP_EXIT -ne 0 ]; then
    echo ""
    echo "ERROR: Setup phase failed with $SETUP_EXIT error(s)."
    echo "Fix the issues above and re-run: ./run.sh"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 2 — Locate stego image
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Phase 2: Locating stego image"
echo "============================================================"

IMAGE="${1:-}"
EXTRA_ARGS="${@:2}"   # any extra flags like -v or --json

if [ -n "$IMAGE" ]; then
    if [ ! -f "$IMAGE" ]; then
        # Try relative to script dir
        if [ -f "$SCRIPT_DIR/$IMAGE" ]; then
            IMAGE="$SCRIPT_DIR/$IMAGE"
        else
            echo "ERROR: Image not found: $IMAGE"
            exit 1
        fi
    fi
    echo "Using specified image: $IMAGE"
else
    # Auto-detect: pick first PNG in sent_image/
    SENT_DIR="$SCRIPT_DIR/sent_image"
    if [ -d "$SENT_DIR" ]; then
        IMAGE=$(find "$SENT_DIR" -maxdepth 1 -name "*.png" 2>/dev/null | sort | head -1)
    fi
    if [ -z "$IMAGE" ]; then
        echo "No stego image found."
        echo "Either:"
        echo "  - Place a stego PNG in:  $SCRIPT_DIR/sent_image/"
        echo "  - Or run:                ./run.sh path/to/stego.png"
        exit 1
    fi
    echo "Auto-detected: $(basename "$IMAGE")"
fi

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 3 — Verify (and extract if chaos_key.txt present)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Phase 3: ZK verification + extraction"
echo "============================================================"

# Prefer the venv created by setup.sh (avoids externally-managed-env issues)
PYTHON=""
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    # Fallback: scan system for Python 3.9+
    for cmd in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            _ver=$("$cmd" -c "import sys; print(sys.version_info.major*100+sys.version_info.minor)" 2>/dev/null || echo 0)
            if [ "$_ver" -ge 309 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.9+ not found even after setup. Re-open your terminal and retry."
    exit 1
fi

VERIFY_SCRIPT="$SCRIPT_DIR/scripts/verify.py"
if [ ! -f "$VERIFY_SCRIPT" ]; then
    echo "ERROR: verify.py not found at: $VERIFY_SCRIPT"
    exit 1
fi

echo "Image:  $IMAGE"
echo "Script: $VERIFY_SCRIPT"
echo ""

# Run verification — passes through any extra args (-v, --json, etc.)
"$PYTHON" "$VERIFY_SCRIPT" "$IMAGE" $EXTRA_ARGS
EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  Done."
else
    echo "  Verification returned exit code $EXIT_CODE."
fi
echo "============================================================"
echo ""
exit $EXIT_CODE
