# Benchmarking Plan for ZK-SNARK DICOM Steganography Paper

This document maps every claim a scientific paper on this system needs to
support to a concrete, reproducible benchmark.  Each section states:
**what claim it supports → what to measure → how to implement it → what to
report**.

---

## 0. First Principles: What Claims Need Evidence?

A paper on this system makes (at minimum) four families of claim:

| Claim | Benchmark family |
|---|---|
| The stego image is imperceptible to human and algorithmic inspection | §1 Quality metrics, §2 Steganalysis resistance |
| The chaos-based position scheme is more secure than naive LSB variants | §3 Baseline comparison |
| The ZK proof actually proves what it says | §4 ZK-specific metrics |
| The system is practical (fast enough, cheap enough) | §5 Performance benchmarks |

Your mentor is correct: PSNR/SSIM **alone** prove imperceptibility, but not
security.  A stego image can look identical to the eye yet be trivially
detected by RS analysis.  Both families are needed.

---

## 1. Image Quality Metrics (Imperceptibility)

**Claim supported:** 2-LSB embedding in 16-bit pixels causes negligible
visual distortion.

### 1.1 Standard metrics

| Metric | Formula | Implementation |
|---|---|---|
| **PSNR** (dB) | $10 \log_{10}(MAX^2 / MSE)$ | `skimage.metrics.peak_signal_noise_ratio` |
| **SSIM** | Structural similarity index | `skimage.metrics.structural_similarity` |
| **MSE** | Mean squared error | `skimage.metrics.mean_squared_error` |
| **BPP** | Bits per pixel embedded | `payload_bits / (H × W)` |

For 16-bit images, `MAX = 65535`.  Use `data_range=65535` in skimage
calls — the default assumes 8-bit and will give wrong PSNR.

Expected results for 2-LSB on a 512×512 MR:
- PSNR ≈ **86–92 dB** (well above the perceptibility threshold of ~40 dB)
- SSIM ≈ **0.9999**
- MSE ≈ **2–4**

> Report: mean ± std across all 10 DICOM test images.

### 1.2 Pixel intensity histogram

Plot the histogram of raw uint16 pixel values before and after embedding.
The two histograms should be overlapping — any visible shift indicates
over-embedding.

```python
import numpy as np, pydicom, matplotlib.pyplot as plt
from PIL import Image

orig = pydicom.dcmread("1-01.dcm").pixel_array.astype(np.uint16)
stego = np.array(Image.open("1-01_stego.png"), dtype=np.uint16)

plt.figure(figsize=(10, 3))
plt.hist(orig.ravel(),  bins=256, alpha=0.6, label="Cover",  color="steelblue")
plt.hist(stego.ravel(), bins=256, alpha=0.6, label="Stego",  color="crimson")
plt.legend(); plt.xlabel("Pixel value"); plt.ylabel("Count")
plt.savefig("histogram_comparison.pdf")
```

> Report: overlay histogram figure for at least one representative scan
> (MR, CT if available).  Visual overlap confirms imperceptibility.

### 1.3 LSB plane visualisation

Extract bit-plane 0 and bit-plane 1 from cover and stego.  Embedding should
appear random (high entropy), not structured.

> Report: 2×2 grid figure (cover bit-0, cover bit-1, stego bit-0, stego bit-1).

### 1.4 Payload capacity

| Property | Value (512×512 MR) |
|---|---|
| Total pixels | 262,144 |
| ROI pixels (5th-pct method) | ~185,568 (70.8 %) |
| Max bits embeddable | ~371,136 |
| Typical DICOM metadata (gzip) | ~20,000 bits |
| Payload utilisation | ~5.4 % |

At 5.4 % utilisation, all detectability metrics should stay near
the unmodified baseline — report the actual utilisation for each test image.

---

## 2. Steganalysis Resistance

**Claim supported:** The chaos-based position selection makes the image
statistically indistinguishable from an unmodified cover.

These are the classical attacks your examiner or reviewer will expect.  All
three can be implemented in pure Python.

### 2.1 RS Analysis (Fridrich et al., 2001)

RS analysis is the canonical statistical test against sequential LSB — it
detects the characteristic asymmetry that sequential embedding introduces
between regular (R), singular (S), and negative-regular (-R) groups.

A **chaos-based / PRNG** system should yield R ≈ S (not significantly
different from a cover image), while plain sequential LSB will exhibit a
clear R−S split.

**Implementation sketch:**

```python
def rs_analysis(img_array: np.ndarray) -> dict:
    """
    Fridrich, Goljan, Du — 'Reliable Detection of LSB Steganography'
    Returns Rm, Sm (mask +1) and Rm_, Sm_ (mask −1) group sizes,
    and estimated payload fraction p.
    """
    # flip_mask: +1 mask (flip LSB) and -1 mask (flip LSB negatively)
    # Group pixels into 2x2 blocks, compute smoothness function f
    # Classify each block as R, S, or U under each mask direction
    # p_hat = (Rm - Rm_) / (Rm - Rm_ + Sm_ - Sm)
    ...
```

