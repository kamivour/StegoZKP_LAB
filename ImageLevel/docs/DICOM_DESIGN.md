# DICOM ZK-Stego — Design Decisions

This document records every design decision made for the DICOM extension,
including alternatives that were considered and rejected.

---

## 1. Pixel Data — Native 16-bit vs 8-bit Normalisation

**Decision: preserve native 16-bit pixels. No normalisation.**

DICOM files store pixels at the bit-depth acquired by the scanner —
always 16-bit for CT, MR, CR, DR, PET. Normalising to 8-bit discards
99.6% of intensity resolution and is diagnostically unsafe.

The `to_uint16()` method handles the only real conversion needed:
`int16` DICOM pixels (signed, range –32768 to +32767) are shifted by
+32768 to map cleanly into `uint16` `[0, 65535]`. This is a lossless,
invertible linear transform. The shift is recoverable via the DICOM tags
`RescaleIntercept` and `PixelRepresentation`, which are already embedded
in the metadata payload.

**Output format:** 16-bit grayscale PNG (PIL `mode="I;16"`). PNG is
lossless, so embedded bits survive the save/load cycle exactly.

---

## 2. Embedding Depth — 2 LSBs vs 1 LSB

**Decision: embed 2 bits per pixel (bits 1 and 0).**

With 16-bit pixels the 2-LSB approach is correct:

| Approach | Max pixel error | % of full range |
|---|---|---|
| 1 LSB | ±1 / 65535 | 0.0015% |
| **2 LSBs** | **±3 / 65535** | **0.005%** |
| 1 LSB (old 8-bit) | ±1 / 255 | 0.39% |

The 2-LSB approach still has **80× less distortion** than the old 8-bit
system, while doubling the embedding rate. The 0.005% error is well below
the noise floor of any DICOM modality.

**Embed layout per pixel:**
```
pixel & 0xFFFC           clear bits 1 and 0
| (b0 << 1)              write first data bit into bit 1
|  b1                    write second data bit into bit 0
```

---

## 3. Where Metadata Goes — PNG Chunk vs Pure Pixel LSB

**Decision: pure pixel LSB steganography. No PNG custom chunk.**

The original system used a custom `zkPF` PNG chunk to carry the ZK proof
and chaos metadata. For DICOM this was removed entirely for two reasons:

1. **Steganographic security** — a PNG chunk is trivially visible to any
   hex editor or `pngcheck`. Pure pixel embedding leaves no detectable
   structural trace.
2. **Consistency** — if both the proof and the metadata live entirely in
   pixel LSBs, the image is self-contained and the stego property holds
   end-to-end.

Everything — 84-byte header, ZK proof JSON, public inputs JSON, and all
compressed metadata — is embedded in pixel bits across two key-derived
regions.

---

## 4. Two-Key System — Why Two Keys

**Decision: Option B — separate `proof_key` (public) and `chaos_key`
(private).**

Two alternative single-key designs were considered:

- **Option A — one key for everything**: The key holder can verify the
  proof AND extract metadata. No separation of roles. Rejected because a
  hospital auditor should be able to verify proof integrity without
  accessing patient data.

- **Option B (chosen) — two keys**: `proof_key` is a fixed public
  constant. `chaos_key` is private, **pre-shared once** when the verifier
  receives `verifier_package/`. After that single exchange, the prover
  sends only the stego PNG — no key travels with subsequent images.

  | Role | When they receive the key | Can do |
  |---|---|---|
  | Public auditor | Never (uses fixed `proof_key`) | Verify ZK proof only |
  | Registered verifier | **Once** (receives `verifier_package/`) | Extract metadata + verify proof |

The key value (`zkdicom_chaos_key_v1` by default) lives in two plain-text
files:
- `ImageLevel/chaos_key.txt` — prover side (auto-loaded by `dicom_embed.py`)
- `verifier_package/chaos_key.txt` — verifier side (shipped once, auto-loaded
  by `dicom_extract.py`)

Neither CLI has any hardcoded key fallback — if `chaos_key.txt` is absent
and no `--key` / `--key-file` flag is given, the script exits with a clear
error explaining the options.

The `chaos_key` is never stored in the image. Only its SHA-256 hash
(32 bytes) is embedded in the header, so a wrong key is rejected
immediately without revealing any metadata.

---

## 5. ZK Coverage — What the Circuit Attests To

