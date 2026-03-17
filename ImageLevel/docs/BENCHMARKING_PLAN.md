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

### 4.5 ZKP Scheme Comparison: Why Groth16?

**Claim supported:** Groth16 is the correct ZKP scheme for this specific
application; the choice is not arbitrary.

This section pre-answers the examiner question "why Groth16 and not Schnorr /
Bulletproofs / PLONK / STARKs?"

#### 4.5.1 The critical constraint that drives the choice

The proof must be **physically embedded inside the stego image as part of
the payload**.  `proof.json` (≈1.1 KB) + `public.json` (≈830 B) together
occupy ≈1,930 bytes of the carrier's LSB capacity.  At 2 LSBs per pixel on
a 512×512 image, the entire stego header + proof region uses ≈7,720 pixel
LSBs out of 262,144 available — roughly **3 %** of capacity.

Any ZKP scheme whose proof size exceeds ~10 KB would double or quadruple
this figure, and schemes above ~50 KB would make embedding impractical on
typical DICOM image sizes.  **Proof size is the primary selection criterion.**

#### 4.5.2 Expressiveness gating: what can the scheme even prove?

Before comparing efficiency, first check whether the scheme can express the
statement at all.  The statement this circuit proves is:

> "I know a secret key K such that, when Arnold Cat Map (16 iterations) is
> applied with K to image dimensions H×W, the resulting 32 embedding
> positions fall within the ROI, do not overlap, and are bound to a specific
> image hash via a Poseidon commitment — without revealing K."

This is a **general arithmetic circuit** with ~18,429 constraints over a
prime field.  Only schemes that support arbitrary-circuit ZK can express it.

| Scheme | Arbitrary circuit? | Can express this statement? |
|---|---|---|
| Schnorr ZK | ✗ — proves discrete log only | ✗ No |
| Σ-protocols (Pedersen, etc.) | ✗ — proves linear relations only | ✗ No |
| Bulletproofs | ✓ — arithmetic circuits via inner-product | ✓ Yes |
| Groth16 (this work) | ✓ — R1CS circuits | ✓ Yes |
| PLONK | ✓ — PLONK-arithmetic circuits | ✓ Yes |
| Marlin | ✓ — R1CS circuits | ✓ Yes |
| zk-STARKs | ✓ — algebraic intermediate representation | ✓ Yes |

**Schnorr ZK cannot be used here at all.** It proves "I know the discrete
log of a public point" — a single-equation statement.  There is no way to
encode "I correctly iterated Arnold Cat Map 16 times" as a discrete log
relation.  This is not a performance trade-off; it is a categorical
mismatch of expressive power.

#### 4.5.3 Efficiency comparison across viable schemes

For schemes that *can* express the statement (arithmetic-circuit ZK):

| Property | Bulletproofs | **Groth16 (this work)** | PLONK | zk-STARKs |
|---|---|---|---|---|
| Proof size | O(log n) ≈ 10–20 KB | **~200 bytes raw / ~1.1 KB JSON** | ~400 bytes raw / ~1.5 KB JSON | 50–200 KB |
| Proving time | O(n log n) — slow | **O(n log n) — fast (FFT)** | O(n log n) | O(n log² n) — slowest |
| Verification time | O(n) — linear, slow | **O(1) — 3 pairings, ~1–3 ms** | O(1) — ~2–5 ms | O(log² n) — ~5–50 ms |
| Trusted setup | ✗ None | Circuit-specific (done once) | Universal (updatable) | ✗ None |
| Post-quantum secure | ✗ | ✗ (BN254 pairings) | ✗ | ✓ (hash-based) |
| Tooling maturity | Moderate | **Best (circom + snarkjs)** | Good (circom + snarkjs) | Moderate |
| Cryptographic assumption | DLOG (elliptic curve) | Pairing + KoE | Pairing + KoE | Collision-resistant hash |

#### 4.5.4 Elimination rationale

**Schnorr / Σ-protocols:** Eliminated at the expressiveness gate.  Cannot
encode an arbitrary constraint system.  Not a viable option regardless of
performance.