Full reference implementation: Fridrich, J., Goljan, M., & Du, R. (2001).
*Reliable detection of LSB steganography in color and grayscale images.*
ACM Multimedia Security Workshop.

> Report: Rm, Sm, Rm_, Sm_ for cover image, plain LSB, PRNG-LSB, and your
> system.  Also report estimated payload fraction p̂ (should be near 0 for
> your system even at full capacity).

### 2.2 Chi-Square Attack (Westfeld & Pfitzmann, 1999)

The chi-square test measures the expected 50/50 split between pairs of
values that differ only in their LSB (PoV pairs).  Sequential LSB forces
this split; random embedding preserves the natural distribution.

```python
def chi_square_attack(img_array: np.ndarray) -> float:
    """
    Returns p-value: large p → not detectable; small p (< 0.05) → detected.
    """
    pixels = img_array.ravel().astype(np.int64)
    # Count occurrences of each value 0..65534 (pair with value+1)
    counts = np.bincount(pixels, minlength=65536)
    pov_exp = (counts[0::2] + counts[1::2]) / 2   # expected under H0
    chi_sq  = np.sum((counts[0::2] - pov_exp)**2 / (pov_exp + 1e-9))
    from scipy.stats import chi2
    return chi2.sf(chi_sq, df=len(pov_exp) - 1)
```

> Report: p-value for cover, plain LSB, PRNG-LSB, your system.  Expected:
> plain LSB → p ≈ 0 (detected), your system → p ≈ same as cover.

### 2.3 Sample Pairs Analysis (SPA) (Dumitrescu et al., 2003)

SPA estimates embedding rate from the probability of value-adjacent pairs —
more robust than chi-square against non-sequential schemes.

Reference:  Dumitrescu, S., Wu, X., & Wang, Z. (2003). *Detection of LSB
steganography via sample pair analysis.* IEEE Transactions on Signal
Processing.

SPA implementations exist in Python in the Aletheia steganalysis tool
(see §2.4).

> Report: estimated payload fraction from SPA for all four systems.

### 2.4 Aletheia (optional but recommended)

