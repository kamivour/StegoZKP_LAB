"""
benchmarks/b6_system_comparison.py  —  §6 System-Level Comparison
==================================================================
Implements Benchmark C (Stego-only timing) and Benchmark D (ECDSA P-256
signing benchmark) as described in BENCHMARKING_PLAN.md §6.

This produces the data for Table T6 (capability comparison) and the
expanded Table T4 (performance of all three systems).

Systems compared
----------------
C — Stego only (--no-proof)    : chaos LSB, no ZK proof
D — ECDSA P-256 Digital Sig    : cryptographic primitive benchmark
   (This is NOT a DICOM PS3.15 full implementation — it benchmarks the
    underlying signing/verification operation on the same payload size,
    which is the fair cryptographic comparison.)

Output: results/b6_system_comparison.json

Run from ImageLevel/:
    python benchmarks/b6_system_comparison.py
"""

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import (
    DICOM_FILES, FIGURES_DIR,
    load_chaos_key, ensure_stego_noproof,
    save_results, Timer, apply_paper_style,
)
from src.zk_stego.dicom_handler import DicomHandler, DicomStego, DEFAULT_PROOF_KEY

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ===========================================================================
# Benchmark C — Stego-only timing
# ===========================================================================

def benchmark_c_stego_only(n_runs: int = 10) -> dict:
    """
    Time embed + extract WITHOUT ZK proof over all test images.
    This is identical to the full pipeline minus the witness/proving phases.

    Key insight: pixel quality (PSNR/SSIM) and steganalysis results are
    IDENTICAL to Stego+ZK — the ZK proof only adds overhead on the embed
    side, it does not change the carrier image pixels.
    """
    print("\n  Benchmark C: Stego-only (--no-proof)")
    chaos_key = load_chaos_key()

    results = []

    for dcm in DICOM_FILES:
        print(f"  [{dcm.name}] ", end="", flush=True)
        embed_times   = []
        extract_times = []
        out_png = ROOT / "benchmarks" / "results" / f"_bcC_{dcm.stem}.png"

        for _ in range(n_runs):
            t0 = time.perf_counter()
            DicomStego(project_root=str(ROOT)).embed(
                str(dcm), str(out_png),
                chaos_key=chaos_key,
                proof_key=DEFAULT_PROOF_KEY,
                generate_zk_proof=False,
                verbose=False,
            )
            embed_times.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            DicomStego(project_root=str(ROOT)).extract(
                str(out_png),
                chaos_key=chaos_key,
                proof_key=DEFAULT_PROOF_KEY,
            )
            extract_times.append(time.perf_counter() - t0)

        em = statistics.mean(embed_times)
        es = statistics.stdev(embed_times) if n_runs > 1 else 0.0
        xm = statistics.mean(extract_times)
        xs = statistics.stdev(extract_times) if n_runs > 1 else 0.0
        print(f"embed={em:.3f}s  extract={xm:.3f}s")

        results.append({
            "image":            dcm.stem,
            "embed_mean_s":     round(em, 4),
            "embed_std_s":      round(es, 4),
            "extract_mean_s":   round(xm, 4),
            "extract_std_s":    round(xs, 4),
        })

    return {
        "benchmark":       "C_stego_only",
        "n_runs":          n_runs,
        "per_image":       results,
        "summary": {
            "embed_mean_s":   round(float(np.mean([r["embed_mean_s"]   for r in results])), 4),
            "embed_std_s":    round(float(np.std( [r["embed_mean_s"]   for r in results])), 4),
            "extract_mean_s": round(float(np.mean([r["extract_mean_s"] for r in results])), 4),
        },
        "note": (
            "Pixel quality (PSNR/SSIM) and steganalysis results are identical "
            "to Stego+ZK — the ZK proof does not change the carrier pixels."
        ),
    }


# ===========================================================================
# Benchmark D — ECDSA P-256 Digital Signature
# ===========================================================================

