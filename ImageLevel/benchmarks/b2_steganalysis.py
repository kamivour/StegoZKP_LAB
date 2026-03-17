"""
benchmarks/b2_steganalysis.py  —  §2 Steganalysis Resistance
=============================================================
Runs three classical steganalysis tests against cover and stego images:
  - RS Analysis   (Fridrich, Goljan, Du 2001)
  - Chi-Square    (Westfeld & Pfitzmann 1999)
  - SPA estimate  (Dumitrescu, Wu, Wang 2003)

Results: results/b2_steganalysis.json

Expected results for a well-designed chaos scheme:
  - Cover and stego chi-square p-values should be similar (> 0.05)
  - RS Rm−Sm should be ≈ 0 for stego (not the large split seen with sequential LSB)
  - SPA estimated payload should be ≈ 0 for stego
  - Sequential LSB (in b3) will show the opposite patterns

Run from ImageLevel/:
    python benchmarks/b2_steganalysis.py

Notes on 16-bit images
----------------------
All three metrics operate directly on the full uint16 pixel values (0–65535).
For a 2-LSB system only bits 0 and 1 are modified, so embedding effects are
concentrated in the low-value pairs (0↔1, 2↔3, …) of the 16-bit histogram.
RS and SPA flip operations use p^1 and p±1 which are identical for any
bit-width — we simply clip to [0, 65535] instead of [0, 255].
"""