[Aletheia](https://github.com/daniellerch/aletheia) by Daniel Lerch is an
open-source Python steganalysis framework that includes RS, SPA, chi-square,
and pre-trained CNN-based detectors (e.g., SRNet, Yedroudj-Net) for grayscale
images.  Their CNN models are trained on 8-bit images; they may need
retraining or fine-tuning for 16-bit DICOM.

If CNN-based detection is out of scope:
- State this explicitly in the paper as a limitation.
- Note that the chaos-based scheme is designed to pass *classical* analysis,
  and that CNN resilience is future work.

---

## 3. Baseline Comparison

**Claim supported:** The chaos-based scheme (Arnold Cat Map + Logistic Map)
is harder to detect than simpler LSB variants.

You need to implement three baselines and run all four systems through every
metric in §1 and §2.

### Baseline A — Plain Sequential LSB

Embed bits sequentially left-to-right, top-to-bottom.  No position
randomisation.  This is the weakest known scheme and acts as the
"obviously detectable" reference point.

```python
def embed_sequential_lsb(cover: np.ndarray, bits: list) -> np.ndarray:
    stego = cover.copy()
    flat  = stego.ravel()
    for i, b in enumerate(bits):
        flat[i] = (flat[i] & 0xFFFE) | b
    return flat.reshape(stego.shape)
```

### Baseline B — PRNG-LSB (numpy random)

Replace the chaos position generator with `numpy.random.default_rng(seed).permutation(roi_pixels)`.  Uses a seeded PRNG but no crypto or chaos structure.  Detectable via RS only at high payload rates.

### Baseline C — Arnold Cat Map only (no Logistic Map perturbation)

Use `ChaosGenerator` but set `dx = dy = 0` (skip the logistic perturbation
step).  Isolates the contribution of the logistic map to detectability.  If
RS scores for this are similar to your full system, the logistic perturbation
adds no measurable value — that is also a valid finding.

### Result table structure

| Metric | Cover | Sequential LSB | PRNG-LSB | ACM-only | **This work** |
|---|---|---|---|---|---|
| PSNR (dB) | ∞ | ... | ... | ... | ... |
| SSIM | 1.0 | ... | ... | ... | ... |
| RS: Rm−Sm | 0 | ... | ... | ... | ... |
| χ² p-value | ... | ≈0 | ... | ... | ... |
| SPA est. payload | 0 | ... | ... | ... | ... |
| Embed time (s) | — | ... | ... | ... | ... |
| Extract time (s) | — | — | — | — | ... |

---

## 4. ZK-Specific Metrics

**Claim supported:** The Groth16 proof is sound, succinct, and efficiently
verifiable without the prover's secrets.

### 4.1 Proof correctness

| Test | Expected |
|---|---|
| Verify valid proof | PASS |
| Verify proof with wrong `publicImageHash` | FAIL |
| Verify proof with tampered `proof.json` (flip one bit) | FAIL |
| Verify proof from image B with verification key from image A | FAIL |
| Extract with wrong chaos_key | Hash mismatch at header, no metadata revealed |

These are binary pass/fail tests — confirm all 5 hold.

### 4.2 Proof size and key sizes

Already documented in `ZK_SYSTEM_METRICS.md`:

| Artifact | Size |
|---|---|
| `proof.json` | ~1.1 KB |
| `public.json` | ~830 B |
| `verification_key.json` | 4.5 KB |
| `chaos_zk_stego.zkey` (proving key) | 12.2 MB |

Verifier only needs `verification_key.json` (4.5 KB) — highlight this
succintness property.

### 4.3 Constraint count and trusted setup

Already measured: **18,429 constraints**, pot16 (28.1 % utilisation).

Report the constraint breakdown by template to demonstrate the cost of each
cryptographic component:

| Template | Estimated constraints | Purpose |
|---|---|---|
| `SecureMessageCommitment` (Poseidon) | ~250 | Message binding |
| `FullPositionVerification` (16× ACM) | ~16,000 | Position integrity |
| `PositionMerkleTree` (4-level, Poseidon) | ~1,500 | Position commitment |
| `AllPositionsRangeProof` (32× LessThan) | ~640 | Bounds checking |
| `ImageHashVerification` | ~8 | Image hash binding |
| `Nullifier` (Poseidon) | ~250 | Replay prevention |

(These are estimates; exact counts require snarkjs `--sym` analysis.)

### 4.4 Payload utilisation inside the stego image

| Region | Size | Location |
|---|---|---|
| Header | 84 bytes (fixed) | proof_key positions |
| ZK proof.json | ~1.1 KB | proof_key positions (tail) |
| public.json | ~830 B | proof_key positions (tail) |
| Compressed DICOM metadata | ~2.5 KB (gzip) | chaos_key positions |
| **Total payload** | **~4.5 KB** | LSBs of ~18,000 pixels |

---

## 5. Performance Benchmarks

**Claim supported:** The system is practically deployable on medical
workstations and embedded devices.

### 5.1 Timing breakdown

Measure each phase independently using `time.perf_counter()`:

| Phase | Measure |
|---|---|
| DICOM load & metadata extraction | seconds |
| ROI detection | seconds |
| gzip compression | seconds |
| Chaos position generation (proof_key region) | seconds |
| Chaos position generation (chaos_key region + entropy sort) | seconds |
| LSB embedding | seconds |
| PNG save | seconds |
| **ZK witness generation** | seconds |
| **ZK Groth16 proving** | seconds |
| **Total embedding (with proof)** | seconds |
| **Total embedding (no proof)** | seconds |
| Header + proof extraction | seconds |
| chaos_key validation | seconds |
| Metadata decompression | seconds |
| **ZK verification** | seconds |
| **Total extraction** | seconds |

> Report: mean ± std over 10 runs on your development machine.  State CPU
> model, RAM, OS.  If you have access to a Raspberry Pi 5, run there too —
> this is the intended deployment platform per the design docs.

### 5.2 Memory usage

Profile peak RSS during proof generation (the most expensive phase):

```python
import tracemalloc, time

tracemalloc.start()
# ... run embed with proof ...
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(f"Peak RAM: {peak / 1024**2:.1f} MB")
```

Also report peak memory during extraction only (no witness/proving key needed).

### 5.3 Throughput at different payload sizes

Sweep DICOM files of different metadata sizes (number of tags):

| Image | Tags | Metadata (raw) | gzip | Embed time |
|---|---|---|---|---|
| 1-01.dcm | 294 | ~8 KB | ~2.5 KB | ... |
| ... | ... | ... | ... | ... |

### 5.4 File size overhead

| Metric | Value |
|---|---|
| Source DICOM (.dcm) | X KB |
| Output stego PNG | Y KB |
| Size increase | Y − X KB |

Note: PNG is losslessly compressed — the stego PNG may actually be
slightly larger than an 8-bit PNG would be because the 2-LSB changes
reduce compressibility marginally.

---

## 6. Security Analysis

**Claim supported:** Without the chaos_key, metadata is cryptographically
inaccessible.  This section is a qualitative + quantitative analysis.

### 6.1 Key sensitivity (avalanche effect)

Change the chaos_key by one character.  Measure:
- Positions generated: completely different (no overlap expected)
- Number of overlapping positions out of N: should be ≈ N / (H × W) (random chance level)
- Header SHA-256 check: immediate mismatch → extraction aborted, zero metadata revealed

```python
key1 = "zkdicom_chaos_key_v1"
key2 = "zkdicom_chaos_key_v2"   # one character change
k1 = generate_chaos_key_from_secret(key1)
k2 = generate_chaos_key_from_secret(key2)
# compare k1 vs k2 in binary — Hamming distance analysis
```

### 6.2 Brute-force infeasibility

The chaos_key is a UTF-8 string.  At 20 characters, even a restricted
character set (95 printable ASCII) gives 95^20 ≈ 3.6 × 10^39 possibilities.
This is a qualitative argument, not a measurement — state it with the
key-length recommendation.

### 6.3 Two-key separation verification

Test that `proof_key` positions and `chaos_key` positions are disjoint:
- Embed with both keys
- Count overlap between the two position sets
- Expected: 0 overlap (enforced by the `exclude` parameter in `_roi_positions`)

> Report: overlap count = 0 confirmed across all 10 test images.

### 6.4 Wrong key rejection timing

Confirm that extraction aborts **before** any metadata is read when the
chaos_key is wrong — the SHA-256 check in the 84-byte header fires before
the chaos_key positions are even computed.  This means an attacker learns
nothing from a failed extraction attempt.

---

## 7. Dataset Requirements

To make results reproducible, specify the test dataset exactly:

- **Source:** [The Cancer Imaging Archive (TCIA)](https://www.cancerimagingarchive.net/) — publicly available DICOM datasets
- **Test set:** 10 MR brain scans (already in `examples/dicom/`)
- **For stronger claims:** also include CT chest + PET body scans (different
  modalities, different bit distributions)
- **Hardware for reporting:** specify CPU, RAM, OS for all timing results

All 10 test images should be run for every metric.  Report mean ± std, not
just a single representative result.

---

## 8. Reporting Checklist for the Paper

### Tables required

- [ ] T1: Quality metrics (PSNR, SSIM, MSE, BPP) × 10 images × 4 systems
- [ ] T2: Steganalysis results (RS, chi-square p-value, SPA est.) × 4 systems
- [ ] T3: ZK proof artifacts (constraint count, proof size, key sizes)
- [ ] T4: Performance timing breakdown with/without ZK proof
- [ ] T5: Security analysis (key sensitivity, position overlap = 0)

### Figures required

- [ ] F1: Histogram overlay (cover vs. stego) for one representative DICOM
- [ ] F2: LSB bit-plane visualisation (cover vs. stego, bits 0 and 1)
- [ ] F3: PSNR vs. payload rate curve (sweep from 10 % to 100 % capacity) × 4 systems
- [ ] F4: RS Rm−Sm vs. payload rate × 4 systems (the most important detectability figure)
- [ ] F5: Timing breakdown stacked bar (embed phases, proof phases)
- [ ] F6: System architecture / two-key flow diagram

---

## 9. What Is Optional vs. Required

| Benchmark | Required for paper | Effort | Notes |
|---|---|---|---|
| PSNR / SSIM / MSE | Yes | Low | Standard; skimage |
| Histogram comparison | Yes | Low | One figure |
| RS analysis | **Yes** | Medium | Implement from Fridrich 2001 |
| Chi-square attack | Yes | Low | ~20 lines of code |
| SPA | Recommended | Medium | Use Aletheia or implement |
| Baseline comparison (A, B, C) | **Yes** | Medium | Core paper contribution |
| PSNR vs. payload rate curve | Yes | Low | Sweep loop |
| RS vs. payload rate curve | **Yes** | Low given RS impl | Most important figure |
| CNN steganalysis | Optional / future work | High | Acknowledge as limitation |
| ZK correctness tests | Yes | Low | Already passes |
| ZK proof size / constraint count | Yes | Done | See ZK_SYSTEM_METRICS.md |
| Timing breakdown | Yes | Low | time.perf_counter |
| Memory profiling | Recommended | Low | tracemalloc |
| Raspberry Pi 5 timing | Recommended | Medium | Matches deployment claim |
| Security analysis (key sensitivity) | Yes | Low | Few lines of code |
| Two-key separation proof | Yes | Low | Assert overlap = 0 |

---

## 10. Implementation Order (Suggested)

1. **Implement RS analysis** — this is the most important and takes the most time
2. **Implement baselines A and B** — sequential LSB and PRNG-LSB
3. **Run T1 + T2 for all 4 systems** — core results table
4. **Generate F3 + F4** (PSNR vs. payload, RS vs. payload) — key figures
5. **Timing benchmark** — single loop, easy
6. **Security tests** — key sensitivity, overlap check
7. Baseline C (ACM-only), SPA, memory profiling — as time permits
