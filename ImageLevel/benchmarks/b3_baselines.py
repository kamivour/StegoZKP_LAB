"""
benchmarks/b3_baselines.py  —  §3 Baseline Comparison
======================================================
Implements three baseline LSB embedders and runs B1 quality metrics +
B2 steganalysis on ALL of them, including this system (Stego+Chaos).

Baselines
---------
A — Sequential LSB   : embed bits left-to-right, top-to-bottom in ROI
B — PRNG-LSB         : embed bits in ROI pixels permuted by numpy RNG
C — ACM-only         : Arnold Cat Map positions only (no Logistic Map perturbation)
D — This work        : full ACM + Logistic Map chaos (no-proof mode)

Results: results/b3_baselines.json
        results/figures/b3_comparison_*.pdf

Run from ImageLevel/:
    python benchmarks/b3_baselines.py
"""

import gzip
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import (
    DICOM_FILES, FIGURES_DIR, RESULTS_DIR,
    load_chaos_key, load_cover, load_stego,
    ensure_stego_noproof, save_results, apply_paper_style,
)
from benchmarks.b1_quality import compute_metrics
from benchmarks.b2_steganalysis import rs_analysis, chi_square_attack, spa_estimate

from src.zk_stego.dicom_handler import DicomHandler, DEFAULT_PROOF_KEY
from src.zk_stego.utils import ChaosGenerator, generate_chaos_key_from_secret

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ===========================================================================
# Baseline embedders
# ===========================================================================

def _get_roi_pixels(cover: np.ndarray) -> List[Tuple[int, int]]:
    """Return (x, y) coordinates of all ROI pixels, ordered top-to-bottom."""
    roi_mask = DicomHandler.detect_roi(cover)
    ys, xs = np.where(roi_mask)
    # Sort top-left to bottom-right (sequential order)
    order = np.lexsort((xs, ys))
    return list(zip(xs[order].tolist(), ys[order].tolist()))


def _embed_at_positions(
    cover: np.ndarray,
    positions: List[Tuple[int, int]],
    bits: List[int],
) -> np.ndarray:
    """Embed *bits* at *positions* using 2 bits per pixel (bits 0 and 1)."""
    stego = cover.copy()
    bit_idx = 0
    for (x, y) in positions:
        if bit_idx >= len(bits):
            break
        px = int(stego[y, x])
        # Embed up to 2 bits per pixel
        b0 = bits[bit_idx] if bit_idx < len(bits) else 0
        b1 = bits[bit_idx + 1] if (bit_idx + 1) < len(bits) else 0
        stego[y, x] = np.uint16((px & 0xFFFC) | (b1 << 1) | b0)
        bit_idx += 2
    return stego


def embed_sequential_lsb(cover: np.ndarray, bits: List[int]) -> np.ndarray:
    """
    Baseline A — Plain Sequential LSB.
    Embeds bits left-to-right, top-to-bottom within the ROI.
    This is the weakest scheme and acts as the "obviously detectable" reference.
    """
    positions = _get_roi_pixels(cover)
    return _embed_at_positions(cover, positions, bits)


def embed_prng_lsb(cover: np.ndarray, bits: List[int], seed: int = 42) -> np.ndarray:
    """
    Baseline B — PRNG-LSB.
    Permutes ROI pixel positions with numpy.random.default_rng(seed).
    Uses a seeded PRNG but no chaos structure.
    """
    positions = _get_roi_pixels(cover)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(positions))
    shuffled = [positions[i] for i in perm]
    return _embed_at_positions(cover, shuffled, bits)