**Problem:** The existing `chaos_zk_stego.circom` circuit accepts exactly
32 bits as the message input. Full DICOM metadata is ~20,000+ bits.
Expanding the circuit to cover all bits would require a `pot16+` trusted
setup and exceed the hardware budget of a Raspberry Pi 5 (target deployment
platform, proof time ~5–15 s on pot12).

**Decision: SHA-256 fingerprint approach.**

The ZK circuit attests to a **32-bit fingerprint** of the compressed
metadata rather than the metadata itself:

```
fingerprint = SHA-256(gzip(metadata_json))[:4].decode("latin-1")
```

This gives the following guarantee:
- The ZK proof proves the prover knew the correct key and generated
  positions correctly at the time of embedding.
- The SHA-256 of the compressed metadata (stored in the 84-byte header)
  provides bit-exact integrity of the full payload on extraction.
- Together: proof = positions were generated correctly, hash = payload
  was not tampered with.

The pot12 trusted setup (~5,000 constraints) and 5–15 s proof time on
Pi 5 are preserved.

---

## 6. ROI Detection — Fixed Threshold vs Percentile

**Decision: percentile-based ROI (bottom 5% excluded as background).**

The original 8-bit code used a fixed threshold of `20` to exclude black
background pixels. This is fragile:
- CT images span Hounsfield values –1024 to +3071 → after uint16 shift,
  the background intensity is ~32–35000 depending on the scanner.
- A fixed integer threshold is meaningless across modalities.

The percentile approach cuts the bottom 5% of `(pixel & 0xFFFC)` intensity
values. This adaptively excludes background regardless of modality or
scanner calibration. The `& 0xFFFC` mask strips the 2 embedding bits so
the ROI mask is **identical on embed and extract** even after embedding.

Result for 1-01.dcm (512×512 MR):
- 8-bit fixed threshold: 25,404 ROI pixels (9.7%)
- **16-bit 5th-percentile: 185,568 ROI pixels (70.8%)**

---

## 7. Position Selection — Chaos Trajectory Mapping

**Problem:** With only 9.7% ROI density (old 8-bit), the chaos trajectory
(generated across the full image) produces very few ROI hits. The initial
implementation tried to oversample by 15× and filter, but still produced
too few positions.

**Decision: enumerate ROI first, then map chaos indices into ROI space.**

Algorithm:
1. Enumerate all ROI pixels into a list `all_roi`.
2. For the `chaos_key` region, optionally sort `all_roi` by ascending
   local variance (entropy sort — embed in the flattest areas first).
3. Run the chaos trajectory to generate N positions across the full image.
4. For each chaos position `(cx, cy)`, compute `flat = cy * width + cx`.
   Map to ROI index via `roi_idx = flat % len(all_roi)`.
5. Deduplicate (skip already-used indices).
6. Sequential fallback for any remaining slots.

This guarantees 100% ROI coverage while preserving the chaotic scatter
property required by the paper (Arnold Cat Map + Logistic Map).

---

## 8. Entropy Sort — Variance Map Stability

**Problem:** After embedding, pixel values change by ±3. If the variance
map is recomputed on the stego image, the sort order may differ from the
order used during embedding → wrong positions → extraction failure.

**Decision:** compute local variance on `pixel & 0xFFFC` (LSBs cleared).

Since both the original and stego images agree on all bits above bit 1,
stripping bits 1 and 0 before computing variance makes the map identical
on both sides. This was the root cause of the first extraction failure
and was fixed before the passing test.

---

## 9. Header Format

The 84-byte header (fixed size, packed with `struct`) contains everything
the extractor needs to locate and validate both regions:

```
Offset  Size  Field
0       4     MAGIC b"ZKDC"
4       4     version b"\x01\x00\x00\x00"
8       32    SHA-256(chaos_key string)   ← key fingerprint for fast rejection
40      32    SHA-256(gzip metadata)      ← payload integrity hash
72      4     metadata_bit_count (uint32)
76      4     proof_json_len (uint32)
80      4     public_json_len (uint32)
84+     var   ZK proof JSON bytes
84+pjl  var   public inputs JSON bytes
```

The header is embedded in the `proof_key` region (public). Anyone with
`proof_key` can read the header and verify the proof. The `chaos_key` hash
at offset 8 allows quick rejection of a wrong key before any metadata
extraction is attempted.
