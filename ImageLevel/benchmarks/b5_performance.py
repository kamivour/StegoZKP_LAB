"""
benchmarks/b5_performance.py  —  §5 Performance Benchmarks
============================================================
Measures timing, memory, and file-size overhead across all test images.

Measurements
------------
- Total embed time (no proof)      N=10 runs, mean ± std
- Total embed time (with ZK proof) N=3 runs  (slow; use --fast to skip)
- Extraction time                  N=10 runs
- ZK verification overhead        = embed_zk_mean − embed_noproof_mean
- Peak memory during embed (tracemalloc)
- File size: DICOM .dcm vs stego .png

Output: results/b5_performance.json
        results/figures/b5_timing_breakdown.pdf

Run from ImageLevel/:
    python benchmarks/b5_performance.py
    python benchmarks/b5_performance.py --fast   (skip ZK timing, use cached)
"""

import sys
import time
import gzip
import tracemalloc
import statistics
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import (
    DICOM_FILES, FIGURES_DIR, RESULTS_DIR,
    load_chaos_key, ensure_stego_noproof, ensure_stego_zk,
    save_results, Timer, apply_paper_style,
)
from src.zk_stego.dicom_handler import DicomHandler, DicomStego, DEFAULT_PROOF_KEY

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ===========================================================================
# Timing helpers
# ===========================================================================

def time_embed_noproof(dcm: Path, n: int = 10) -> dict:
    """Time the full embed pipeline WITHOUT ZK proof, N runs."""
    chaos_key = load_chaos_key()
    times = []
    for i in range(n):
        # Write to a temp file each run so we measure consistently
        out = RESULTS_DIR / f"_perf_noproof_{dcm.stem}.png"
        t0 = time.perf_counter()
        DicomStego(project_root=str(ROOT)).embed(
            str(dcm), str(out),
            chaos_key=chaos_key,
            proof_key=DEFAULT_PROOF_KEY,
            generate_zk_proof=False,
            verbose=False,
        )
        times.append(time.perf_counter() - t0)
    return _stats(times, "embed_noproof_s")


def time_embed_zk(dcm: Path, n: int = 3) -> dict:
    """Time the full embed pipeline WITH ZK proof, N runs (SLOW)."""
    chaos_key = load_chaos_key()
    times = []
    for i in range(n):
        out = RESULTS_DIR / f"_perf_zk_{dcm.stem}.png"
        t0 = time.perf_counter()
        DicomStego(project_root=str(ROOT)).embed(
            str(dcm), str(out),
            chaos_key=chaos_key,
            proof_key=DEFAULT_PROOF_KEY,
            generate_zk_proof=True,
            verbose=False,
        )
        times.append(time.perf_counter() - t0)
    return _stats(times, "embed_zk_s")


def time_extract(dcm: Path, n: int = 10) -> dict:
    """Time extraction from a no-proof stego PNG (ZK only affects embed side)."""
    chaos_key = load_chaos_key()
    png = ensure_stego_noproof(dcm)
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        DicomStego(project_root=str(ROOT)).extract(
            str(png),
            chaos_key=chaos_key,
            proof_key=DEFAULT_PROOF_KEY,
        )
        times.append(time.perf_counter() - t0)
    return _stats(times, "extract_s")


def _stats(values: list, label: str) -> dict:
    return {
        "label":  label,
        "n":      len(values),
        "mean_s": round(statistics.mean(values), 4),
        "std_s":  round(statistics.stdev(values) if len(values) > 1 else 0.0, 4),
        "min_s":  round(min(values), 4),
        "max_s":  round(max(values), 4),
        "all_s":  [round(v, 4) for v in values],
    }


# ===========================================================================
# Phase-level timing (single run, instrumented manually)
# ===========================================================================