def embed_acm_only_lsb(cover: np.ndarray, bits: List[int], chaos_key_str: str) -> np.ndarray:
    """
    Baseline C — Arnold Cat Map only (no Logistic Map perturbation).
    Isolates the contribution of the Logistic Map to detectability.
    """
    h, w = cover.shape
    chaos_key_int = generate_chaos_key_from_secret(chaos_key_str)
    arnold_iterations = (chaos_key_int // 10000) % 10 + 1

    roi_mask = DicomHandler.detect_roi(cover)
    ys, xs = np.where(roi_mask)
    roi_set = set(zip(xs.tolist(), ys.tolist()))

    gen = ChaosGenerator(w, h)

    # Starting point from the chaos key
    x0 = chaos_key_int % w
    y0 = (chaos_key_int // w) % h

    # Generate positions using only Arnold Cat Map (no logistic perturbation)
    needed = (len(bits) + 1) // 2
    positions = []
    used = set()
    x, y = x0, y0

    for _ in range(needed * 10):  # overshoot to ensure enough unique positions
        x, y = gen.arnold_cat_map(x, y, arnold_iterations)
        pos = (x, y)
        if pos in roi_set and pos not in used:
            positions.append(pos)
            used.add(pos)
        if len(positions) >= needed:
            break

    # Fallback: fill from ROI if not enough
    if len(positions) < needed:
        ys_sorted, xs_sorted = np.where(roi_mask)
        order = np.lexsort((xs_sorted, ys_sorted))
        for xi, yi in zip(xs_sorted[order], ys_sorted[order]):
            p = (int(xi), int(yi))
            if p not in used:
                positions.append(p)
                used.add(p)
            if len(positions) >= needed:
                break

    return _embed_at_positions(cover, positions[:needed], bits)


# ===========================================================================
# Payload extraction helper
# ===========================================================================

def _dicom_payload_bits(dcm: Path) -> List[int]:
    """Return the exact bit sequence that this system would embed."""
    _, metadata_json, _ = DicomHandler.load(str(dcm))
    compressed = gzip.compress(metadata_json.encode("utf-8"), compresslevel=9)
    bits = []
    for byte in compressed:
        for i in range(8):
            bits.append((byte >> i) & 1)
    return bits


# ===========================================================================
# Run one baseline on all test images
# ===========================================================================

def _run_baseline(name: str, embedder_fn, dcm: Path) -> dict:
    cover = load_cover(dcm)
    bits = _dicom_payload_bits(dcm)
    stego = embedder_fn(cover, bits)
    n_bits = len(bits)

    quality = compute_metrics(cover, stego, n_bits)
    rs      = rs_analysis(stego)
    chi     = chi_square_attack(stego)
    spa     = spa_estimate(stego)

    # Save stego PNG for reference
    out_png = RESULTS_DIR / f"{dcm.stem}_baseline_{name}.png"
    Image.fromarray(stego).save(str(out_png))

    return {
        "baseline": name,
        "image":    dcm.stem,
        "quality":  quality,
        "rs":       rs,
        "chi_square": chi,
        "spa":      spa,
    }


# ===========================================================================
# Comparison figure
# ===========================================================================

def plot_comparison(all_data: list) -> Path:
    """
    Multi-metric bar chart comparing all 4 systems across one representative image.
    """
    out = FIGURES_DIR / "b3_comparison.pdf"

    baselines   = ["sequential", "prng", "acm_only", "this_work"]
    labels      = ["Sequential LSB", "PRNG-LSB", "ACM-only", "This Work (ACM+Logistic)"]
    colors      = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71"]

    # Use first image for the figure
    first_stem = all_data[0]["this_work"]["image"]
    psnr_vals  = [all_data[0][b]["quality"]["PSNR_dB"] for b in baselines]
    ssim_vals  = [all_data[0][b]["quality"]["SSIM"]    for b in baselines]
    chi_p_vals = [all_data[0][b]["chi_square"]["p_value"] for b in baselines]
    rs_phats   = [all_data[0][b]["rs"]["p_hat"]        for b in baselines]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(f"Baseline comparison — {first_stem}", fontsize=13)

    for ax, vals, title, ylabel in [
        (axes[0, 0], psnr_vals, "PSNR (dB)",           "dB"),
        (axes[0, 1], ssim_vals, "SSIM",                 ""),
        (axes[1, 0], chi_p_vals,"Chi-square p-value",   "p"),
        (axes[1, 1], rs_phats,  "RS estimated payload", "p̂"),
    ]:
        bars = ax.bar(labels, vals, color=colors, edgecolor="white")
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=25)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f"{v:.3f}", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


# ===========================================================================
# Main
# ===========================================================================

def run() -> dict:
    apply_paper_style()
    print("\n" + "="*60)
    print("B3  Baseline Comparison")
    print("="*60)

    chaos_key_str = load_chaos_key()
    all_image_data = []

    for dcm in DICOM_FILES:
        print(f"\n[{dcm.name}]")
        cover = load_cover(dcm)
        bits  = _dicom_payload_bits(dcm)

        image_data = {}

        # A — Sequential LSB
        print("  Baseline A: Sequential LSB … ", end="", flush=True)
        image_data["sequential"] = _run_baseline(
            "sequential", lambda c, b: embed_sequential_lsb(c, b), dcm
        )
        print(f"PSNR={image_data['sequential']['quality']['PSNR_dB']:.1f}  "
              f"χ²p={image_data['sequential']['chi_square']['p_value']:.4f}  "
              f"RS_p̂={image_data['sequential']['rs']['p_hat']:.4f}")

        # B — PRNG-LSB
        print("  Baseline B: PRNG-LSB      … ", end="", flush=True)
        image_data["prng"] = _run_baseline(
            "prng", lambda c, b: embed_prng_lsb(c, b), dcm
        )
        print(f"PSNR={image_data['prng']['quality']['PSNR_dB']:.1f}  "
              f"χ²p={image_data['prng']['chi_square']['p_value']:.4f}  "
              f"RS_p̂={image_data['prng']['rs']['p_hat']:.4f}")

        # C — ACM-only
        print("  Baseline C: ACM-only      … ", end="", flush=True)
        image_data["acm_only"] = _run_baseline(
            "acm_only", lambda c, b: embed_acm_only_lsb(c, b, chaos_key_str), dcm
        )
        print(f"PSNR={image_data['acm_only']['quality']['PSNR_dB']:.1f}  "
              f"χ²p={image_data['acm_only']['chi_square']['p_value']:.4f}  "
              f"RS_p̂={image_data['acm_only']['rs']['p_hat']:.4f}")

        # D — This work (no-proof, same embedding)
        print("  This work (no-proof)      … ", end="", flush=True)
        stego_png = ensure_stego_noproof(dcm)
        stego_arr = load_stego(stego_png)
        n_bits    = len(bits)
        rs_d      = rs_analysis(stego_arr)
        chi_d     = chi_square_attack(stego_arr)
        spa_d     = spa_estimate(stego_arr)
        qual_d    = compute_metrics(cover, stego_arr, n_bits)
        image_data["this_work"] = {
            "baseline": "this_work",
            "image":    dcm.stem,
            "quality":  qual_d,
            "rs":       rs_d,
            "chi_square": chi_d,
            "spa":      spa_d,
        }
        print(f"PSNR={qual_d['PSNR_dB']:.1f}  "
              f"χ²p={chi_d['p_value']:.4f}  "
              f"RS_p̂={rs_d['p_hat']:.4f}")

        all_image_data.append(image_data)

    # Comparison figure (first image)
    plot_comparison(all_image_data)

    # Build result table rows (for paper Table T2)
    print("\n  Result table (means over all images):")
    print(f"  {'Scheme':25s}  {'PSNR':>8}  {'SSIM':>8}  {'χ²p':>8}  {'RS p̂':>8}  {'SPA p̂':>8}")
    print("  " + "-"*70)
    for bname, label in [
        ("sequential", "Sequential LSB"),
        ("prng",       "PRNG-LSB"),
        ("acm_only",   "ACM-only"),
        ("this_work",  "This Work"),
    ]:
        psnr_m  = np.mean([d[bname]["quality"]["PSNR_dB"]         for d in all_image_data])
        ssim_m  = np.mean([d[bname]["quality"]["SSIM"]            for d in all_image_data])
        chi_m   = np.mean([d[bname]["chi_square"]["p_value"]      for d in all_image_data])
        rs_m    = np.mean([d[bname]["rs"]["p_hat"]                for d in all_image_data])
        spa_m   = np.mean([d[bname]["spa"]["p_hat"]               for d in all_image_data])
        print(f"  {label:25s}  {psnr_m:>8.2f}  {ssim_m:>8.4f}  {chi_m:>8.4f}  {rs_m:>8.4f}  {spa_m:>8.4f}")

    report = {
        "per_image": all_image_data,
        "note": (
            "All RS/chi-square/SPA analyses performed on the bottom 8 bits "
            "(2-LSB embedding modifies bits 0 and 1 only). "
            "Baseline PNGs saved to benchmarks/results/"
        ),
    }
    save_results("b3_baselines.json", report)
    return report


if __name__ == "__main__":
    run()
