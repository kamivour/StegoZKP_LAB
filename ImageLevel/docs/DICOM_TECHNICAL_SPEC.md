# DICOM ZK-Stego — Technical Specification

## Source Files

| File | Purpose |
|---|---|
| `src/zk_stego/dicom_handler.py` | All DICOM stego logic — two classes + module helpers |
| `scripts/dicom_embed.py` | CLI embedder |
| `scripts/dicom_extract.py` | CLI extractor / verifier (two modes) |

---

## Class: `DicomHandler`

Static utility class. No state.

### `DicomHandler.load(dcm_path) → (pixel_array, metadata_json, info)`

Reads a `.dcm` file via pydicom.  
Returns:
- `pixel_array`: `np.ndarray` dtype `uint16`, shape `(H, W)` — native pixel
  values, no normalisation. `int16` input is shifted `+32768` to `uint16`.
- `metadata_json`: JSON string of all non-binary DICOM tags.
- `info`: dict with `rows`, `cols`, `bits_allocated`, `modality`,
  `patient_id`, `study_date`.

### `DicomHandler.to_uint16(native_array) → np.ndarray`

Converts native DICOM pixel array to `uint16`:
- `uint16` → returned as-is
- `int16` → `(pixel + 32768).astype(uint16)` — lossless, invertible
- other → linearly scaled to `[0, 65535]`

### `DicomHandler.extract_metadata_dict(ds) → dict[str, str]`

Iterates all DICOM elements. Skips `PixelData` and VRs `OB OW OF SQ UN`.
Returns `{keyword: str(value)}` for all remaining elements.

### `DicomHandler.detect_roi(pixel_array, background_percentile=5.0) → np.ndarray[bool]`

Returns `True` where pixel is inside the ROI (non-background).  
Procedure:
1. Strip 2 LSBs: `stripped = pixel_array & 0xFFFC`
2. `threshold = np.percentile(stripped, background_percentile)`
3. `roi_mask = stripped > threshold`

The `& 0xFFFC` mask makes the ROI mask **bit-for-bit identical between the
original image and the stego image**, which is required for reproducible
extraction.

### `DicomHandler.compute_local_variance(pixel_array, kernel_size=5) → np.ndarray`

Sliding-window local variance map using `scipy.ndimage.uniform_filter`.  
Input is first masked with `& 0xFFFC` to strip embedding bits — ensures the
variance sort order is identical on embed and extract.  
Low variance = flat region = preferred embedding target.

---

## Class: `DicomStego`

### `DicomStego.embed(dcm_path, output_png, chaos_key, proof_key, generate_zk_proof, background_percentile, verbose) → dict`

Full embedding pipeline:

```
1. DicomHandler.load()           → pixel_array (uint16), metadata_json
2. DicomHandler.detect_roi()     → roi_mask
3. gzip.compress(metadata_json)  → meta_bytes
4. SHA-256(meta_bytes)[:4]       → ZK fingerprint (32-bit message)
5. Prover._generate_zk_proof()   → proof, public_inputs  (optional)
6. _build_proof_block()          → 84-byte header + proof JSON bytes
7. _roi_positions(proof_key, no entropy sort)  → proof pixel positions
8. _roi_positions(chaos_key, entropy sort, exclude proof positions)
                                 → metadata pixel positions
9. _embed_at(proof_positions, proof_bits)    → stego array
10. _embed_at(meta_positions,  meta_bits)    → stego array
11. PIL.Image.fromarray(uint16).save(png)    → 16-bit PNG
```

Returns dict: `output_png, chaos_key, proof_key, metadata_json,
metadata_bytes, metadata_bits, proof, public_inputs, roi_pixels, dicom_info`.

### `DicomStego.extract(stego_png, chaos_key, proof_key, verbose) → dict`

Full extraction and verification pipeline:

```
1. PIL.Image.open(png) → pixel_array (uint16)
2. detect_roi()        → roi_mask
3. Read 84-byte header from proof_key positions
4. Validate: SHA-256(chaos_key) == header[chaos_key_hash]
5. Read ZK proof tail from proof_key positions
6. Read metadata bits from chaos_key positions (entropy sort, exclude proof)
7. SHA-256(meta_bytes) == header[metadata_sha256]  → integrity check
8. gzip.decompress(meta_bytes) → metadata_json → metadata_dict
9. snarkjs groth16 verify → zk_verified
```

Returns dict: `success, zk_verified, zk_error, integrity_ok,
metadata_dict, metadata_json, metadata_bits, proof, public_inputs`.

---

## Module-Level Helper Functions

### `_bytes_to_bits(data: bytes) → list[int]`
MSB-first byte-to-bit expansion. `b"\xA5"` → `[1,0,1,0,0,1,0,1]`.

### `_bits_to_bytes(bits: list[int]) → bytes`
Inverse of `_bytes_to_bits`. Pads last byte with zeros if needed.

### `_positions_needed(n_bits: int) → int`
`ceil(n_bits / BITS_PER_PIXEL)`.  
With `BITS_PER_PIXEL = 2`: 20248 bits → 10124 positions.

