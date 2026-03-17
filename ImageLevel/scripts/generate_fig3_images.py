#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_fig3_images.py — Generate three images for Figure 3 (stego visual comparison).

Outputs (saved to docs/figs/):
  fig3a_original.png  — Original 16-bit DICOM image (display-normalized)
  fig3b_stego.png     — Stego 16-bit PNG (same normalization as (a))
  fig3c_diff.png      — |original - stego| × 1000, display-normalized

Usage:
  python scripts/generate_fig3_images.py
  python scripts/generate_fig3_images.py --dcm examples/dicom/1-04.dcm \\
                                          --stego examples/dicom/1-04_full_test.png
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_stego.dicom_handler import DicomHandler


def normalize_to_uint8(arr: np.ndarray,
                       vmin: float = None, vmax: float = None) -> np.ndarray:
    """Min-max normalize to [0, 255] uint8, clipping to [vmin, vmax]."""
    a = arr.astype(np.float32)
    mn = float(a.min()) if vmin is None else vmin
    mx = float(a.max()) if vmax is None else vmax
    if mx == mn:
        return np.zeros(a.shape, dtype=np.uint8)
    return np.clip((a - mn) / (mx - mn) * 255.0, 0, 255).astype(np.uint8)


def generate_fig3_images(dcm_path: str, stego_path: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Load original DICOM ───────────────────────────────────────────────────
    print(f"Loading DICOM  : {dcm_path}")
    orig, _, info = DicomHandler.load(dcm_path)
    print(f"  Size: {info['rows']}×{info['cols']}  modality={info['modality']}")

    # ── Load stego PNG (16-bit grayscale) ─────────────────────────────────────
    print(f"Loading stego  : {stego_path}")
    stego = np.array(Image.open(stego_path), dtype=np.uint16)
    if stego.shape != orig.shape:
        raise ValueError(
            f"Shape mismatch: original {orig.shape} vs stego {stego.shape}"
        )

    # ── Shared normalisation scale (from original) ────────────────────────────
    vmin, vmax = float(orig.min()), float(orig.max())

    # ── (a) Original ──────────────────────────────────────────────────────────
    img_a = Image.fromarray(normalize_to_uint8(orig, vmin, vmax), mode='L')
    path_a = out_dir / "fig3a_original.png"
    img_a.save(path_a)
    print(f"  Saved: {path_a}")

    # ── (b) Stego ────────────────────────────────────────────────────────────
    img_b = Image.fromarray(normalize_to_uint8(stego, vmin, vmax), mode='L')
    path_b = out_dir / "fig3b_stego.png"
    img_b.save(path_b)
    print(f"  Saved: {path_b}")

    # ── (c) Amplified absolute difference ─────────────────────────────────────
    # Cast to int32 first to prevent uint16 underflow on subtraction.
    diff = np.abs(orig.astype(np.int32) - stego.astype(np.int32)) * 1000
    nonzero = int((diff > 0).sum())
    print(f"  Nonzero diff pixels: {nonzero} / {orig.size} "
          f"({100 * nonzero / orig.size:.2f}%)")
    print(f"  Max diff (pre-amp): {int(np.abs(orig.astype(np.int32) - stego.astype(np.int32)).max())}")

    # Normalise diff for display: clip to uint8 (values >255 clamp to white)
    diff_u8 = np.clip(diff, 0, 65535)
    diff_display = normalize_to_uint8(diff_u8)
    img_c = Image.fromarray(diff_display, mode='L')
    path_c = out_dir / "fig3c_diff.png"
    img_c.save(path_c)
    print(f"  Saved: {path_c}")

    print("\nDone.")


def main() -> None:
    default_dcm   = str(project_root / "examples" / "dicom" / "1-04.dcm")
    default_stego = str(project_root / "examples" / "dicom" / "1-04_full_test.png")

    parser = argparse.ArgumentParser(
        description="Generate Figure 3 stego-comparison images."
    )
    parser.add_argument("--dcm",   default=default_dcm,
                        help="Source DICOM file")
    parser.add_argument("--stego", default=default_stego,
                        help="Corresponding stego PNG (16-bit grayscale)")
    parser.add_argument("--out-dir",
                        default=str(project_root / "docs" / "figs"),
                        help="Output directory (default: docs/figs)")
    args = parser.parse_args()

    for p in (args.dcm, args.stego):
        if not Path(p).exists():
            print(f"ERROR: File not found: {p}", file=sys.stderr)
            sys.exit(1)

    generate_fig3_images(args.dcm, args.stego, Path(args.out_dir))


if __name__ == "__main__":
    main()
