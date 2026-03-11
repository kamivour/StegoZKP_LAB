# DICOM ZK-Stego — How to Run

## Prerequisites

Same as the main system (Node.js, snarkjs, npm install), plus two extra
Python packages:

```powershell
pip install pydicom>=2.3.0 scipy>=1.9.0
```

These are already listed in `requirements.txt`.

---

## Embedding — Sender Side

Run from `ImageLevel/`. The key is read from `chaos_key.txt` automatically — no `--key` flag needed after one-time setup:

```powershell
# Recommended: key read from chaos_key.txt in current directory
python scripts/dicom_embed.py scan.dcm stego.png

# Skip ZK proof (faster — no Node.js needed)
python scripts/dicom_embed.py scan.dcm stego.png --no-proof

# Verbose / JSON output
python scripts/dicom_embed.py scan.dcm stego.png -v
python scripts/dicom_embed.py scan.dcm stego.png --json

# Override key explicitly (first-time testing or scripting)
python scripts/dicom_embed.py scan.dcm stego.png --key-file /path/chaos_key.txt
python scripts/dicom_embed.py scan.dcm stego.png --key "patient_secret"
```

### Parameters

| Argument | Description |
|---|---|
| `dcm` | Path to the source `.dcm` file |
| `output` | Output path for the stego PNG (must be `.png`) |
| `--key / -k` | Inline chaos key string (overrides file lookup) |
| `--key-file / -K` | Path to key file (default: `chaos_key.txt` in cwd) |
| `--proof-key` | Public proof key (default: `"zkdicom_proof_key_v1"`) |
| `--no-proof` | Skip ZK proof generation |
| `--background-percentile` | Bottom N% of pixel intensity treated as background (default: `5.0`) |
| `--verbose / -v` | Verbose output |
| `--json / -j` | JSON output |

### What the output PNG contains

- **Pixel data**: original 16-bit DICOM pixels — only bits 1 and 0 of some
  pixels are modified (±3 max distortion out of 65535)
- **`proof_key` region** (publicly readable): 84-byte header + ZK proof JSON
  + public inputs JSON — all in pixel LSBs
- **`chaos_key` region** (private): gzip-compressed JSON of all 294+ DICOM
  tags — in pixel LSBs, non-overlapping with proof region

### What to share after embedding

**One-time setup (first time only):**
```
verifier_package/   → send to verifier via a secure channel
                       (Signal, in person, encrypted email)
```
`chaos_key.txt` is already inside `verifier_package/` — no separate key
transmission is needed. The verifier places the package in a directory and
runs `dicom_extract.py` from there; the key is loaded automatically.

**Per-image (all subsequent transfers):**
```
stego.png   → send via any channel (email, PACS, USB)
```
No key travels with the image. The `chaos_key` is never stored in the
image — only its SHA-256 hash is embedded in the header. Without the key,
the metadata is cryptographically inaccessible.

---

## Extraction — Recipient Side

The recipient only needs `verifier_package/` — no prover code, no embedding scripts.
Run from `verifier_package/`. The key is read from `chaos_key.txt` automatically
(already inside the package):

```powershell
# Recommended: reads chaos_key.txt in current directory automatically
python scripts/dicom_extract.py path/to/stego.png

# Verbose / JSON / save metadata
python scripts/dicom_extract.py stego.png -v
python scripts/dicom_extract.py stego.png --json
python scripts/dicom_extract.py stego.png --save-meta recovered.json

# Override key explicitly (if testing with a different key)
python scripts/dicom_extract.py stego.png --key-file /path/chaos_key.txt
python scripts/dicom_extract.py stego.png --key "patient_secret"
```

### Parameters

| Argument | Description |
|---|---|
| `image` | Path to the stego PNG |
    | `--key / -k` | Inline chaos key string (overrides file lookup) |
    | `--key-file / -K` | Path to key file (default: `chaos_key.txt` in cwd) |
| `--proof-key` | Public proof key (default matches embed default) |
| `--verify-only` | Verify ZK proof only — no chaos key needed |
| `--save-meta FILE` | Save recovered metadata JSON to this file |
| `--verbose / -v` | Verbose output |
| `--json / -j` | JSON output |

### Successful output

```
Header  : 20248 metadata bits, proof=0 B, public=0 B
chaos_key validated ✓
Integrity: PASS ✓
Metadata : 294 tags recovered
[SUCCESS] Metadata extracted and integrity verified.

PatientID                      : ZZ RIDER MR8 1
PatientName                    : ZZ083108A
PatientBirthDate               : 19900101
PatientSex                     : M
StudyDate                      : 20080831
Modality                       : MR
InstitutionName                : M D Anderson Cancer Center
SOPInstanceUID                 : 1.2.840.113619.2.176...
SeriesDescription              : MultiFlip T1
… and 284 more tags
```

### Wrong key — immediate rejection

```
[FAILED] Extraction failed: Wrong chaos_key — SHA-256 hash mismatch
```

No metadata is revealed before the key is validated.

---

## Public Auditor Mode (no chaos_key)

Anyone can verify the ZK proof without knowing the chaos_key.
Run from `verifier_package/`:

```powershell
python scripts/dicom_extract.py stego.png --verify-only
```

Output:
```
ZK proof verification: PASS ✓
   Embedded bits : 20248
   Mode          : public auditor (metadata hidden, no chaos_key)

[SUCCESS] ZK proof is valid — image contains legitimately embedded data.
   Note: supply --key to also extract the hidden DICOM metadata.
```

---

## Python API

```python
import sys
from pathlib import Path
sys.path.insert(0, "src")
from zk_stego.dicom_handler import DicomStego

stego = DicomStego()
chaos_key = Path("chaos_key.txt").read_text().strip()  # pre-stored

# Embed
result = stego.embed(
    dcm_path="scan.dcm",
    output_png="stego.png",
    chaos_key=chaos_key,
    generate_zk_proof=False,   # True to also run ZK proof
    verbose=True,
)

# Extract
result = stego.extract(
    stego_png="stego.png",
    chaos_key=chaos_key,
    verbose=True,
)
print(result["success"])        # True
print(result["zk_verified"])    # True if proof was generated
print(result["metadata_dict"])  # dict of all DICOM tags
```

---

## Test Run Result (1-01.dcm, 512×512 MR)

| Metric | Value |
|---|---|
| Source file | `examples/dicom/1-01.dcm` |
| Image size | 512 × 512 px, 16-bit int16 |
| Raw metadata | 8,293 bytes (294 tags) |
| Compressed payload | 2,531 bytes → 20,248 bits |
| ROI pixels | 185,568 / 262,144 (70.8%) |
| Pixel positions used | 10,460 (5.6% of ROI) |
| Integrity check | **PASS** |
| Tags recovered | **294 / 294** |
| Wrong key rejection | **Immediate (SHA-256 mismatch)** |
