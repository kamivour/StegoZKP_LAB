# DICOM ZK-Stego — Overview

## What This Extension Does

The DICOM extension hides all patient metadata from a DICOM medical image
inside the image's own pixel data using LSB steganography, then generates a
Groth16 ZK-SNARK proof of data integrity — without any modification to the
underlying diagnostic pixel values beyond the 2 least significant bits.

**In one sentence:**  
A sender embeds all DICOM metadata (patient, study, acquisition tags) into a
16-bit PNG carrier derived from the original DICOM pixel array; a ZK proof
attests to the integrity of that payload; the receiver extracts and verifies
everything using a `chaos_key` that was pre-shared once during setup — so
subsequent transfers require only the stego image.

---

## Why Not Normalise to 8-bit?

The original PNG steganography module normalised pixels to 8-bit. That is
wrong for medical imaging:

| Bit-depth | Intensity levels | Consequence of 8-bit downscale |
|---|---|---|
| DICOM (CT, MR) | 16-bit → 65 536 levels | Soft-tissue contrast, HU values, T1/T2 ratios are destroyed |
| 8-bit PNG (old) | 256 levels | Diagnostically unsafe if PNG were used clinically |
| **16-bit PNG (current)** | **65 536 levels** | **Full fidelity — identical to source** |

All DICOM modalities (CT, MR, CR, DR, PET) natively store 16-bit pixels, so
no normalisation is ever needed. The current implementation reads native pixels
and preserves them exactly.

---

## What Is Embedded

Everything that is not binary pixel data:

- All text and numeric DICOM tags — **294 tags** in the test dataset
- Excluded: `PixelData` (the image itself), VRs `OB / OW / OF / SQ / UN`
  (binary blobs or nested sequences that cannot be represented as plain text)
- Typical raw JSON size: **~8 KB**; after gzip compression: **~2.5 KB**

---

## Two-Key Design

Two independent keys control two independent regions of the image.

```
proof_key  (public, fixed default: "zkdicom_proof_key_v1")
    └─ Determines where the ZK proof header is hidden.
    └─ Anyone who knows this key can verify the ZK proof.
    └─ Cannot be used to read the patient metadata.

chaos_key  (private, pre-shared once during verifier setup)
    └─ Determines where the compressed metadata is hidden.
    └─ Only the holder of this key can extract patient data.
    └─ Never stored in the image — only its SHA-256 hash is.
    └─ Ships inside `verifier_package/chaos_key.txt`. After the one-time
       package delivery, the prover sends only the stego image — no key
       needs to travel with subsequent images.
```

This separation means:
- A **public auditor** (e.g., a PACS audit system) can confirm the image
  carries a valid integrity proof without ever learning patient information.
- A **registered verifier** receives the `chaos_key` once (together with
  `verifier_package/`) and forever after receives only the stego PNG — no
  key needs to travel with each image.

---

## Pixel Distortion

Each pixel carries **2 bits** (bits 1 and 0). The maximum change per pixel is ±3
out of 65535 — an error of **0.005%**. This is below the noise floor of any
DICOM modality and invisible on any display.

| Metric | Value |
|---|---|
| Embedding capacity | 2 bits / pixel |
| Max distortion | ±3 / 65535 = 0.005% |
| ROI pixels used (512×512 MR) | 10,460 of 185,568 (5.6%) |
| Total pixel budget used | < 6% |

---

## File Map

```
ImageLevel/
├── chaos_key.txt               ← Pre-shared private key (prover side, auto-loaded)
├── src/zk_stego/
│   └── dicom_handler.py        ← All DICOM stego logic (DicomHandler, DicomStego)
├── scripts/
│   ├── dicom_embed.py          ← CLI: embed DICOM metadata into stego PNG
│   └── dicom_extract.py        ← CLI: extract metadata + verify ZK proof
├── examples/
│   └── dicom/                  ← Sample .dcm files + generated stego PNGs
└── verifier_package/
    ├── chaos_key.txt           ← Same pre-shared key (shipped to verifier once)
    └── scripts/
        └── dicom_extract.py    ← (run from verifier_package/ root; reads chaos_key.txt)
```

---

## Relationship to the Original PNG System

The DICOM extension is completely independent of the original `embed.py /
verify.py` pipeline. It reuses only:

- `utils.py` — `ChaosGenerator` (Arnold Cat Map + Logistic Map) and
  `generate_chaos_key_from_secret()`
- `prover.py` — `Prover._generate_zk_proof()` for the optional ZK proof step

The ZK circuit (`chaos_zk_stego.circom`), proving key, and snarkjs toolchain
are shared between both systems.