**Bulletproofs:** Proof size scales as O(log n) — for 18,429 constraints
this yields ≈ 10–15 KB per proof.  That is 10–15× larger than Groth16 and
would consume ≈ 60,000–120,000 pixel LSBs for the proof alone (≈ 23–46 %
of capacity on a 512×512 image), potentially exhausting the carrier.
Verification is O(n), making it slow for the verifier.  **Eliminated: proof
too large to embed, verification too slow.**

**zk-STARKs:** No trusted setup (good), post-quantum (good), but proof size
is 50–200 KB.  Embedding 50 KB requires ≈ 200,000 pixel LSBs — almost the
entire ROI of a 512×512 image.  Impractical at this image size.  Would
become viable for larger carriers (e.g., 4K radiological images).
**Eliminated: proof too large to embed in typical DICOM images.**

**PLONK:** Very similar proof size to Groth16 (~400 bytes raw).  Key
advantage: *universal trusted setup* (one setup for all circuits, updatable
by anyone).  Key disadvantage for this system: circom/snarkjs support for
PLONK is less mature than Groth16, and the proving time is marginally higher.
The trusted setup is done **once** for a fixed circuit (the steganography
algorithm does not change), so the "circuit-specific setup" downside of
Groth16 is not a practical concern.  **PLONK is the closest competitor and a
valid future upgrade path; Groth16 is preferred now because of tooling
maturity and proof size.**

**Groth16:** Smallest raw proof size of any arithmetic-circuit SNARK
(3 group elements; 192 bytes compressed).  Constant-time verification
(3 pairing operations, hardware-acceleratable).  Most mature tooling.
Circuit is compiled once; trusted setup done once.  **Selected.**

#### 4.5.5 Benchmark table to include in the paper

This is a *literature / specification* table — you do not implement the
other schemes, you cite their published figures.  Fill the measured Groth16
values from §4 and §5 of this plan; use cited values for the others.

| Scheme | Proof size | Verify time | Trusted setup | Embeddable in DICOM? | Reference |
|---|---|---|---|---|---|
| Schnorr ZK | 64 bytes | < 1 ms | ✗ | N/A — wrong tool | [Schnorr 1991] |
| Bulletproofs | ~10–15 KB† | ~100 ms† | ✗ | ✗ (too large) | [Bünz et al. 2018] |
| PLONK | ~400 bytes | ~2–5 ms | Universal | ✓ (marginal) | [Gabizon et al. 2019] |
| zk-STARK | ~50–200 KB | ~5–50 ms | ✗ | ✗ (too large) | [Ben-Sasson et al. 2018] |
| **Groth16 (this work)** | **~200 bytes raw / 1.1 KB JSON** | **~1–3 ms (measured)** | Circuit-specific | **✓ (3 % of capacity)** | [Groth 2016] |

† For 18,429-constraint circuit; scales as O(log n).

> Note the "N/A — wrong tool" row for Schnorr.  This is important to state
> explicitly: including Schnorr in this table shows the examiner you
> understand the expressiveness distinction, not just the performance numbers.

#### 4.5.6 References to cite

- Groth, J. (2016). *On the size of pairing-based non-interactive arguments.*
  EUROCRYPT 2016.  (The Groth16 paper.)
- Bünz, B., Bootle, J., Boneh, D., Poelstra, A., Wuille, P., & Maxwell, G.
  (2018). *Bulletproofs: Short proofs for confidential transactions and more.*
  IEEE S&P 2018.
- Gabizon, A., Williamson, Z. J., & Ciobanu, O. (2019). *PLONK: Permutations
  over Lagrange-bases for oecumenical noninteractive arguments of knowledge.*
  ePrint 2019/953.
- Ben-Sasson, E., Bentov, I., Horesh, Y., & Riabzev, M. (2018). *Scalable,
  transparent, and post-quantum secure computational integrity.*
  ePrint 2018/046.
- Schnorr, C. P. (1991). *Efficient signature generation by smart cards.*
  Journal of Cryptology, 4(3), 161–174.

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

Note: PNG is losslessly compressed — the stego PNG may be marginally larger
than a plain cover PNG because the 2-LSB changes reduce compressibility very
slightly.  Measure the actual delta for all 10 test images.

---

## 6. System-Level Comparison: Digital Signature vs Stego-Only vs This Work

**Claim supported:** The ZK-steganography system occupies a unique position
in the design space that neither DICOM digital signatures nor plain
steganography can fill alone.