def benchmark_d_ecdsa(n_runs: int = 1000) -> dict:
    """
    Benchmark ECDSA P-256 signing and verification on the DICOM metadata payload.

    Uses the same payload (gzip-compressed metadata JSON) that this system
    embeds, so the comparison is apples-to-apples in terms of what is being
    protected.

    This benchmarks the *cryptographic primitive*, not a full DICOM PS3.15
    implementation (which requires a CA hierarchy and DICOM toolkit).
    The primitive cost is the honest comparison with Groth16 proof generation.

    Requires: pip install cryptography
    """
    print("\n  Benchmark D: ECDSA P-256 Digital Signature")

    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes, serialization
    except ImportError:
        return {
            "benchmark": "D_ecdsa",
            "error": (
                "The 'cryptography' package is not installed. "
                "Run: pip install cryptography"
            ),
        }

    # Use the first test image for the payload size representative
    dcm = DICOM_FILES[0]
    import gzip
    _, metadata_json, _ = DicomHandler.load(str(dcm))
    payload = gzip.compress(metadata_json.encode("utf-8"), compresslevel=9)
    print(f"  Payload size: {len(payload)} bytes (gzip-compressed DICOM metadata)")

    # --- Key generation (one-time setup, not per-image) ---
    t0 = time.perf_counter()
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key  = private_key.public_key()
    keygen_time = time.perf_counter() - t0

    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    # --- Sign ---
    sign_times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        sign_times.append(time.perf_counter() - t0)

    # --- Verify ---
    verify_times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        verify_times.append(time.perf_counter() - t0)

    sm = statistics.mean(sign_times)   * 1000
    ss = statistics.stdev(sign_times)  * 1000
    vm = statistics.mean(verify_times) * 1000
    vs = statistics.stdev(verify_times)* 1000

    print(f"  Key generation   : {keygen_time*1000:.3f} ms (one-time)")
    print(f"  Sign ({n_runs} runs) : mean={sm:.3f} ms  std={ss:.3f} ms")
    print(f"  Verify({n_runs} runs): mean={vm:.3f} ms  std={vs:.3f} ms")
    print(f"  Signature size   : {len(signature)} bytes (DER-encoded)")
    print(f"  Public key size  : {len(pub_bytes)} bytes (uncompressed)")

    return {
        "benchmark":            "D_ecdsa_p256",
        "n_runs":               n_runs,
        "payload_bytes":        len(payload),
        "keygen_time_ms":       round(keygen_time * 1000, 4),
        "sign_mean_ms":         round(sm, 4),
        "sign_std_ms":          round(ss, 4),
        "verify_mean_ms":       round(vm, 4),
        "verify_std_ms":        round(vs, 4),
        "signature_bytes_der":  len(signature),
        "public_key_bytes_uncompressed": len(pub_bytes),
        "note": (
            "ECDSA P-256 (SECP256R1). Sign/verify time on gzip-compressed DICOM "
            "metadata payload. Keygen is one-time and not counted per-image. "
            "This benchmarks the cryptographic primitive only — DICOM PS3.15 "
            "full integration also requires PKI infrastructure."
        ),
    }


# ===========================================================================
# Comparison table / figure
# ===========================================================================

