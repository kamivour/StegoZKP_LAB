"""
benchmarks/run_all.py  —  Master benchmark runner
==================================================
Runs all benchmark scripts in order and prints a final summary.

Usage (from ImageLevel/):
    python benchmarks/run_all.py           # full run (includes ZK timing)
    python benchmarks/run_all.py --fast    # skip ZK timing in b5

Individual scripts can be run independently:
    python benchmarks/b1_quality.py
    python benchmarks/b2_steganalysis.py
    python benchmarks/b3_baselines.py
    python benchmarks/b4_zk_metrics.py
    python benchmarks/b5_performance.py [--fast]
    python benchmarks/b6_system_comparison.py

Results are written to benchmarks/results/ as JSON files.
Figures are written to benchmarks/results/figures/ as PDF files.
"""

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAST = "--fast" in sys.argv


def _run(label: str, fn):
    """Run a benchmark function, catching exceptions so others still run."""
    print(f"\n{'='*60}")
    print(f"Running {label} …")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    try:
        result = fn()
        elapsed = time.perf_counter() - t0
        print(f"\n  ✓ {label} completed in {elapsed:.1f} s")
        return True, elapsed
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"\n  ✗ {label} FAILED after {elapsed:.1f} s: {exc}")
        traceback.print_exc()
        return False, elapsed


def main():
    print("ZK-SNARK DICOM Steganography — Full Benchmark Suite")
    print(f"Fast mode: {'YES (skipping ZK timing in b5)' if FAST else 'NO'}")
    print(f"Results → benchmarks/results/")

    from benchmarks import b1_quality, b2_steganalysis, b3_baselines
    from benchmarks import b4_zk_metrics, b5_performance, b6_system_comparison

    suite = [
        ("B1 Image Quality",         b1_quality.run),
        ("B2 Steganalysis",          b2_steganalysis.run),
        ("B3 Baseline Comparison",   b3_baselines.run),
        ("B4 ZK Metrics",            b4_zk_metrics.run),
        ("B5 Performance",           lambda: b5_performance.run(fast=FAST)),
        ("B6 System Comparison",     b6_system_comparison.run),
    ]

    total_start = time.perf_counter()
    summary = []
    for label, fn in suite:
        ok, elapsed = _run(label, fn)
        summary.append({"benchmark": label, "pass": ok, "elapsed_s": round(elapsed, 1)})

    total = time.perf_counter() - total_start
    print(f"\n{'='*60}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*60}")
    for s in summary:
        status = "✓" if s["pass"] else "✗"
        print(f"  {status}  {s['benchmark']:30s}  {s['elapsed_s']:>6.1f} s")
    passed = sum(1 for s in summary if s["pass"])
    print(f"\n  {passed}/{len(summary)} benchmarks passed   Total: {total:.1f} s")
    print(f"\n  Results saved to: benchmarks/results/")
    print(f"  Figures saved to: benchmarks/results/figures/")


if __name__ == "__main__":
    main()