import sys
from pathlib import Path
import numpy as np
from scipy.stats import chi2 as chi2_dist

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import (
    DICOM_FILES,
    load_cover, load_stego,
    ensure_stego_noproof, save_results,
    FIGURES_DIR, apply_paper_style,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ===========================================================================
# RS Analysis  (Fridrich, Goljan, Du 2001)
# ===========================================================================

def _smoothness(block: np.ndarray) -> float:
    """Smoothness function f = sum of absolute differences between adjacent pixels."""
    return float(np.sum(np.abs(np.diff(block.astype(np.int32)))))


def _flip1(p: int) -> int:
    """F+1 operation: flip the LSB (0↔1)."""
    return p ^ 1


def _flip_neg1(p: int) -> int:
    """
    F-1 operation: the 'negative' flip — maps each even value to the one
    below it, and each odd value to the one above it.
    Formally: F-1(p) = p-1 if p is odd, p+1 if p is even
    (Also written as the mapping 2k↔2k+1 reversed.)
    """
    return p - 1 if (p % 2 == 1) else p + 1


def rs_analysis(img_array: np.ndarray, group_size: int = 4) -> dict:
    """
    Fridrich RS analysis on the full 16-bit uint16 pixel values.

    The flip operations (F+1: p^1, F-1: p±1) are identical for any bit-width;
    the only change from the classic 8-bit formulation is clipping to [0, 65535].

    Returns
    -------
    dict with keys:
        Rm, Sm, Rm_, Sm_  — Regular/Singular group counts for +/- masks
        p_hat             — Estimated payload fraction (0 = unmodified)
        n_groups          — Number of pixel groups analysed
    """
    flat = img_array.ravel().astype(np.int32)   # full 16-bit values

    # Pad to a multiple of group_size
    pad = (group_size - len(flat) % group_size) % group_size
    if pad:
        flat = np.concatenate([flat, np.zeros(pad, dtype=np.int32)])

    groups = flat.reshape(-1, group_size)
    n_groups = len(groups)

    # Mask pattern: [0, 1, 0, 1] — flip every other pixel
    mask = np.array([0, 1, 0, 1][:group_size])

    Rm = Sm = Rm_ = Sm_ = 0

    for g in groups:
        f0 = _smoothness(g)

        # F+1 mask
        gp = g.copy()
        for i in range(group_size):
            if mask[i] == 1:
                gp[i] = _flip1(int(gp[i]))
        gp = np.clip(gp, 0, 65535)
        fp = _smoothness(gp)
        if fp > f0:
            Rm += 1
        elif fp < f0:
            Sm += 1

        # F-1 mask
        gm = g.copy()
        for i in range(group_size):
            if mask[i] == 1:
                gm[i] = _flip_neg1(int(gm[i]))
        gm = np.clip(gm, 0, 65535)
        fm = _smoothness(gm)
        if fm > f0:
            Rm_ += 1
        elif fm < f0:
            Sm_ += 1

    # Payload estimate from the standard formula (Fridrich 2001 eq. 14)
    denom = (Rm - Rm_) + (Sm_ - Sm)
    p_hat = (Rm - Rm_) / denom if abs(denom) > 1 else 0.0

    return {
        "Rm":     Rm,
        "Sm":     Sm,
        "Rm_":    Rm_,
        "Sm_":    Sm_,
        "Rm_Sm_diff": Rm - Sm,    # large positive = suspicious
        "p_hat":  round(float(p_hat), 4),
        "n_groups": n_groups,
    }


# ===========================================================================
# Chi-Square Attack  (Westfeld & Pfitzmann 1999)
# ===========================================================================

def chi_square_attack(img_array: np.ndarray) -> dict:
    """
    Chi-square test on PoV (Pairs of Values) in the full uint16 pixel values.

    PoV pairs: (0,1), (2,3), (4,5), … (65534,65535) — 32 768 pairs total.
    Only pairs with at least one non-zero count are tested (the MR histogram
    is concentrated in a narrow band, so most pairs are empty).
    Sequential LSB forces equal pair counts → p ≈ 0 (detected).
    Chaos / random 2-LSB should leave the natural distribution → p >> 0.

    Returns
    -------
    dict with chi2_stat and p_value (large p = not detectable).
    """
    flat   = img_array.ravel().astype(np.int64)   # full 16-bit, no masking
    counts = np.bincount(flat, minlength=65536)

    even_counts = counts[0::2]           # values 0, 2, 4, …, 65534
    odd_counts  = counts[1::2]           # values 1, 3, 5, …, 65535
    expected    = (even_counts + odd_counts) / 2.0

    # Only include pairs where at least one value appears
    mask = expected > 0
    chi2_stat = float(np.sum(
        (even_counts[mask] - expected[mask]) ** 2 / expected[mask]
    ))
    df = int(mask.sum()) - 1
    p_value = float(chi2_dist.sf(chi2_stat, df=df)) if df > 0 else 1.0

    return {
        "chi2_stat": round(chi2_stat, 4),
        "df":        df,
        "p_value":   round(p_value,  6),
        "note":      "p >> 0.05 → not detected; p ≈ 0 → detected",
    }


# ===========================================================================
# Sample Pairs Analysis  (Dumitrescu, Wu, Wang 2003)
# ===========================================================================

def spa_estimate(img_array: np.ndarray) -> dict:
    """
    Simplified SPA payload estimator on full uint16 pixel values.

    Counts horizontally-adjacent pairs (p_i, p_{i+1}) where values differ
    by exactly +1 (C1) or -1 (C2) — the asymmetry between C1 and C2
    correlates with the embedding rate after 2-LSB modifications.
    Works identically on 16-bit values; only bits 0 and 1 are modified,
    so the relevant PoV transitions are those crossing even→odd boundaries.

    Returns estimated payload fraction and support counts.
    Reference: Dumitrescu et al. (2003), IEEE TSP.
    """
    flat = img_array.ravel().astype(np.int64)   # full 16-bit, no masking
    a = flat[:-1]
    b = flat[1:]

    # C1(k): pairs where b = a + 1 for even a   (increases that cross a PoV boundary)
    # C2(k): pairs where b = a - 1 for odd  a
    # W(k):  pairs where a == b
    even_mask = (a % 2 == 0)
    odd_mask  = ~even_mask

    C1 = np.sum( (b == a + 1) &  even_mask )
    C2 = np.sum( (b == a - 1) &  odd_mask  )
    W  = np.sum( a == b )

    # Payload estimate (eq. from Dumitrescu 2003, simplified form)
    total = C1 + C2 + W
    denom = 2 * C2 - W
    if abs(denom) < 1e-6:
        p_hat = 0.0
    else:
        p_hat = float((C1 - C2) / denom)

    p_hat = max(0.0, min(1.0, p_hat))

    return {
        "C1":     int(C1),
        "C2":     int(C2),
        "W":      int(W),
        "p_hat":  round(p_hat, 4),
        "note":   "p_hat ≈ 0 → unmodified; ≈ 1.0 → fully embedded",
    }


# ===========================================================================
# Figures
# ===========================================================================

def plot_rs_bars(cover_rs: dict, stego_rs: dict, stem: str) -> Path:
    """Side-by-side bars: Rm, Sm, Rm_, Sm_ for cover and stego."""
    out = FIGURES_DIR / f"b2_rs_bars_{stem}.pdf"
    labels  = ["Rm", "Sm", "Rm_", "Sm_"]
    cover_v = [cover_rs[k] for k in labels]
    stego_v = [stego_rs[k] for k in labels]

    x     = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar(x - width/2, cover_v, width, label="Cover", color="steelblue", edgecolor="none")
    ax.bar(x + width/2, stego_v, width, label="Stego", color="crimson",   edgecolor="none")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Group count")
    ax.set_title(f"RS Analysis — {stem}")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


def plot_steganalysis_lines(all_results: list) -> Path:
    """
    Line chart showing chi-square p-value and RS/SPA p_hat across all images.
    Three metrics on two y-axes; each image is one x-tick.
    A line at p=0.05 marks the conventional detectability threshold.
    """
    out = FIGURES_DIR / "b2_steganalysis_summary.pdf"
    stems         = [r["image"] for r in all_results]
    chi_cover     = [r["cover"]["chi_square"]["p_value"] for r in all_results]
    chi_stego     = [r["stego"]["chi_square"]["p_value"] for r in all_results]
    rs_cover      = [r["cover"]["rs"]["p_hat"]           for r in all_results]
    rs_stego      = [r["stego"]["rs"]["p_hat"]           for r in all_results]
    spa_cover     = [r["cover"]["spa"]["p_hat"]          for r in all_results]
    spa_stego     = [r["stego"]["spa"]["p_hat"]          for r in all_results]

    x = np.arange(len(stems))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)

    ax1.plot(x, chi_cover, "o--", color="steelblue", label="Cover \u03c7\u00b2 p-value", lw=1.6, ms=5)
    ax1.plot(x, chi_stego, "s-",  color="crimson",   label="Stego \u03c7\u00b2 p-value", lw=1.6, ms=5)
    ax1.axhline(0.05, color="gray", ls=":", lw=1, label="α = 0.05")
    ax1.set_ylabel("Chi-square p-value")
    ax1.set_ylim(-0.02, 1.05)
    ax1.legend(frameon=False, fontsize=9)
    ax1.set_title("Steganalysis Resistance — all test images (full 16-bit)")

    ax2.plot(x, rs_cover,  "o--", color="steelblue",  label="Cover RS p\u0302",  lw=1.6, ms=5)
    ax2.plot(x, rs_stego,  "s-",  color="crimson",    label="Stego RS p\u0302",  lw=1.6, ms=5)
    ax2.plot(x, spa_cover, "^--", color="#2ca02c",    label="Cover SPA p\u0302", lw=1.2, ms=4)
    ax2.plot(x, spa_stego, "v-",  color="#d62728",    label="Stego SPA p\u0302", lw=1.2, ms=4)
    ax2.set_ylabel("Estimated payload fraction p\u0302")
    ax2.set_xticks(x)
    ax2.set_xticklabels(stems, rotation=40, ha="right", fontsize=8)
    ax2.legend(frameon=False, fontsize=9, ncol=2)

    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


