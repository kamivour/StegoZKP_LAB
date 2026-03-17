#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_fig4_rdh_map.py — Generate Figure 4: RDH region map overlay.

Uses the exact same position-generation logic as DicomStego.embed() to derive
the four non-overlapping region coordinate arrays from the border zone, then
plots them as a color-coded overlay on the original grayscale image.

Output: docs/figs/rdh_regions_fig.png

Usage:
  python scripts/generate_fig4_rdh_map.py
"""

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from PIL import Image

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_stego.dicom_handler import (
    DicomHandler, DicomStego,
    DEFAULT_PROOF_KEY,
    BORDER_EROSION_ITERATIONS,
    BACKGROUND_PERCENTILE,
    _positions_needed,
    HEADER_SIZE, BITS_PER_PIXEL,
)
from src.zk_stego.utils import generate_chaos_key_from_secret

# ── Configuration ─────────────────────────────────────────────────────────────
DCM_PATH   = project_root / "examples" / "dicom" / "1-04.dcm"
STEGO_PATH = project_root / "examples" / "dicom" / "1-04_full_test.png"
KEY_FILE   = project_root / "chaos_key.txt"
OUT_PATH   = project_root / "docs" / "figs" / "rdh_regions_fig.png"

# Region colours (RGBA, fully opaque — overlaid with alpha in imshow)
COLOURS = {
    "proof\\_data":  (0.0,  0.9,  1.0),   # cyan
    "proof\\_undo": (1.0,  0.2,  0.2),   # red
    "meta\\_data":  (0.2,  1.0,  0.2),   # green
    "meta\\_undo":  (1.0,  0.9,  0.0),   # yellow
}

REGION_ORDER = ["proof\\_data", "proof\\_undo", "meta\\_data", "meta\\_undo"]

# ── Realistic payload sizes (match the actual embedded test) ──────────────────
# Proof block: 84-byte header + ~984 bytes proof/public = ~1068 bytes → 8544 bits
PROOF_BITS   = (84 + 984) * 8          # 8544 bits
N_PROOF_DATA = _positions_needed(PROOF_BITS)   # 4272 positions

# Meta payload: gzip-compressed metadata ~2.5 KB = 20000 bits
META_BITS    = 20_000
N_META_DATA  = _positions_needed(META_BITS)    # 10000 positions


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # ── Load DICOM ────────────────────────────────────────────────────────────
    chaos_key = KEY_FILE.read_text(encoding="utf-8").strip()
    print(f"Chaos key   : {chaos_key!r}")

    pixel_array, _, info = DicomHandler.load(str(DCM_PATH))
    height, width = pixel_array.shape
    print(f"Image       : {height}×{width}  modality={info['modality']}")

    # ── Detect border zone ────────────────────────────────────────────────────
    roi_mask = DicomHandler.detect_border_zone(
        pixel_array,
        erosion_iterations=BORDER_EROSION_ITERATIONS,
        background_percentile=BACKGROUND_PERCENTILE,
    )
    border_count = int(roi_mask.sum())
    print(f"Border zone : {border_count} pixels")

    # ── Derive positions (same logic as DicomStego.embed) ────────────────────
    stego = DicomStego()

    proof_key_int  = generate_chaos_key_from_secret(DEFAULT_PROOF_KEY)
    chaos_key_int  = generate_chaos_key_from_secret(chaos_key)

    pk_x0, pk_y0   = stego._key_start(proof_key_int, width, height, roi_mask)
    meta_x0, meta_y0 = stego._key_start(chaos_key_int, width, height, roi_mask)

    # 1. proof_data
    proof_data = stego._roi_positions(
        pixel_array, roi_mask, pk_x0, pk_y0, proof_key_int,
        N_PROOF_DATA, sort_by_entropy=False, exclude=None,
    )
    proof_data_set = set(map(tuple, proof_data))
    print(f"proof_data  : {len(proof_data)} positions")

    # 2. proof_undo  (non-overlapping with proof_data)
    proof_undo = stego._roi_positions(
        pixel_array, roi_mask, pk_x0, pk_y0, proof_key_int,
        N_PROOF_DATA, sort_by_entropy=False, exclude=proof_data_set,
    )
    proof_undo_set = set(map(tuple, proof_undo))
    proof_all_set  = proof_data_set | proof_undo_set
    print(f"proof_undo  : {len(proof_undo)} positions")

    # 3. meta_data  (non-overlapping with both proof regions)
    meta_data = stego._roi_positions(
        pixel_array, roi_mask, meta_x0, meta_y0, chaos_key_int,
        N_META_DATA, sort_by_entropy=True, exclude=proof_all_set,
    )
    meta_data_set = set(map(tuple, meta_data))
    print(f"meta_data   : {len(meta_data)} positions")

    # 4. meta_undo  (non-overlapping with everything)
    meta_undo = stego._roi_positions(
        pixel_array, roi_mask, meta_x0, meta_y0, chaos_key_int,
        N_META_DATA, sort_by_entropy=True,
        exclude=proof_all_set | meta_data_set,
    )
    print(f"meta_undo   : {len(meta_undo)} positions")

    # ── Verify non-overlap ────────────────────────────────────────────────────
    all_sets = [proof_data_set, proof_undo_set, meta_data_set, set(map(tuple, meta_undo))]
    total = sum(len(s) for s in all_sets)
    union = len(set.union(*all_sets))
    assert total == union, f"OVERLAP DETECTED: {total} positions but union has {union}"
    print(f"Non-overlap : VERIFIED ({total} positions, union={union})")

    # ── Prepare display data ──────────────────────────────────────────────────
    arr = pixel_array.astype(np.float32)
    arr8 = ((arr - arr.min()) / (arr.max() - arr.min()) * 255).astype(np.uint8)

    # Filled outer ring for display (same logic as Fig 2b/c)
    from scipy.ndimage import (binary_fill_holes, binary_erosion as _erode,
                               binary_dilation)
    roi_filled   = binary_fill_holes(DicomHandler.detect_roi(pixel_array))
    core_filled  = _erode(roi_filled, iterations=BORDER_EROSION_ITERATIONS)
    display_ring = roi_filled & ~core_filled

    regions = {
        "proof_data":  proof_data,
        "proof_undo":  proof_undo,
        "meta_data":   meta_data,
        "meta_undo":   meta_undo,
    }
    # Map names to display names and colours
    DISP = {
        "proof_data": ((0.0, 0.9, 1.0), "proof\_data"),   # cyan
        "proof_undo": ((1.0, 0.2, 0.2), "proof\_undo"),   # red
        "meta_data":  ((0.2, 1.0, 0.2), "meta\_data"),    # green
        "meta_undo":  ((1.0, 0.9, 0.0), "meta\_undo"),    # yellow
    }

    # ── Build per-region boolean masks ────────────────────────────────────────
    masks = {}
    for name, positions in regions.items():
        m = np.zeros((height, width), dtype=bool)
        for x, y in positions:
            if display_ring[y, x]:
                m[y, x] = True
        masks[name] = m

    # ── Dilated RGBA overlay for main image ───────────────────────────────────
    struct = np.ones((3, 3), dtype=bool)       # 3×3 square — subtle thickening
    overlay_main = np.zeros((height, width, 4), dtype=np.float32)
    for name, m in masks.items():
        colour, _ = DISP[name]
        dilated = binary_dilation(m, structure=struct)
        # Only paint within the (slightly expanded) ring, not beyond
        dilated &= roi_filled
        r, g, b = colour
        overlay_main[dilated, 0] = r
        overlay_main[dilated, 1] = g
        overlay_main[dilated, 2] = b
        overlay_main[dilated, 3] = 0.90

    # ── Auto-select zoom window: top edge of the border ring ─────────────────
    ring_ys, ring_xs = np.where(display_ring)
    y_top = int(ring_ys.min())
    x_mid = int(np.median(ring_xs[ring_ys == y_top]))
    ZOOM = 50                          # 50×50 pixel inset
    half = ZOOM // 2
    zy0 = max(y_top - 5,    0)         # include a few rows above the ring
    zy1 = min(zy0 + ZOOM,   height)
    zx0 = max(x_mid - half, 0)
    zx1 = min(zx0 + ZOOM,   width)
    # Adjust if clipped
    if zx1 - zx0 < ZOOM:
        zx0 = max(0, zx1 - ZOOM)
    print(f"Zoom window : rows {zy0}–{zy1}, cols {zx0}–{zx1}")

    # Raw (un-dilated) RGBA overlay for inset — exact 1×1 pixel positions
    overlay_inset = np.zeros((height, width, 4), dtype=np.float32)
    for name, m in masks.items():
        colour, _ = DISP[name]
        r, g, b = colour
        overlay_inset[m, 0] = r
        overlay_inset[m, 1] = g
        overlay_inset[m, 2] = b
        overlay_inset[m, 3] = 1.0

    # ── Figure layout: main + inset axes ─────────────────────────────────────
    from mpl_toolkits.axes_grid1.inset_locator import mark_inset, inset_axes
    import matplotlib.ticker as ticker

    fig, ax_main = plt.subplots(figsize=(7, 7), dpi=300,
                                facecolor="#0a0a0a")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Main image
    ax_main.imshow(arr8, cmap="gray", interpolation="nearest",
                   vmin=0, vmax=255)
    ax_main.imshow(overlay_main, interpolation="nearest")
    ax_main.set_facecolor("#0a0a0a")
    ax_main.axis("off")


    # Inset axes (upper-left corner of the figure)
    ax_ins = inset_axes(ax_main, width="38%", height="38%",
                        loc="upper left",
                        bbox_to_anchor=(0.01, 0.01, 1, 1),
                        bbox_transform=ax_main.transAxes,
                        borderpad=0)
    ax_ins.imshow(arr8[zy0:zy1, zx0:zx1], cmap="gray",
                  interpolation="nearest", vmin=0, vmax=255,
                  extent=[zx0, zx1, zy1, zy0])
    ax_ins.imshow(overlay_inset[zy0:zy1, zx0:zx1],
                  interpolation="nearest",
                  extent=[zx0, zx1, zy1, zy0])
    ax_ins.set_xlim(zx0, zx1)
    ax_ins.set_ylim(zy1, zy0)
    ax_ins.set_facecolor("#0a0a0a")
    for spine in ax_ins.spines.values():
        spine.set_edgecolor("white")
        spine.set_linewidth(1.2)
    ax_ins.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)
    ax_ins.set_title("Zoom (1×1 px, exact)", fontsize=7,
                      color="white", pad=3)

    # Connecting box + lines from main image to inset
    mark_inset(ax_main, ax_ins,
               loc1=1, loc2=4,           # corners: top-right→bottom-right
               fc="none", ec="white",
               lw=0.8, alpha=0.7)

    # Rectangle on main image showing the zoom region
    from matplotlib.patches import Rectangle
    rect = Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0,
                     linewidth=1.0, edgecolor="white",
                     facecolor="none", linestyle="--", alpha=0.8)
    ax_main.add_patch(rect)

    # Legend
    patches = [
        mpatches.Patch(color=DISP[k][0],
                       label=DISP[k][1].replace("\_", "_"))
        for k in ["proof_data", "proof_undo", "meta_data", "meta_undo"]
    ]
    ax_main.legend(
        handles=patches,
        loc="lower right",
        fontsize=20,
        framealpha=0.85,
        edgecolor="#555555",
        facecolor="#111111",
        labelcolor="white",
    )

    plt.savefig(str(OUT_PATH), dpi=300, bbox_inches="tight",
                facecolor="#0a0a0a", edgecolor="none")
    plt.close()
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()

