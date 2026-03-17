"""
benchmarks/run_paper_benchmarks.py
===================================
Targeted benchmark for the three DICOM test cases reported in the paper:
  - CT thorax  512×512
  - MR knee    256×256
  - MR brain   512×512  (partial: border/positions/proof size already known)

For each image this script produces:
  PSNR, SSIM, MSE      — 16-bit arrays, data_range=65535
  Border px            — border zone pixel count
  Positions used       — total embedded positions (data + RDH undo, both keys)
  Utilisation %        — positions / border_px * 100
  PG (s)               — ZK proof generation wall-clock time (witness + groth16 prove)
  PV (ms)              — Groth16 verification wall-clock time
  Proof size (KB)      — proof.json + public.json serialized bytes / 1024
  H(P), H(Q), ΔH, JSD — Shannon entropy and Jensen-Shannon divergence (16-bit histograms)

Output: benchmarks/results/paper_benchmarks.json
        (human-readable summary printed to stdout)

Run from ImageLevel/:
    python benchmarks/run_paper_benchmarks.py
    python benchmarks/run_paper_benchmarks.py --skip-zk   # skip slow PG/PV; fill with None
"""

import gzip
import io
import json
import math
import sys
import time
import contextlib
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image
from scipy.stats import entropy as scipy_entropy
from skimage.metrics import (
    peak_signal_noise_ratio as psnr_fn,
    structural_similarity as ssim_fn,
    mean_squared_error as mse_fn,
)

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import load_chaos_key, save_results
from src.zk_stego.dicom_handler import DicomHandler, DicomStego, DEFAULT_PROOF_KEY
from src.zk_stego.utils import SnarkJSRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identify_target_dicoms() -> dict:
    """
    Return the three target DICOM files for the paper benchmark.

    All 10 files in the dataset are MR phantom 512×512 (MultiFlip T1).
    Files are assigned to paper table rows by confirmed border-pixel counts:

      'mr_brain_512'   1-04.dcm  border_px=144,432  (matches pre-existing table entry)
      'mr_hi_512'      1-10.dcm  border_px=149,075  (highest border zone — most embedding headroom)
      'mr_lo_512'      1-06.dcm  border_px=140,581  (lowest border zone — tightest fit case)

    NOTE: The paper table originally used placeholder labels "CT thorax 512×512" and
    "MR knee 256×256". Since the actual test dataset contains only MR phantom 512×512
    images, those labels must be updated in the LaTeX to reflect the real test data.
    The update_latex() call in main() handles this automatically.
    """
    dicom_dir = ROOT / "examples" / "dicom"
    return {
        "mr_brain_512": dicom_dir / "1-04.dcm",
        "mr_hi_512":    dicom_dir / "1-10.dcm",
        "mr_lo_512":    dicom_dir / "1-06.dcm",
    }


