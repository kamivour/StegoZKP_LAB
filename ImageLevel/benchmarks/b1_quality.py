"""
benchmarks/b1_quality.py  —  §1 Image Quality Metrics
======================================================
Measures PSNR, SSIM, MSE, BPP for each test DICOM and produces:
  - results/b1_quality.json      (per-image + summary statistics)
  - results/figures/b1_histogram_<stem>.pdf
  - results/figures/b1_lsb_planes_<stem>.pdf

Run from ImageLevel/:
    python benchmarks/b1_quality.py

Dependencies: numpy, Pillow, pydicom, scikit-image, matplotlib (all in requirements.txt)
"""

import sys
from pathlib import Path
import numpy as np

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import (
    DICOM_FILES, FIGURES_DIR,
    load_cover, load_stego, payload_bits,
    ensure_stego_noproof, save_results,
    apply_paper_style,
)

import matplotlib
matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt

from skimage.metrics import (
    peak_signal_noise_ratio as psnr,
    structural_similarity   as ssim,
    mean_squared_error      as mse,
)


# ---------------------------------------------------------------------------
# Per-image metrics
# ---------------------------------------------------------------------------

def compute_metrics(cover: np.ndarray, stego: np.ndarray, n_payload_bits: int) -> dict:
    """
    Compute PSNR, SSIM, MSE, BPP for a cover/stego pair.

    All skimage functions are called with data_range=65535 (16-bit images).
    Default data_range=1.0 or 255 would give wrong PSNR values.
    """
    assert cover.shape == stego.shape, "Cover and stego shapes must match"
    assert cover.dtype == np.uint16 and stego.dtype == np.uint16

    cover_f = cover.astype(np.float64)
    stego_f = stego.astype(np.float64)

    mse_val   = float(np.mean((cover_f - stego_f) ** 2))
    psnr_val  = float(psnr(cover, stego, data_range=65535))
    ssim_val  = float(ssim(cover, stego, data_range=65535))
    h, w      = cover.shape
    bpp_val   = n_payload_bits / (h * w)
    max_diff  = int(np.max(np.abs(cover.astype(np.int32) - stego.astype(np.int32))))

    return {
        "height": h,
        "width":  w,
        "pixels": h * w,
        "payload_bits": n_payload_bits,
        "payload_bytes": n_payload_bits // 8,
        "BPP":     round(bpp_val,  6),
        "MSE":     round(mse_val,  4),
        "PSNR_dB": round(psnr_val, 4),
        "SSIM":    round(ssim_val, 6),
        "max_pixel_diff": max_diff,
    }


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def plot_histogram(cover: np.ndarray, stego: np.ndarray, stem: str) -> Path:
    """
    Two-panel histogram:
      Left  — full uint16 range (0–65535, 256 bins) showing where the MR
              signal band sits within the complete 16-bit space.
      Right — zoomed into the active data range [cover.min(), cover.max()]
              with 256 bins so cover/stego overlap is clearly visible.

    Together the panels answer two different questions:
      "Where does the data live?" and "Did embedding shift the distribution?"
    """
    out = FIGURES_DIR / f"b1_histogram_{stem}.pdf"

    lo = int(cover.ravel().min())
    hi = int(cover.ravel().max())

    bins_full = np.linspace(0, 65536, 257)                         # 256 bins over full range
    bins_zoom = np.linspace(lo, hi + 1, min(257, hi - lo + 2))    # up to 256 bins, active range

    fig, (ax_full, ax_zoom) = plt.subplots(1, 2, figsize=(12, 3.5))

    # ── Left: full range ────────────────────────────────────────────────────
    ax_full.hist(cover.ravel(), bins=bins_full, alpha=0.65,
                 label="Cover", color="steelblue", density=True)
    ax_full.hist(stego.ravel(), bins=bins_full, alpha=0.65,
                 label="Stego", color="crimson",   density=True)
    ax_full.set_xlim(0, 65535)
    ax_full.set_xlabel("Pixel value (full uint16 range 0–65535)")
    ax_full.set_ylabel("Density")
    ax_full.set_title("Full 16-bit range")
    ax_full.legend(frameon=False)
    # Annotate the active band
    ax_full.axvspan(lo, hi, alpha=0.12, color="gold", label=f"Active band [{lo}–{hi}]")
    ax_full.legend(frameon=False, fontsize=8)

    # ── Right: zoomed active range ───────────────────────────────────────────
    ax_zoom.hist(cover.ravel(), bins=bins_zoom, alpha=0.65,
                 label="Cover", color="steelblue", density=True)
    ax_zoom.hist(stego.ravel(), bins=bins_zoom, alpha=0.65,
                 label="Stego", color="crimson",   density=True)
    ax_zoom.set_xlabel(f"Pixel value (active range {lo}–{hi})")
    ax_zoom.set_ylabel("Density")
    ax_zoom.set_title("Active data range (zoomed)")
    ax_zoom.legend(frameon=False)

    fig.suptitle(f"Pixel-value histogram — {stem}", fontsize=12)
    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