Your second mentor's feedback is correct: reviewers familiar with clinical
DICOM workflows will immediately ask "why not just use DICOM Digital
Signatures (PS3.15)?".  This section pre-answers that question with data.

### 6.1 Threat-model framing

The three systems are **not competitors** — they address different threat
models:

| Threat | Digital Signature | Stego only | Stego + ZK (this work) |
|---|---|---|---|
| "Was this image tampered with?" | ✓ (RSA/ECDSA) | Partial (hash, key-bound) | ✓ (ZK proof + hash) |
| "Who signed this image?" (non-repudiation) | ✓ (PKI-bound identity) | ✗ | Partial (key holder) |
| "Who can see the embedded metadata?" | Anyone (tag is visible) | Key holder only | Key holder only |
| "Can I verify without the prover's key?" | ✓ (public key) | ✗ | ✓ (verification_key.json) |
| "Can I hide that metadata was embedded?" | ✗ (tag FFFA,FFFA visible) | ✓ | ✓ |
| Requires PKI infrastructure | ✓ mandatory | ✗ | ✗ |
| Zero-knowledge property | ✗ | ✗ | ✓ |

**Paper framing (one sentence):** "DICOM Digital Signatures prove *who*
signed an image; this system proves *what* was embedded and *that* it was
embedded correctly, while keeping the payload covert and eliminating PKI
dependency."

### 6.2 Property comparison table (T6)

This becomes **Table T6** in the paper — a 3-column capability matrix.

| Property | DICOM Digital Sig (PS3.15) | Stego only (`--no-proof`) | **This work (Stego + ZK)** |
|---|---|---|---|
| Metadata hidden from DICOM viewers | ✗ | ✓ | ✓ |
| Integrity guarantee type | RSA/ECDSA chain | SHA-256 (key-bound) | Groth16 ZK proof + SHA-256 |
| Publicly verifiable (no prover secret) | ✓ | ✗ | ✓ |
| Proof of *embedding correctness* | ✗ | ✗ | ✓ |
| Covert channel (undetectable carrier) | ✗ | ✓ | ✓ |
| PKI required | ✓ | ✗ | ✗ |
| Detectable by DICOM tag inspection | ✓ (trivially) | ✗ | ✗ |
| Detectable by RS/chi-square analysis | N/A | Low (chaos scheme) | Low (same embedding) |
| Signature/proof size | 71–256 bytes | 0 bytes | ~2 KB (proof.json + public.json) |
| Verification key size | Public key (~64–294 bytes) | Shared chaos_key | 4.5 KB (verification_key.json) |
| Depends on image carrier | ✗ | ✓ | ✓ |
| Post-quantum resistant | ✗ (RSA/ECDSA broken by Shor) | ✓ (hash + chaos) | Partial (Groth16 pairing-based) |

### 6.3 Benchmark C — Stego only (`--no-proof` mode)

Already supported: pass `--no-proof` to `dicom_embed.py`.  No new code needed.

**What to measure and report:**

| Metric | Measure |
|---|---|
| Total embed time (no proof) | `time.perf_counter()` — expected: < 1 s |
| Total extract time | Same as full system (ZK only on embed side) |
| PSNR, SSIM | **Identical** to Stego+ZK (same embedding algorithm) |
| RS/chi-square | **Identical** to Stego+ZK |
| Proof artifact size | 0 bytes (no proof.json, no public.json) |

> Key insight to highlight: the *embedding quality and steganalysis resistance*
> are identical between Stego-only and Stego+ZK — the ZK proof adds overhead
> only at proof generation time, not in the carrier image.

```python
# Benchmark C runner
import subprocess, time

t0 = time.perf_counter()
subprocess.run([
    "python", "scripts/dicom_embed.py",
    "--input",  "examples/dicom/1-01.dcm",
    "--output", "examples/output/1-01_noproof.png",
    "--no-proof",
], check=True)
stego_only_time = time.perf_counter() - t0
print(f"Stego-only embed time: {stego_only_time:.3f} s")
```

### 6.4 Benchmark D — DICOM Digital Signature (ECDSA-P256)

Implement a minimal signing benchmark using the `cryptography` package
(already in the Python ecosystem; `pip install cryptography`).