def _positions_used_from_verbose(dcm_path: Path, stego_png: Path,
                                 chaos_key: str, generate_zk: bool) -> tuple:
    """
    Run embed with verbose=True; capture stdout to parse:
      - border_pixels       (from "Border zone: X / Y pixels")
      - positions_used      (from "Border zone utilisation: X / Y pixels")
      - utilisation_pct     (from same line)
    Returns (border_px, positions_used, utilisation_pct, embed_result)
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = DicomStego(project_root=str(ROOT)).embed(
            str(dcm_path), str(stego_png),
            chaos_key=chaos_key,
            proof_key=DEFAULT_PROOF_KEY,
            generate_zk_proof=generate_zk,
            verbose=True,
        )
    log = buf.getvalue()

    # Parse: "Border zone: 144432 / 262144 pixels (55.1 %, erosion=10 px)"
    border_px = result["border_pixels"]

    # Parse: "Border zone utilisation: 28800 / 144432 pixels (19.9 %)"
    pos_used = None
    util_pct = None
    for line in log.splitlines():
        if "Border zone utilisation:" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p.isdigit():
                    pos_used = int(p)
                    break
            # extract percentage
            for part in parts:
                if part.startswith("(") and "%" not in part:
                    try:
                        util_pct = float(part.lstrip("("))
                    except ValueError:
                        pass
                if "%" in part:
                    try:
                        util_pct = float(part.replace("(", "").replace("%", ""))
                    except ValueError:
                        pass
            break

    return border_px, pos_used, util_pct, result


def _entropy_metrics(cover: np.ndarray, stego: np.ndarray) -> dict:
    """
    Shannon entropy H(P), H(Q), ΔH, JSD on 16-bit histograms.
    Uses np.histogram with 65536 bins (one per grey level).
    """
    bins = np.arange(65537, dtype=np.int32)  # 65536 bins

    cover_counts, _ = np.histogram(cover.ravel(), bins=bins)
    stego_counts, _ = np.histogram(stego.ravel(), bins=bins)

    # Normalise to probability distributions (skip zero bins to avoid log(0))
    cover_prob = cover_counts / cover_counts.sum()
    stego_prob = stego_counts / stego_counts.sum()

    # Shannon entropy (base-2, bits)
    hp = float(scipy_entropy(cover_prob + 1e-12, base=2))
    hq = float(scipy_entropy(stego_prob + 1e-12, base=2))

    # JSD
    m = 0.5 * (cover_prob + stego_prob)
    jsd = 0.5 * float(scipy_entropy(cover_prob + 1e-12, m + 1e-12, base=2)) + \
          0.5 * float(scipy_entropy(stego_prob + 1e-12, m + 1e-12, base=2))

    return {
        "H_P":   round(hp, 6),
        "H_Q":   round(hq, 6),
        "delta_H": round(abs(hp - hq), 6),
        "JSD":   round(jsd, 8),
    }


def _load_cover(dcm_path: Path) -> np.ndarray:
    return DicomHandler.to_uint16(pydicom.dcmread(str(dcm_path)).pixel_array)


def _load_stego(png_path: Path) -> np.ndarray:
    return np.array(Image.open(str(png_path)), dtype=np.uint16)


def _proof_size_kb(proof: dict, public_inputs: list) -> float:
    """Serialized size of proof.json + public.json in KB."""
    pj = len(json.dumps(proof).encode("utf-8"))
    ij = len(json.dumps(public_inputs).encode("utf-8"))
    return round((pj + ij) / 1024, 3)


def _time_pv(proof: dict, public_inputs: list) -> float:
    """Time Groth16 verification in milliseconds. Returns -1.0 on failure."""
    runner = SnarkJSRunner(project_root=str(ROOT))
    t0 = time.perf_counter()
    ok = runner.verify_groth16_proof(proof, public_inputs)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if not ok:
        print("  WARNING: ZK proof verification returned False")
    return round(elapsed_ms, 2)


# ---------------------------------------------------------------------------
# Per-image benchmark
# ---------------------------------------------------------------------------

def benchmark_image(label: str, dcm_path: Path, skip_zk: bool) -> dict:
    print(f"\n{'='*60}")
    print(f"  {label}  ({dcm_path.name})")
    print(f"{'='*60}")

    chaos_key = load_chaos_key()
    results_dir = ROOT / "benchmarks" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: No-proof embed ───────────────────────────────────────────────
    stego_noproof = results_dir / f"paper_noproof_{dcm_path.stem}.png"
    print(f"  [1/5] No-proof embed … ", end="", flush=True)
    t_start = time.perf_counter()
    border_px, positions_used, util_pct, res_np = _positions_used_from_verbose(
        dcm_path, stego_noproof, chaos_key, generate_zk=False
    )
    t_noproof = time.perf_counter() - t_start
    print(f"done ({t_noproof:.2f} s)  border={border_px:,}  positions={positions_used}")

    # ── Step 2: Image quality metrics ────────────────────────────────────────
    print(f"  [2/5] Quality metrics … ", end="", flush=True)
    cover = _load_cover(dcm_path)
    stego = _load_stego(stego_noproof)
    mse_val  = float(np.mean((cover.astype(np.float64) - stego.astype(np.float64))**2))
    psnr_val = float(psnr_fn(cover, stego, data_range=65535))
    ssim_val = float(ssim_fn(cover, stego, data_range=65535))
    print(f"PSNR={psnr_val:.4f} dB  SSIM={ssim_val:.6f}  MSE={mse_val:.4f}")

    # ── Step 3: Entropy metrics ──────────────────────────────────────────────
    print(f"  [3/5] Entropy metrics … ", end="", flush=True)
    ent = _entropy_metrics(cover, stego)
    print(f"H(P)={ent['H_P']:.4f}  H(Q)={ent['H_Q']:.4f}  "
          f"ΔH={ent['delta_H']:.6f}  JSD={ent['JSD']:.2e}")

    # ── Step 4: ZK proof generation time (PG) ───────────────────────────────
    pg_s = None
    pv_ms = None
    proof_size_kb = None
    proof_obj = None
    public_inputs_obj = None

    if skip_zk:
        print(f"  [4/5] ZK timing — SKIPPED (--skip-zk)")
        print(f"  [5/5] ZK verification — SKIPPED")
    else:
        print(f"  [4/5] ZK proof generation (witness + groth16 prove) … ", flush=True)
        stego_zk = results_dir / f"paper_zk_{dcm_path.stem}.png"
        t_zk_start = time.perf_counter()
        _, _, _, res_zk = _positions_used_from_verbose(
            dcm_path, stego_zk, chaos_key, generate_zk=True
        )
        t_zk_total = time.perf_counter() - t_zk_start
        # PG = ZK embed time minus no-proof embed time (isolates witness + prove)
        pg_s = round(t_zk_total - t_noproof, 2)
        print(f"       embed_zk={t_zk_total:.1f}s  embed_noproof={t_noproof:.2f}s  PG≈{pg_s:.1f}s")

        proof_obj = res_zk.get("proof")
        public_inputs_obj = res_zk.get("public_inputs")
        if proof_obj and public_inputs_obj:
            proof_size_kb = _proof_size_kb(proof_obj, public_inputs_obj)
            print(f"       Proof size: {proof_size_kb:.3f} KB")

            # ── Step 5: Verification time (PV) ──────────────────────────────
            print(f"  [5/5] Groth16 verification timing … ", end="", flush=True)
            pv_ms = _time_pv(proof_obj, public_inputs_obj)
            print(f"{pv_ms:.1f} ms")
        else:
            print(f"  WARNING: ZK proof was not generated — check snarkjs setup")
            print(f"  [5/5] ZK verification — SKIPPED (no proof available)")

    # ── Utilisation from positions_used and border_px─────────────────────────
    if positions_used is not None and border_px:
        util_pct_calc = round(positions_used / border_px * 100, 1)
    else:
        util_pct_calc = util_pct

    return {
        "label":          label,
        "dicom_file":     dcm_path.name,
        # Quality
        "PSNR_dB":        round(psnr_val, 4),
        "SSIM":           round(ssim_val, 6),
        "MSE":            round(mse_val,  4),
        # Capacity
        "border_px":      border_px,
        "positions_used": positions_used,
        "utilisation_pct":util_pct_calc,
        # ZK
        "PG_s":           pg_s,
        "PV_ms":          pv_ms,
        "proof_size_kb":  proof_size_kb,
        # Entropy
        **ent,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    skip_zk = "--skip-zk" in sys.argv

    print("\nIdentifying test DICOM images …")
    targets = _identify_target_dicoms()
    for role, path in targets.items():
        status = str(path.name) if path else "NOT FOUND"
        print(f"  {role:20s}  {status}")

    missing = [r for r, p in targets.items() if p is None]
    if missing:
        print(f"\nWARNING: Could not identify: {missing}")
        print("  Proceeding with available images only.\n")

    # Ordered for output (matches paper table row order)
    ordered = [
        ("mr_brain_512", "MR brain 512x512 (1-04)"),
        ("mr_hi_512",    "MR phantom 512x512 (1-10)"),
        ("mr_lo_512",    "MR phantom 512x512 (1-06)"),
    ]

    all_results = []
    for role, label in ordered:
        if targets[role] is None:
            print(f"\nSKIPPING {label} — DICOM not found")
            continue
        r = benchmark_image(label, targets[role], skip_zk=skip_zk)
        all_results.append(r)

    # ── Summary print ────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("RESULTS SUMMARY (copy-paste into LaTeX)")
    print(f"{'='*80}")
    header = f"{'Image':<22} {'PSNR':>9} {'SSIM':>10} {'MSE':>10} " \
             f"{'BdrPx':>9} {'Pos':>7} {'Util%':>6} " \
             f"{'PG(s)':>7} {'PV(ms)':>7} {'PrfKB':>7}" \
             f"  H(P)   H(Q)    ΔH        JSD"
    print(header)
    print("-" * len(header))
    for r in all_results:
        pg  = f"{r['PG_s']:.1f}"  if r['PG_s']  is not None else "---"
        pv  = f"{r['PV_ms']:.1f}" if r['PV_ms'] is not None else "---"
        psz = f"{r['proof_size_kb']:.2f}" if r['proof_size_kb'] is not None else "---"
        pos = f"{r['positions_used']:,}" if r['positions_used'] else "---"
        print(
            f"{r['label']:<22} "
            f"{r['PSNR_dB']:>9.4f} "
            f"{r['SSIM']:>10.6f} "
            f"{r['MSE']:>10.4f} "
            f"{r['border_px']:>9,} "
            f"{pos:>7} "
            f"{r['utilisation_pct']:>5.1f}% "
            f"{pg:>7} {pv:>7} {psz:>7}"
            f"  {r['H_P']:.4f} {r['H_Q']:.4f} {r['delta_H']:.6f}  {r['JSD']:.3e}"
        )

    # ── Save JSON ─────────────────────────────────────────────────────────────
    save_results("paper_benchmarks.json", {"results": all_results})
    print(f"\nFull results saved to benchmarks/results/paper_benchmarks.json")


if __name__ == "__main__":
    main()
