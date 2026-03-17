# Benchmarks

End-to-end benchmark suite for the ZK-SNARK DICOM Steganography paper.

All scripts run from the **`ImageLevel/`** directory.

```
benchmarks/
├── _common.py                # Shared helpers (path setup, key loading, etc.)
├── b1_quality.py             # §1  Image quality: PSNR, SSIM, MSE, BPP
├── b2_steganalysis.py        # §2  Steganalysis: RS, Chi-square, SPA
├── b3_baselines.py           # §3  Baselines: Sequential LSB, PRNG-LSB, ACM-only
├── b4_zk_metrics.py          # §4  ZK: correctness tests, artifact sizes, constraints
├── b5_performance.py         # §5  Performance: timing, memory, file-size overhead
├── b6_system_comparison.py   # §6  System comparison: Stego-only + ECDSA P-256
├── run_all.py                # Master runner
└── results/                  # Output JSONs + PDF figures (auto-created)
    └── figures/
```

---

## Prerequisites

```bash
# From ImageLevel/
pip install scikit-image matplotlib scipy
pip install cryptography     # needed only for b6 ECDSA benchmark
```

A `chaos_key.txt` must exist in `ImageLevel/` (already present).

---

## Quick start

```bash
# From ImageLevel/
python benchmarks/run_all.py           # full suite (includes ZK timing ~30-120 s)
python benchmarks/run_all.py --fast    # skip ZK timing in b5, use cached PNGs
```

### Individual scripts

```bash
python benchmarks/b1_quality.py
python benchmarks/b2_steganalysis.py
python benchmarks/b3_baselines.py
python benchmarks/b4_zk_metrics.py
python benchmarks/b5_performance.py
python benchmarks/b5_performance.py --fast   # skip ZK timing
python benchmarks/b6_system_comparison.py
```

---

## What each script does

### b1_quality.py — Image Quality Metrics
- PSNR, SSIM, MSE, BPP for all 10 test DICOMs
- Histogram overlay figures (cover vs stego)
- LSB bit-plane visualisation (4-panel grid)
- **Output:** `b1_quality.json`, `figures/b1_histogram_*.pdf`, `figures/b1_lsb_planes_*.pdf`

### b2_steganalysis.py — Steganalysis Resistance
- RS Analysis (Fridrich et al. 2001)
- Chi-Square test (Westfeld & Pfitzmann 1999)
- SPA estimate (Dumitrescu et al. 2003)
- All tests performed on the bottom 8 bits of each uint16 pixel
- **Output:** `b2_steganalysis.json`, `figures/b2_rs_bars_*.pdf`

### b3_baselines.py — Baseline Comparison
Implements and tests 4 LSB embedders on the same DICOM payload:

| ID | Scheme |
|---|---|
| A | Sequential LSB (left-to-right in ROI) |
| B | PRNG-LSB (numpy RNG permutation) |
| C | ACM-only (Arnold Cat Map, no Logistic Map) |
| D | **This work** (ACM + Logistic Map chaos) |

- **Output:** `b3_baselines.json`, `figures/b3_comparison.pdf`

### b4_zk_metrics.py — ZK-Specific Metrics
Runs 7 correctness/soundness tests:

| Test | Expected |
|---|---|
| T1 Valid proof verifies | PASS |
| T2 Tampered image → ZK fail | FAIL |
| T3 Wrong chaos_key → rejected | error/integrity=False |
| T4 No-proof embed → integrity OK | integrity PASS, zk_verified False |
| T5 Artifact sizes | reports sizes |
| T6 Constraint count | 18,429 |
| T7 Two-key position separation | 0 overlaps |

> **Note:** T1 and T2 require a ZK embed (~30–120 s on first run). Subsequent runs use cached PNGs.

- **Output:** `b4_zk_metrics.json`

### b5_performance.py — Performance Benchmarks
- Embed timing (no proof), N=10 runs, mean ± std
- Extract timing, N=10 runs
- ZK embed timing, N=3 runs (slow; skip with `--fast`)
- Per-phase breakdown (load, ROI, gzip, positions, embed)
- Peak memory via `tracemalloc`
- File-size overhead (DICOM .dcm vs stego .png)
- **Output:** `b5_performance.json`, `figures/b5_timing_*.pdf`

### b6_system_comparison.py — System-Level Comparison
- **Benchmark C:** Stego-only (`--no-proof`) timing over all images
- **Benchmark D:** ECDSA P-256 sign + verify, N=1,000 runs
- Capability comparison table (T6 data)
- **Output:** `b6_system_comparison.json`, `figures/b6_performance_comparison.pdf`

---

## Results files

| File | Description |
|---|---|
| `b1_quality.json` | PSNR/SSIM/MSE/BPP per image + summary stats |
| `b2_steganalysis.json` | RS/chi-square/SPA for cover and stego |
| `b3_baselines.json` | All metrics for all 4 embedding schemes |
| `b4_zk_metrics.json` | 7 pass/fail tests + artifact sizes |
| `b5_performance.json` | Per-phase timing, memory, file sizes |
| `b6_system_comparison.json` | Stego-only timing + ECDSA P-256 data |

---

## Expected results summary

| Metric | Expected |
|---|---|
| PSNR (stego vs cover) | 86–92 dB |
| SSIM | ≥ 0.9999 |
| Chi-square p-value (stego) | similar to cover (> 0.05) |
| RS p_hat (stego) | ≈ 0 |
| ZK correctness tests | 7/7 PASS |
| Constraints | 18,429 |
| ECDSA sign time | < 1 ms |
| ECDSA verify time | < 2 ms |
| ECDSA signature size | 71–72 bytes |