This does *not* implement the full DICOM PS3.15 sequence (which requires a
DICOM toolkit and CA certificates) — it benchmarks the underlying
cryptographic primitive on the same metadata payload, which is the honest
apples-to-apples comparison.

```python
import json, time
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

# Key generation (done once, not per-image)
private_key = ec.generate_private_key(ec.SECP256R1())
public_key  = private_key.public_key()

# Simulate signing the same DICOM metadata JSON that this system embeds
with open("examples/dicom/1-01_metadata.json", "rb") as f:
    payload = f.read()

# --- Sign ---
t0 = time.perf_counter()
signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
sign_time = time.perf_counter() - t0

# --- Verify ---
t0 = time.perf_counter()
public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
verify_time = time.perf_counter() - t0

print(f"ECDSA-P256 sign time  : {sign_time  * 1000:.3f} ms")
print(f"ECDSA-P256 verify time: {verify_time * 1000:.3f} ms")
print(f"Signature size (DER)  : {len(signature)} bytes")
```

**Expected results:**

| Operation | Expected |
|---|---|
| ECDSA-P256 sign | < 1 ms |
| ECDSA-P256 verify | < 2 ms |
| Signature size | 71–72 bytes (DER) |
| Public key size | 64 bytes (uncompressed) |

Compared to Groth16: ZK proving takes seconds; ECDSA takes milliseconds.
This is a known trade-off — report it honestly.  The ZK cost buys the
zero-knowledge property (verifier learns nothing about the chaos_key or
payload positions).

### 6.5 Updated performance comparison (T4 extended)

Add columns to the performance table (T4) to cover all three modes:

| Operation | ECDSA Digital Sig | Stego only | **Stego + ZK** |
|---|---|---|---|
| "Signing" / embed time | < 1 ms | ~0.3 s | ~30–120 s (ZK proving) |
| "Verification" / verify time | < 2 ms | ~0.1 s | ~1–3 s |
| Proof/sig size | 71 bytes | 0 bytes | ~2 KB |
| Verification key size | 64 bytes | — | 4.5 KB |
| Carrier image modified | ✗ | ✓ | ✓ |

> Report: fill in measured values from Benchmarks C and D.  Be explicit that
> the ZK proving overhead is a one-time cost per embed (not per verification),
> and that verification is fast enough for clinical use.

---

## 7. Security Analysis

**Claim supported:** Without the chaos_key, metadata is cryptographically
inaccessible.  This section is a qualitative + quantitative analysis.

### 7.1 Key sensitivity (avalanche effect)

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

### 7.2 Brute-force infeasibility

The chaos_key is a UTF-8 string.  At 20 characters, even a restricted
character set (95 printable ASCII) gives 95^20 ≈ 3.6 × 10^39 possibilities.
This is a qualitative argument, not a measurement — state it as a security
claim with the recommended minimum key length.

### 7.3 Two-key separation verification

Test that `proof_key` positions and `chaos_key` positions are disjoint:
- Embed with both keys
- Count overlap between the two position sets
- Expected: 0 overlap (enforced by the `exclude` parameter in `_roi_positions`)

> Report: overlap count = 0 confirmed across all 10 test images.

### 7.4 Wrong key rejection timing

Confirm that extraction aborts **before** any metadata is read when the
chaos_key is wrong — the SHA-256 check in the 84-byte header fires before
the chaos_key positions are even computed.  This means an attacker learns
nothing from a failed extraction attempt.

---

## 8. Dataset Requirements

To make results reproducible, specify the test dataset exactly:

