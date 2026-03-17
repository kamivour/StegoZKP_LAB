#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_fig5_histograms.py — Generate Figure 5: histogram comparison (original vs stego).

Outputs (saved to docs/figs/):
  fig5a_hist_full.png  — Overlaid full-range 16-bit histograms
  fig5b_hist_zoom.png  — Zoomed-in view to reveal ±3 LSB jitter
"""

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_stego.dicom_handler import DicomHandler

DCM_PATH   = project_root / "examples" / "dicom" / "1-04.dcm"
STEGO_PATH = project_root / "examples" / "dicom" / "1-04_full_test.png"
OUT_DIR    = project_root / "docs" / "figs"

# Plot style constants
BLUE  = "#2196F3"   # original
RED   = "#F44336"   # stego
BG    = "#0d0d0d"
GRID  = "#2a2a2a"
TEXT  = "#e0e0e0"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.style.use("default")          # white background, black axes

    # ── Load images ───────────────────────────────────────────────────────────
    print("Loading original DICOM...")
    orig, _, info = DicomHandler.load(str(DCM_PATH))
    print(f"  {info['rows']}×{info['cols']}  modality={info['modality']}")

    print("Loading stego PNG...")
    stego = np.array(Image.open(str(STEGO_PATH)), dtype=np.uint16)
    assert stego.shape == orig.shape, "Shape mismatch"

    # ── Flatten and filter background (pixel == 0) ────────────────────────────
    orig_flat  = orig.flatten().astype(np.int32)
    stego_flat = stego.flatten().astype(np.int32)

    orig_tissue  = orig_flat[orig_flat   > 0]
    stego_tissue = stego_flat[stego_flat > 0]
    print(f"  Tissue pixels (orig):  {len(orig_tissue):,}")
    print(f"  Tissue pixels (stego): {len(stego_tissue):,}")

    # ── Active data range for fig5a ───────────────────────────────────────────
    min_active = int(min(orig_tissue.min(), stego_tissue.min()))
    max_active = int(max(orig_tissue.max(), stego_tissue.max()))
    print(f"  Active range: [{min_active}, {max_active}]")

    # ── Auto-detect zoom centre from modified pixels ───────────────────────────
    diff_mask   = orig_flat != stego_flat
    diff_vals   = orig_flat[diff_mask]
    zoom_centre = int(np.median(diff_vals)) if len(diff_vals) else int(np.median(orig_tissue))
    print(f"  Modified pixels: {diff_mask.sum():,}, median intensity={zoom_centre}")
    ZOOM_HALF = 25
    zoom_lo   = max(zoom_centre - ZOOM_HALF, 0)
    zoom_hi   = zoom_centre + ZOOM_HALF
    print(f"  Zoom window: [{zoom_lo}, {zoom_hi}]")

    # ── (a) Full histogram — bounded to active data range ─────────────────────
    fig_a, ax_a = plt.subplots(figsize=(6, 3.5), dpi=300)

    n_bins_full = 512
    ax_a.hist(orig_tissue,  bins=n_bins_full,
              range=(min_active, max_active),
              histtype="step", color="#1565C0", linewidth=1.0,
              alpha=0.9, label="Original")
    ax_a.hist(stego_tissue, bins=n_bins_full,
              range=(min_active, max_active),
              histtype="step", color="#C62828", linewidth=1.0,
              linestyle="--", alpha=0.85, label="Stego")

    ax_a.set_xlim(32740, 33200)
    ax_a.set_xlabel("Pixel Intensity (16-bit)", fontsize=9)
    ax_a.set_ylabel("Frequency", fontsize=9)
    ax_a.legend(fontsize=8, framealpha=0.9)
    ax_a.grid(True, linewidth=0.4, linestyle="--", alpha=0.5)
    ax_a.tick_params(labelsize=8)
    fig_a.tight_layout()

    path_a = OUT_DIR / "fig5a_hist_full.png"
    fig_a.savefig(str(path_a), dpi=300, bbox_inches="tight")
    plt.close(fig_a)
    print(f"  Saved: {path_a}")

    # ── (b) Zoomed histogram — exact 1-bin-per-value ──────────────────────────
    n_bins_zoom = zoom_hi - zoom_lo      # 1 bin per integer value

    fig_b, ax_b = plt.subplots(figsize=(6, 3.5), dpi=300)

    ax_b.hist(orig_flat,  bins=n_bins_zoom, range=(zoom_lo, zoom_hi),
              histtype="step", color="#1565C0", linewidth=1.2,
              alpha=0.9, label="Original")
    ax_b.hist(stego_flat, bins=n_bins_zoom, range=(zoom_lo, zoom_hi),
              histtype="step", color="#C62828", linewidth=1.2,
              linestyle="--", alpha=0.85, label="Stego")
    ax_b.axvspan(zoom_centre - 3, zoom_centre + 3,
                 alpha=0.10, color="#555555",
                 label=r"$\pm$3 LSB jitter band")

    ax_b.set_xlim(32760, 32800)
    ax_b.set_xlabel("Pixel Intensity (16-bit)", fontsize=9)
    ax_b.set_ylabel("Frequency", fontsize=9)
    ax_b.legend(fontsize=8, framealpha=0.9)
    ax_b.grid(True, linewidth=0.4, linestyle="--", alpha=0.5)
    ax_b.tick_params(labelsize=8)
    fig_b.tight_layout()

    path_b = OUT_DIR / "fig5b_hist_zoom.png"
    fig_b.savefig(str(path_b), dpi=300, bbox_inches="tight")
    plt.close(fig_b)
    print(f"  Saved: {path_b}")

    print("\nDone.")


if __name__ == "__main__":
    main()