# ===========================================================================
# Main
# ===========================================================================

def analyse_image(dcm) -> dict:
    stego_png = ensure_stego_noproof(dcm)
    cover = load_cover(dcm)
    stego = load_stego(stego_png)

    return {
        "image": dcm.stem,
        "cover": {
            "rs":         rs_analysis(cover),
            "chi_square": chi_square_attack(cover),
            "spa":        spa_estimate(cover),
        },
        "stego": {
            "rs":         rs_analysis(stego),
            "chi_square": chi_square_attack(stego),
            "spa":        spa_estimate(stego),
        },
    }


def run() -> dict:
    apply_paper_style()
    print("\n" + "="*60)
    print("B2  Steganalysis Resistance")
    print("="*60)
    print("  Tests: RS Analysis, Chi-Square, SPA (full 16-bit uint16)")

    all_results = []

    for i, dcm in enumerate(DICOM_FILES):
        print(f"\n[{dcm.name}]", flush=True)
        r = analyse_image(dcm)
        all_results.append(r)

        c, s = r["cover"], r["stego"]
        print(f"  RS    cover p_hat={c['rs']['p_hat']:.4f}  stego p_hat={s['rs']['p_hat']:.4f}")
        print(f"  χ²    cover p={c['chi_square']['p_value']:.4f}  stego p={s['chi_square']['p_value']:.4f}")
        print(f"  SPA   cover p_hat={c['spa']['p_hat']:.4f}  stego p_hat={s['spa']['p_hat']:.4f}")

        if i < 3:
            plot_rs_bars(c["rs"], s["rs"], dcm.stem)

    # Summary line chart across all images
    plot_steganalysis_lines(all_results)

    # Aggregate
    stego_chi_p  = [r["stego"]["chi_square"]["p_value"]  for r in all_results]
    stego_rs_p   = [r["stego"]["rs"]["p_hat"]            for r in all_results]
    stego_spa_p  = [r["stego"]["spa"]["p_hat"]           for r in all_results]

    print(f"\n  Summary (stego, n={len(all_results)} images):")
    print(f"    χ² p-value : mean={np.mean(stego_chi_p):.4f}  std={np.std(stego_chi_p):.4f}")
    print(f"    RS p_hat   : mean={np.mean(stego_rs_p):.4f}  std={np.std(stego_rs_p):.4f}")
    print(f"    SPA p_hat  : mean={np.mean(stego_spa_p):.4f}  std={np.std(stego_spa_p):.4f}")

    report = {
        "per_image": all_results,
        "summary_stego": {
            "chi_square_p_value": {
                "mean": float(np.mean(stego_chi_p)),
                "std":  float(np.std(stego_chi_p)),
            },
            "rs_p_hat": {
                "mean": float(np.mean(stego_rs_p)),
                "std":  float(np.std(stego_rs_p)),
            },
            "spa_p_hat": {
                "mean": float(np.mean(stego_spa_p)),
                "std":  float(np.std(stego_spa_p)),
            },
        },
        "interpretation": {
            "chi_square": "p_value > 0.05 = not detectable (good); p ≈ 0 = detected (bad)",
            "rs":         "p_hat ≈ 0 = undetected; large p_hat = embedding detected",
            "spa":        "p_hat ≈ 0 = undetected; large p_hat = embedding detected",
            "note":       "All three metrics operate on full 16-bit uint16 pixel values",
        },
    }

    save_results("b2_steganalysis.json", report)
    return report


if __name__ == "__main__":
    run()
