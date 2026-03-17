#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_fig2_images.py — Generate three context images for Figure 2 of the manuscript.

Outputs (saved to docs/figs/):
  fig2a_original.png  — 8-bit normalized grayscale DICOM image
  fig2b_roi.png       — Binary ROI mask (white = tissue, black = background)
  fig2c_target.png    — Original image with 10-pixel border zone highlighted in orange

Usage:
  python scripts/generate_fig2_images.py
  python scripts/generate_fig2_images.py --dcm examples/dicom/1-04.dcm
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Make sure project root is on sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_stego.dicom_handler import DicomHandler


def normalize_to_uint8(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize a uint16 array to [0, 255] uint8."""
    arr = arr.astype(np.float32)
    mn, mx = arr.min(), arr.max()
    if mx == mn:
        return np.zeros(arr.shape, dtype=np.uint8)
    return ((arr - mn) / (mx - mn) * 255.0).astype(np.uint8)


def generate_fig2_images(dcm_path: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading DICOM: {dcm_path}")
    pixel_array, _, info = DicomHandler.load(dcm_path)
    print(f"  Image: {info['rows']}×{info['cols']} px, modality={info['modality']}")

    # ── (a) Original: 8-bit normalized grayscale ─────────────────────────────
    arr8 = normalize_to_uint8(pixel_array)
    img_a = Image.fromarray(arr8, mode='L')
    path_a = out_dir / "fig2a_original.png"
    img_a.save(path_a)
    print(f"  Saved: {path_a}")

    # ── (b) ROI mask: white=tissue, black=background ──────────────────────────
    # binary_fill_holes collapses internal speckle/holes into a clean solid
    # shape, giving a clear white-on-black illustration of the tissue region.
    # (The actual embedding code uses detect_roi() directly — unchanged.)
    from scipy.ndimage import binary_fill_holes, binary_erosion as _erode
    roi_solid = binary_fill_holes(DicomHandler.detect_roi(pixel_array))
    mask8 = (roi_solid.astype(np.uint8)) * 255
    img_b = Image.fromarray(mask8, mode='L')
    path_b = out_dir / "fig2b_roi.png"
    img_b.save(path_b)
    print(f"  Saved: {path_b}")

    # ── (c) Border zone: outer ring highlighted, anatomy visible ─────────────
    # Reuse the filled ROI so the border zone is a clean outer ring only.
    # (The actual embedding code uses detect_border_zone() directly, which
    # may include inner-hole boundary pixels — see dicom_handler.py.)
    core_solid = _erode(roi_solid, iterations=10)
    border_mask = roi_solid & ~core_solid

    # Build RGB image from 8-bit grayscale
    rgb = np.stack([arr8, arr8, arr8], axis=-1).astype(np.float32)   # H×W×3, [0,255]

    # Alpha-blend: 70% orange + 30% original grey at border pixels
    alpha = 0.70
    orange = np.array([255.0, 140.0, 0.0])
    rgb[border_mask] = alpha * orange + (1.0 - alpha) * rgb[border_mask]

    img_c = Image.fromarray(rgb.astype(np.uint8), mode='RGB')


    path_c = out_dir / "fig2c_target.png"
    img_c.save(path_c)
    print(f"  Saved: {path_c}")

    border_px = int(border_mask.sum())
    total_px  = pixel_array.size
    print(f"\nDone. Border zone: {border_px} / {total_px} px "
          f"({100 * border_px / total_px:.1f}%) — Me=10 erosion iterations.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate three context images for Figure 2 of the manuscript."
    )
    parser.add_argument(
        "--dcm",
        default=str(project_root / "examples" / "dicom" / "1-04.dcm"),
        help="Source DICOM file (default: examples/dicom/1-04.dcm)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(project_root / "docs" / "figs"),
        help="Output directory for generated PNG files (default: docs/figs)",
    )
    args = parser.parse_args()

    dcm_path = Path(args.dcm)
    if not dcm_path.exists():
        print(f"ERROR: DICOM file not found: {dcm_path}", file=sys.stderr)
        sys.exit(1)

    generate_fig2_images(str(dcm_path), Path(args.out_dir))


if __name__ == "__main__":
    main()