### `_embed_at(pixel_array, positions, bits) → np.ndarray`
Embeds 2 bits per position:
```python
pixel & 0xFFFC | (bits[2*i] << 1) | bits[2*i + 1]
```
Bit 1 of the pixel receives the first data bit; bit 0 receives the second.

### `_extract_at(pixel_array, positions) → list[int]`
Extracts 2 bits per position:
```python
[(val >> 1) & 1, val & 1]  for val = pixel_array[y, x]
```
Returns a flat list — mirrors the layout used by `_embed_at`.

### `_build_proof_block(chaos_key, metadata_sha256, metadata_bit_count, proof, public_inputs) → bytes`
Packs the 84-byte header and appends proof JSON bytes.

### `_parse_header(data: bytes) → dict | None`
Unpacks the 84-byte header. Returns `None` if magic bytes `b"ZKDC"` are absent.

---

## Constants

| Name | Value | Meaning |
|---|---|---|
| `MAGIC` | `b"ZKDC"` | Header magic bytes |
| `HEADER_SIZE` | `84` | Fixed header size in bytes |
| `BITS_PER_PIXEL` | `2` | Bits embedded per pixel |
| `HEADER_POSITIONS` | `336` | Pixel positions for 84-byte header at 2 bits/px |
| `DEFAULT_PROOF_KEY` | `"zkdicom_proof_key_v1"` | Fixed public key |
| `BACKGROUND_PERCENTILE` | `5.0` | Default ROI background cut |
| `_HEADER_FMT` | `">4s4s32s32sIII"` | struct format, exactly 84 bytes |

---

## Header Binary Layout

```
Offset  Size  Type    Field
0       4     bytes   MAGIC = b"ZKDC"
4       4     bytes   version = b"\x01\x00\x00\x00"
8       32    bytes   chaos_key_hash = SHA-256(chaos_key.encode())
40      32    bytes   metadata_sha256 = SHA-256(gzip_compressed_metadata)
72      4     uint32  metadata_bit_count  (big-endian)
76      4     uint32  proof_json_len      (big-endian)
80      4     uint32  public_json_len     (big-endian)
84      var   bytes   proof JSON (UTF-8)
84+pjl  var   bytes   public inputs JSON (UTF-8)
```

Total positions consumed by the proof_key region:
`HEADER_POSITIONS + ceil((proof_json_len + public_json_len) * 8 / 2)`

---

## Position Selection Algorithm (`_roi_positions`)

```
Input:
  pixel_array   — the current image (uint16)
  roi_mask      — boolean mask from detect_roi()
  x0, y0        — chaos starting position derived from key
  chaos_key_int — 64-bit integer from generate_chaos_key_from_secret()
  n             — number of positions needed
  sort_by_entropy — if True, sort ROI pixels by ascending local variance
  exclude       — set of (x,y) tuples already allocated to proof_key region

Steps:
1. all_roi = list of (x,y) tuples where roi_mask is True
2. Remove any (x,y) in exclude
3. If sort_by_entropy: sort all_roi by compute_local_variance()[y,x]  (ascending)
4. pool = ChaosGenerator.generate_positions(x0, y0, chaos_key_int, len(all_roi))
5. For each (cx, cy) in pool:
     flat = cy * width + cx
     roi_idx = flat % len(all_roi)
     if roi_idx not in seen: append all_roi[roi_idx]
6. Sequential fallback for any remaining positions
7. Return first n entries
```

This guarantees:
- All selected positions are inside the ROI mask
- The chaos scatter property (Arnold Cat Map + Logistic Map) is preserved
- The same key always produces the same positions (deterministic)

---

## ZK Integrity Approach

The circuit accepts 32 bits (4 bytes) as the message input. The full DICOM
metadata payload is ~20 000 bits — too large for the circuit directly.

**Fingerprint approach:**
```python
meta_bytes       = gzip.compress(metadata_json.encode())
meta_sha256      = hashlib.sha256(meta_bytes).digest()        # 32 bytes
fingerprint_msg  = meta_sha256[:4].decode("latin-1")          # 4 chars → 32 bits
```

The ZK proof attests: "I used the correct chaos_key and embedding positions."  
The SHA-256 hash (stored in the header) attests: "The payload was not tampered with."

Together they provide full integrity coverage within the pot12 constraint budget.

---

## Capacity Analysis (512×512 MR image)

| Item | Bits | Positions |
|---|---|---|
| Header (84 bytes) | 672 | 336 |
| ZK proof JSON (~2 KB) | ~16 000 | ~8 000 |
| Public inputs JSON (~1 KB) | ~8 000 | ~4 000 |
| Metadata gzip (~2.5 KB) | 20 248 | 10 124 |
| **Total** | **~44 920** | **~22 460** |
| ROI pixels available | — | **185 568** |
| **ROI utilisation** | — | **~12%** |

There is an 8× headroom, which accommodates larger DICOM files and longer
ZK proofs without capacity issues.