def plot_lsb_planes(cover: np.ndarray, stego: np.ndarray, stem: str) -> Path:
    """
    2×2 grid: cover bit-0, cover bit-1, stego bit-0, stego bit-1.

    A random-looking (high-entropy) LSB plane confirms the embedding is
    dispersed across the image, not sequential.
    """
    out = FIGURES_DIR / f"b1_lsb_planes_{stem}.pdf"

    cover_b0 = (cover & 1).astype(np.float32)
    cover_b1 = ((cover >> 1) & 1).astype(np.float32)
    stego_b0 = (stego & 1).astype(np.float32)
    stego_b1 = ((stego >> 1) & 1).astype(np.float32)

    fig, axes = plt.subplots(2, 2, figsize=(8, 8))
    panels = [
        (cover_b0, "Cover — bit 0"),
        (cover_b1, "Cover — bit 1"),
        (stego_b0, "Stego — bit 0"),
        (stego_b1, "Stego — bit 1"),
    ]
    for ax, (plane, title) in zip(axes.flat, panels):
        ax.imshow(plane, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
        ax.set_title(title)
        ax.axis("off")
    fig.suptitle(f"LSB bit planes — {stem}")
    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


def plot_quality_lines(results: list) -> Path:
    """Line chart of PSNR, SSIM, MSE, BPP per image across the test dataset."""
    out = FIGURES_DIR / "b1_quality_trends.pdf"
    stems  = [r["image"] for r in results]
    x      = np.arange(len(stems))

    metrics = [
        ("PSNR_dB", "PSNR (dB)",  "steelblue"),
        ("SSIM",    "SSIM",        "#2ca02c"),
        ("MSE",     "MSE",         "crimson"),
        ("BPP",     "BPP",         "#ff7f0e"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(10, 6), sharex=True)
    for ax, (key, label, colour) in zip(axes.flat, metrics):
        vals = [r[key] for r in results]
        ax.plot(x, vals, "o-", color=colour, lw=1.6, ms=5)
        ax.set_ylabel(label)
        ax.set_xticks(x)
        ax.set_xticklabels(stems, rotation=40, ha="right", fontsize=7)
        ylo, yhi = min(vals), max(vals)
        pad = max((yhi - ylo) * 0.1, 1e-6)
        ax.set_ylim(ylo - pad, yhi + pad)
        ax.set_title(label, fontsize=11)

    fig.suptitle("Image Quality Metrics per test DICOM", fontsize=12)
    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> dict:
    apply_paper_style()
    print("\n" + "="*60)
    print("B1  Image Quality Metrics")
    print("="*60)

    all_results = []

    for dcm in DICOM_FILES:
        print(f"\n[{dcm.name}]")
        stego_png = ensure_stego_noproof(dcm)

        cover = load_cover(dcm)
        stego = load_stego(stego_png)
        n_bits = payload_bits(dcm)

        m = compute_metrics(cover, stego, n_bits)
        m["image"] = dcm.stem
        all_results.append(m)

        print(f"  PSNR={m['PSNR_dB']:.2f} dB   SSIM={m['SSIM']:.6f}   "
              f"MSE={m['MSE']:.2f}   BPP={m['BPP']:.5f}")

        # Figures (first 3 images only to keep output manageable)
        if len(all_results) <= 3:
            plot_histogram(cover, stego, dcm.stem)
            plot_lsb_planes(cover, stego, dcm.stem)
            print(f"  Figures saved to benchmarks/results/figures/")

    # Summary statistics (mean ± std over all images)
    for metric in ("PSNR_dB", "SSIM", "MSE", "BPP"):
        vals = [r[metric] for r in all_results]
        print(f"\n  {metric:10s}  mean={np.mean(vals):.4f}   std={np.std(vals):.4f}   "
              f"min={np.min(vals):.4f}   max={np.max(vals):.4f}")

    # Line chart: all 4 metrics across test images
    plot_quality_lines(all_results)

    summary = {
        "per_image": all_results,
        "summary": {
            metric: {
                "mean": float(np.mean([r[metric] for r in all_results])),
                "std":  float(np.std( [r[metric] for r in all_results])),
                "min":  float(np.min( [r[metric] for r in all_results])),
                "max":  float(np.max( [r[metric] for r in all_results])),
            }
            for metric in ("PSNR_dB", "SSIM", "MSE", "BPP")
        },
        "note": (
            "data_range=65535 used for all skimage metrics (16-bit images). "
            "Stego generated with --no-proof (same pixel quality as full ZK embed)."
        ),
    }

    save_results("b1_quality.json", summary)
    return summary


if __name__ == "__main__":
    run()