def plot_comparison_table(c_result: dict, d_result: dict) -> Path:
    """
    Side-by-side bar charts: embed/sign time and verify time across three systems.
    Uses b5 results for Stego+ZK if available, otherwise estimated values.
    """
    from benchmarks._common import load_results
    b5 = load_results("b5_performance.json")

    # Try to get ZK timing from b5 results
    if b5 and b5.get("zk_timing"):
        zk_embed_s  = b5["zk_timing"]["mean_s"]
        zk_verify_s = None   # verification timing from extract — approximate
    else:
        zk_embed_s  = None   # not yet measured
        zk_verify_s = None

    out = FIGURES_DIR / "b6_performance_comparison.pdf"

    # Embed / sign times
    labels   = ["ECDSA Sign\n(ms, left axis)", "Stego only\n(s, right axis)", "Stego+ZK\n(s, right axis)"]
    colors   = ["#3498db", "#2ecc71", "#e74c3c"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("System performance comparison (Benchmark D vs C vs this work)")

    # Left: sign / embed times (note different units)
    stego_only_embed = c_result["summary"]["embed_mean_s"]
    ecdsa_sign_ms    = d_result.get("sign_mean_ms", 0) if "error" not in d_result else 0
    zk_embed_s_val   = zk_embed_s if zk_embed_s else 0

    ax = axes[0]
    ax.set_title("Embed / Sign time")
    b1 = ax.bar(["ECDSA\n(ms)"], [ecdsa_sign_ms], color="#3498db")
    ax.set_ylabel("ECDSA time (ms)", color="#3498db")
    ax2 = ax.twinx()
    ax2.bar(["Stego-only\n(s)", "Stego+ZK\n(s)"],
            [stego_only_embed, zk_embed_s_val or 0],
            color=["#2ecc71", "#e74c3c"])
    ax2.set_ylabel("Stego time (s)", color="#e74c3c")
    ax.set_xlabel("System")

    # Right: verify times
    stego_extract_s  = c_result["summary"]["extract_mean_s"]
    ecdsa_verify_ms  = d_result.get("verify_mean_ms", 0) if "error" not in d_result else 0

    ax = axes[1]
    ax.set_title("Verify / Extract time")
    ax.bar(["ECDSA\n(ms)"], [ecdsa_verify_ms], color="#3498db")
    ax.set_ylabel("ECDSA time (ms)", color="#3498db")
    ax3 = ax.twinx()
    ax3.bar(["Stego+Extract\n(s)"], [stego_extract_s], color="#2ecc71")
    ax3.set_ylabel("Extract time (s)", color="#2ecc71")

    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


# ===========================================================================
# Capability matrix (T6 data)
# ===========================================================================

CAPABILITY_TABLE = {
    "systems": [
        "DICOM Digital Sig (PS3.15)",
        "Stego only (--no-proof)",
        "This work (Stego + ZK)",
    ],
    "properties": {
        "Metadata hidden from DICOM viewers":   [False, True,  True ],
        "Integrity guarantee":                  ["RSA/ECDSA", "SHA-256 (key-bound)", "Groth16 + SHA-256"],
        "Publicly verifiable (no prover secret)":[True,  False, True ],
        "Proves embedding correctness":         [False, False, True ],
        "Covert channel":                       [False, True,  True ],
        "PKI required":                         [True,  False, False],
        "Detectable by DICOM tag inspection":   [True,  False, False],
        "Zero-knowledge property":              [False, False, True ],
    },
}


# ===========================================================================
# Figure F6 — Capability radar chart
# ===========================================================================

# Numeric scores for the six properties used in the radar.
# Each cell: 1 = property present / good, 0 = absent / bad.
# Rows are systems; columns are the six axes.
_RADAR_LABELS = [
    "Metadata covert\n(hidden from viewers)",
    "Publicly verifiable\n(no prover secret)",
    "Proves embedding\ncorrectness (ZK)",
    "Covert channel\n(steganalysis-resistant)",
    "No PKI required",
    "Zero-knowledge\nproperty",
]
_RADAR_SCORES = {
    # label                                  : [ECDSA, Stego-only, This work]
    "Metadata covert\n(hidden from viewers)" : [0, 1, 1],
    "Publicly verifiable\n(no prover secret)": [1, 0, 1],
    "Proves embedding\ncorrectness (ZK)"     : [0, 0, 1],
    "Covert channel\n(steganalysis-resistant)": [0, 1, 1],
    "No PKI required"                        : [0, 1, 1],
    "Zero-knowledge\nproperty"               : [0, 0, 1],
}


def plot_capability_radar() -> Path:
    """
    F6 — Radar / spider chart comparing three systems across six capability
    dimensions.  Each axis is binary (0 = absent, 1 = present).
    """
    out = FIGURES_DIR / "b6_capability_radar.pdf"

    labels  = list(_RADAR_SCORES.keys())
    n_axes  = len(labels)
    scores  = np.array([_RADAR_SCORES[l] for l in labels], dtype=float)  # (n_axes, 3)

    # Compute angles; close the polygon by repeating the first point
    angles = np.linspace(0, 2 * np.pi, n_axes, endpoint=False).tolist()
    angles += angles[:1]

    system_names = ["DICOM Digital Sig", "Stego only", "This work (Stego+ZK)"]
    colors       = ["#3498db", "#2ecc71", "#e74c3c"]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))

    for idx, (name, color) in enumerate(zip(system_names, colors)):
        vals = scores[:, idx].tolist()
        vals += vals[:1]          # close polygon
        ax.plot(angles, vals, "o-", color=color, linewidth=2,   label=name)
        ax.fill(angles, vals,         color=color, alpha=0.12)

    # Axis labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_yticks([0, 0.5, 1])
    ax.set_yticklabels(["0", "0.5", "1"], fontsize=7, color="grey")
    ax.set_ylim(0, 1.15)
    ax.set_title("System capability comparison (F6)", fontsize=12, pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), frameon=False, fontsize=9)

    fig.tight_layout()
    fig.savefig(str(out), bbox_inches="tight")
    plt.close(fig)
    return out