- **Source:** [The Cancer Imaging Archive (TCIA)](https://www.cancerimagingarchive.net/) — publicly available DICOM datasets
- **Test set:** 10 MR brain scans (already in `examples/dicom/`)
- **For stronger claims:** also include CT chest + PET body scans (different
  modalities, different bit distributions)
- **Hardware for reporting:** specify CPU, RAM, OS for all timing results

All 10 test images should be run for every metric.  Report mean ± std, not
just a single representative result.

---

## 9. Reporting Checklist for the Paper

### Tables

| ID | Title | Section | Status |
|---|---|---|---|
| T1 | Image quality metrics (PSNR, SSIM, MSE, BPP) averaged over 10 images | §1 | [ ] |
| T2 | Steganalysis results (RS Rm−Sm, χ² p-value, SPA) for all 4 embedding schemes | §2–§3 | [ ] |
| T3 | ZK proof correctness (5 pass/fail tests) | §4 | [ ] |
| T4 | Performance timing breakdown (per-phase, mean ± std, with and without proof) | §5 | [ ] |
| T5 | ZK artifact sizes (proof.json, public.json, verification_key.json, proving_key) | §4 | [ ] |
| T6 | System capability comparison (Digital Sig vs Stego only vs Stego+ZK) | §6 | [ ] |

### Figures

| ID | Title | Section |
|---|---|---|
| F1 | Overlay histogram: cover vs stego pixel values | §1.2 |
| F2 | LSB plane visualisation (4-panel: cover bit-0, cover bit-1, stego bit-0, stego bit-1) | §1.3 |
| F3 | RS analysis bar chart: Rm, Sm, Rm_, Sm_ for cover, sequential, PRNG, this work | §2.1 |
| F4 | PSNR/SSIM per image (bar chart, 10 images) | §1 |
| F5 | Timing breakdown pie/bar chart (phases of embed+proof pipeline) | §5.1 |
| F6 | Capability radar chart (6 properties × 3 systems: Sig, Stego, Stego+ZK) | §6 |

---

## 10. Required vs Optional Matrix

| Benchmark | Effort | Required for paper | Nice to have |
|---|---|---|---|
| PSNR, SSIM, MSE | Low (1 h) | ✓ Required | — |
| Pixel histogram | Low (30 min) | ✓ Required | — |
| LSB plane viz | Low (30 min) | ✓ Required | — |
| RS analysis | Medium (2 h) | ✓ Required | — |
| Chi-square test | Low (1 h) | ✓ Required | — |
| SPA | Medium (2 h) | ✓ Required | — |
| Aletheia CNN | High (4–8 h) | Optional | ✓ |
| Sequential LSB baseline | Low (1 h) | ✓ Required | — |
| PRNG-LSB baseline | Low (1 h) | ✓ Required | — |
| ACM-only baseline | Low (1 h) | ✓ Required | — |
| ZK correctness tests | Low (1 h) | ✓ Required | — |
| Proof sizes | Done | ✓ Required | — |
| Constraint breakdown | Low (30 min) | ✓ Required | — |
| Timing breakdown | Medium (2 h) | ✓ Required | — |
| Memory profiling | Low (1 h) | Recommended | ✓ |
| File size overhead | Low (30 min) | ✓ Required | — |
| **Stego-only benchmark** | **Low (30 min)** | **✓ Required** | — |
| **ECDSA digital sig benchmark** | **Low (1 h)** | **✓ Required** | — |
| Key sensitivity | Low (1 h) | Recommended | ✓ |
| Two-key separation | Low (30 min) | Recommended | ✓ |

---

## 11. Suggested Implementation Order

Work bottom-up: establish the cover image baseline first, then add embedding,
then add ZK, then add comparisons.

1. **§1 quality metrics** — Run PSNR/SSIM/MSE on existing test image.  You
   already have a stego PNG; this takes ~1 hour.
2. **§5.1 timing (no ZK phases)** — Add `perf_counter` calls around the
   non-ZK phases of `embed()`.
3. **§2 steganalysis** — Implement RS and chi-square; run on cover then stego.
4. **§3 baselines** — Write sequential LSB and PRNG-LSB; run all metrics.
5. **§4 ZK correctness** — 5 pass/fail tests; run the existing test suite.
6. **§5.1 timing (full pipeline)** — Add timing around witness + proving.
7. **§6 Benchmark C (stego-only)** — Run `--no-proof`; record timing delta.
8. **§6 Benchmark D (ECDSA)** — Write the 20-line signing benchmark script.
9. **§7 two-key separation + key sensitivity** — 1-hour addition.
10. **Figures** — Generate all 6 figures from collected data.
11. **Tables** — Consolidate into T1–T6 for paper draft.

---

*Last updated: system comparison (§6) added per mentor feedback — DICOM
Digital Signatures (PS3.15) added as baseline alongside stego-only mode.*
