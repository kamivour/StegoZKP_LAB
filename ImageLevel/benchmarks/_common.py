"""
benchmarks/_common.py
---------------------
Shared helpers imported by every benchmark script.

Run all benchmarks from the ImageLevel/ directory:
    python benchmarks/b1_quality.py
"""

import gzip
import json
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pydicom
from PIL import Image

# ---------------------------------------------------------------------------
# Path bootstrap — must come before any src.* import
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent          # …/ImageLevel/
BENCH_DIR = ROOT / "benchmarks"
RESULTS_DIR = BENCH_DIR / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Lazy imports (after path setup)
# ---------------------------------------------------------------------------
from src.zk_stego.dicom_handler import DicomHandler, DicomStego, DEFAULT_PROOF_KEY
from src.zk_stego.utils import generate_chaos_key_from_secret

# ---------------------------------------------------------------------------
# Test dataset
# ---------------------------------------------------------------------------
DICOM_DIR = ROOT / "examples" / "dicom"
DICOM_FILES = sorted(DICOM_DIR.glob("*.dcm"))

if not DICOM_FILES:
    print(f"WARNING: no .dcm files found in {DICOM_DIR}")


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def load_chaos_key() -> str:
    """Read chaos_key.txt from ImageLevel/."""
    p = ROOT / "chaos_key.txt"
    if not p.exists():
        raise FileNotFoundError(
            f"chaos_key.txt not found at {p}. "
            "Create it with your secret key string."
        )
    return p.read_text().strip()


def stego_path_noproof(dcm: Path) -> Path:
    return RESULTS_DIR / f"{dcm.stem}_noproof.png"


def stego_path_zk(dcm: Path) -> Path:
    return RESULTS_DIR / f"{dcm.stem}_zk.png"


def ensure_stego_noproof(dcm: Path, verbose: bool = False) -> Path:
    """
    Ensure a no-proof stego PNG exists for *dcm*.
    Generates it on first call (fast, ~0.3 s).
    Returns the path to the PNG.
    """
    out = stego_path_noproof(dcm)
    if out.exists():
        return out
    print(f"  [setup] Generating no-proof stego for {dcm.name} …", end=" ", flush=True)
    t0 = time.perf_counter()
    DicomStego(project_root=str(ROOT)).embed(
        str(dcm), str(out),
        chaos_key=load_chaos_key(),
        proof_key=DEFAULT_PROOF_KEY,
        generate_zk_proof=False,
        verbose=verbose,
    )
    print(f"done ({time.perf_counter()-t0:.2f} s)")
    return out


def ensure_stego_zk(dcm: Path, verbose: bool = False) -> Path:
    """
    Ensure a ZK-proof stego PNG exists for *dcm*.
    Generates it on first call (SLOW, ~30–120 s).
    Returns the path to the PNG.
    """
    out = stego_path_zk(dcm)
    if out.exists():
        return out
    print(f"  [setup] Generating ZK stego for {dcm.name} … (this may take 30–120 s)", flush=True)
    t0 = time.perf_counter()
    DicomStego(project_root=str(ROOT)).embed(
        str(dcm), str(out),
        chaos_key=load_chaos_key(),
        proof_key=DEFAULT_PROOF_KEY,
        generate_zk_proof=True,
        verbose=verbose,
    )
    print(f"  [setup] ZK stego done ({time.perf_counter()-t0:.1f} s)")
    return out


# ---------------------------------------------------------------------------
# Array helpers
# ---------------------------------------------------------------------------

def load_cover(dcm: Path) -> np.ndarray:
    """Load DICOM as uint16 array (H × W)."""
    return DicomHandler.to_uint16(pydicom.dcmread(str(dcm)).pixel_array)


def load_stego(png: Path) -> np.ndarray:
    """Load 16-bit stego PNG as uint16 array (H × W)."""
    return np.array(Image.open(str(png)), dtype=np.uint16)


def payload_bits(dcm: Path) -> int:
    """Return number of bits embedded (gzip-compressed metadata length × 8)."""
    _, metadata_json, _ = DicomHandler.load(str(dcm))
    compressed = gzip.compress(metadata_json.encode("utf-8"), compresslevel=9)
    return len(compressed) * 8


# ---------------------------------------------------------------------------
# Results I/O
# ---------------------------------------------------------------------------

def save_results(filename: str, data: dict) -> Path:
    out = RESULTS_DIR / filename
    out.write_text(json.dumps(data, indent=2, default=str))
    print(f"  Saved → benchmarks/results/{filename}")
    return out


def load_results(filename: str) -> Optional[dict]:
    p = RESULTS_DIR / filename
    if p.exists():
        return json.loads(p.read_text())
    return None


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------

class Timer:
    """Context manager → elapsed seconds stored in .elapsed."""
    def __enter__(self):
        self._t = time.perf_counter()
        return self
    def __exit__(self, *_):
        self.elapsed = time.perf_counter() - self._t


# ---------------------------------------------------------------------------
# Matplotlib style
# ---------------------------------------------------------------------------

def apply_paper_style() -> None:
    """Apply a clean, publication-quality matplotlib style to all subsequent figures."""
    import matplotlib.pyplot as plt
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except OSError:
        try:
            plt.style.use("seaborn-whitegrid")
        except OSError:
            plt.style.use("ggplot")
    plt.rcParams.update({
        "font.family":      "DejaVu Sans",
        "font.size":        11,
        "axes.titlesize":   12,
        "axes.labelsize":   11,
        "xtick.labelsize":  9,
        "ytick.labelsize":  9,
        "legend.fontsize":  10,
        "figure.dpi":       150,
        "lines.linewidth":  1.8,
        "lines.markersize": 6,
        "axes.spines.top":  False,
        "axes.spines.right": False,
    })