# Main
# ===========================================================================

def run() -> dict:
    apply_paper_style()
    print("\n" + "="*60)
    print("B6  System-Level Comparison")
    print("="*60)

    c_result = benchmark_c_stego_only(n_runs=10)
    d_result = benchmark_d_ecdsa(n_runs=1000)

    # Print T4-style performance table
    print("\n  Performance table (T4 extended):")
    print(f"  {'System':30s}  {'Embed/Sign':>15}  {'Verify/Extract':>15}  {'Proof/Sig size':>15}")
    print("  " + "-"*80)

    c_embed   = f"{c_result['summary']['embed_mean_s']:.3f} s"
    c_extract = f"{c_result['summary']['extract_mean_s']:.3f} s"
    print(f"  {'Stego only (--no-proof)':30s}  {c_embed:>15}  {c_extract:>15}  {'0 bytes':>15}")

    if "error" not in d_result:
        d_sign  = f"{d_result['sign_mean_ms']:.3f} ms"
        d_verify= f"{d_result['verify_mean_ms']:.3f} ms"
        d_size  = f"{d_result['signature_bytes_der']} bytes"
        print(f"  {'ECDSA P-256 (Digital Sig)':30s}  {d_sign:>15}  {d_verify:>15}  {d_size:>15}")
    else:
        print(f"  {'ECDSA P-256 (Digital Sig)':30s}  {'N/A':>15}  {'N/A':>15}  {'N/A':>15}")

    print(f"  {'Stego+ZK (see b5_perf.)':30s}  {'see b5':>15}  {'see b5':>15}  {'~2 KB':>15}")

    try:
        plot_comparison_table(c_result, d_result)
        radar_out = plot_capability_radar()
        print(f"  Radar chart saved → {radar_out.name}")
    except Exception as e:
        print(f"  (Figure skipped: {e})")

    report = {
        "benchmark_c_stego_only": c_result,
        "benchmark_d_ecdsa":      d_result,
        "capability_table":       CAPABILITY_TABLE,
        "note": (
            "ECDSA benchmarks the cryptographic primitive only. "
            "Full DICOM PS3.15 digital signatures require additional PKI overhead "
            "(certificate chain lookup, timestamp authority, CA infrastructure). "
            "Groth16 ZK proof timing: see b5_performance.json zk_timing entry."
        ),
    }
    save_results("b6_system_comparison.json", report)
    return report


if __name__ == "__main__":
    run()