def time_phases(dcm: Path) -> dict:
    """
    Break the embed pipeline into individual phases and time each one.
    Uses the public API; phases = ordered timing checkpoints.
    """
    import pydicom

    chaos_key = load_chaos_key()

    phases = {}

    with Timer() as t:
        ds = pydicom.dcmread(str(dcm))
        pixel_array = DicomHandler.to_uint16(ds.pixel_array)
    phases["load_dicom"] = t.elapsed

    with Timer() as t:
        metadata_json = DicomHandler.extract_metadata_dict(ds)
    phases["extract_metadata"] = t.elapsed

    with Timer() as t:
        roi_mask = DicomHandler.detect_roi(pixel_array)
    phases["detect_roi"] = t.elapsed

    with Timer() as t:
        import json
        meta_bytes = gzip.compress(
            json.dumps(metadata_json).encode("utf-8"), compresslevel=9
        )
    phases["gzip_compress"] = t.elapsed

    from src.zk_stego.utils import ChaosGenerator, generate_chaos_key_from_secret
    chaos_key_int = generate_chaos_key_from_secret(chaos_key)
    proof_key_int = generate_chaos_key_from_secret(DEFAULT_PROOF_KEY)
    h, w = pixel_array.shape

    with Timer() as t:
        gen = ChaosGenerator(w, h)
        pk_x0, pk_y0 = proof_key_int % w, (proof_key_int // w) % h
        proof_pos = gen.generate_positions(pk_x0, pk_y0, proof_key_int, 600)
    phases["proof_key_positions"] = t.elapsed

    with Timer() as t:
        ck_x0, ck_y0 = chaos_key_int % w, (chaos_key_int // w) % h
        meta_pos = gen.generate_positions(ck_x0, ck_y0, chaos_key_int, len(meta_bytes) * 4 + 200)
    phases["chaos_key_positions"] = t.elapsed

    # Embed (using full DicomStego for accuracy)
    out_tmp = RESULTS_DIR / f"_perf_phases_{dcm.stem}.png"
    with Timer() as t:
        DicomStego(project_root=str(ROOT)).embed(
            str(dcm), str(out_tmp),
            chaos_key=chaos_key,
            generate_zk_proof=False,
            verbose=False,
        )
    phases["full_embed_noproof"] = t.elapsed

    return {k: round(v * 1000, 3) for k, v in phases.items()}   # milliseconds


# ===========================================================================
# Memory profiling
# ===========================================================================

def measure_memory(dcm: Path, with_zk: bool = False) -> dict:
    """Measure peak RAM during embed using tracemalloc."""
    chaos_key = load_chaos_key()
    out = RESULTS_DIR / f"_perf_mem_{dcm.stem}.png"

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    DicomStego(project_root=str(ROOT)).embed(
        str(dcm), str(out),
        chaos_key=chaos_key,
        generate_zk_proof=with_zk,
        verbose=False,
    )

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "mode":         "with_zk" if with_zk else "no_proof",
        "current_mb":   round(current  / 1024**2, 2),
        "peak_mb":      round(peak     / 1024**2, 2),
    }


# ===========================================================================
# File-size overhead
# ===========================================================================

def measure_file_sizes(dcm: Path) -> dict:
    """Compare DICOM .dcm size vs stego .png size."""
    png = ensure_stego_noproof(dcm)
    dcm_bytes = dcm.stat().st_size
    png_bytes = png.stat().st_size

    _, metadata_json, _ = DicomHandler.load(str(dcm))
    meta_compressed = gzip.compress(metadata_json.encode(), compresslevel=9)

    return {
        "dicom_bytes":     dcm_bytes,
        "dicom_kb":        round(dcm_bytes / 1024, 1),
        "stego_png_bytes": png_bytes,
        "stego_png_kb":    round(png_bytes / 1024, 1),
        "delta_bytes":     png_bytes - dcm_bytes,
        "metadata_raw_bytes": len(metadata_json.encode()),
        "metadata_gzip_bytes": len(meta_compressed),
    }


# ===========================================================================
# Timing figure
# ===========================================================================

def plot_phase_chart(phases: dict, dcm_stem: str) -> Path:
    """Horizontal bar chart of per-phase times (ms)."""
    out = FIGURES_DIR / "b5_timing_phases.pdf"
    labels = list(phases.keys())
    values = list(phases.values())

    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(labels, values, color="steelblue", edgecolor="white")
    ax.set_xlabel("Time (ms)")
    ax.set_title(f"Per-phase timing — {dcm_stem}")
    for bar, v in zip(bars, values):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                f"{v:.1f} ms", va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


def plot_timing_per_image(per_image: list) -> Path:
    out = FIGURES_DIR / "b5_timing_per_image.pdf"
    stems  = [r["image"] for r in per_image]
    times  = [r["embed_noproof"]["mean_s"] for r in per_image]
    etimes = [r["extract"]["mean_s"]       for r in per_image]

    x = np.arange(len(stems))
    w = 0.35
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(x - w/2, times,  w, label="Embed (no proof)", color="steelblue")
    ax.bar(x + w/2, etimes, w, label="Extract",          color="coral")
    ax.set_xticks(x)
    ax.set_xticklabels(stems, rotation=45, ha="right")
    ax.set_ylabel("Time (s)")
    ax.set_title("Embed / Extract time per image")
    ax.legend()
    fig.tight_layout()
    fig.savefig(str(out))
    plt.close(fig)
    return out


# ===========================================================================
# Main
# ===========================================================================

def run(fast: bool = False) -> dict:
    apply_paper_style()
    print("\n" + "="*60)
    print("B5  Performance Benchmarks")
    print("="*60)
    if fast:
        print("  --fast mode: skipping ZK timing (use cached stego PNGs)")

    per_image = []
    all_embed_times = []
    all_extract_times = []
    all_file_sizes = []

    for dcm in DICOM_FILES:
        print(f"\n[{dcm.name}]")

        print("  Embed timing (no proof, N=10) … ", end="", flush=True)
        embed_t = time_embed_noproof(dcm, n=10)
        all_embed_times.append(embed_t["mean_s"])
        print(f"mean={embed_t['mean_s']:.3f}s  std={embed_t['std_s']:.3f}s")

        print("  Extract timing (N=10) … ", end="", flush=True)
        extract_t = time_extract(dcm, n=10)
        all_extract_times.append(extract_t["mean_s"])
        print(f"mean={extract_t['mean_s']:.3f}s  std={extract_t['std_s']:.3f}s")

        print("  File sizes … ", end="", flush=True)
        sizes = measure_file_sizes(dcm)
        all_file_sizes.append(sizes)
        print(f"DICOM={sizes['dicom_kb']:.0f} KB  PNG={sizes['stego_png_kb']:.0f} KB  "
              f"delta={sizes['delta_bytes']/1024:+.1f} KB")

        per_image.append({
            "image":        dcm.stem,
            "embed_noproof": embed_t,
            "extract":       extract_t,
            "file_sizes":    sizes,
        })

    # Phase breakdown (first image only — representative)
    print(f"\n  Phase-level timing for {DICOM_FILES[0].name} …")
    phases = time_phases(DICOM_FILES[0])
    for ph, ms in phases.items():
        print(f"    {ph:35s} {ms:>8.1f} ms")
    plot_phase_chart(phases, DICOM_FILES[0].stem)

    # Memory (first image, no-proof only)
    print(f"\n  Memory profiling (no-proof embed) … ", end="", flush=True)
    mem = measure_memory(DICOM_FILES[0], with_zk=False)
    print(f"peak={mem['peak_mb']:.1f} MB")

    zk_timing = None
    if not fast:
        print(f"\n  ZK embed timing (N=3, SLOW) for {DICOM_FILES[0].name} … ", flush=True)
        zk_timing = time_embed_zk(DICOM_FILES[0], n=3)
        zk_overhead = zk_timing["mean_s"] - next(
            r["embed_noproof"]["mean_s"] for r in per_image
            if r["image"] == DICOM_FILES[0].stem
        )
        print(f"  ZK mean={zk_timing['mean_s']:.1f}s  overhead≈{zk_overhead:.1f}s")
        zk_timing["zk_overhead_s"] = round(zk_overhead, 2)

    # Summary
    plot_timing_per_image(per_image)

    report = {
        "per_image":       per_image,
        "phases_ms":       phases,
        "memory":          mem,
        "zk_timing":       zk_timing,
        "summary": {
            "embed_noproof_s": {
                "mean": round(float(np.mean(all_embed_times)), 4),
                "std":  round(float(np.std(all_embed_times)),  4),
            },
            "extract_s": {
                "mean": round(float(np.mean(all_extract_times)), 4),
                "std":  round(float(np.std(all_extract_times)),  4),
            },
            "file_size_delta_bytes": {
                "mean": round(float(np.mean([s["delta_bytes"] for s in all_file_sizes])), 0),
            },
        },
        "system_info_note": "Report CPU model, RAM, OS when publishing these results",
    }

    save_results("b5_performance.json", report)
    return report


if __name__ == "__main__":
    fast_mode = "--fast" in sys.argv
    run(fast=fast_mode)
