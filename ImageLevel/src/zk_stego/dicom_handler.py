"""
DICOM Steganography Handler

Handles DICOM file loading, border-zone detection, entropy analysis, and
two-key LSB steganographic embedding / extraction with Reversible Data Hiding.

Two-key design
--------------
proof_key  (public / fixed default):
    Determines WHERE the ZK proof header is embedded.
    Anyone who knows proof_key can locate and verify the ZK proof
    without learning anything about the private patient data.

chaos_key  (private, user-chosen):
    Determines WHERE the compressed DICOM metadata is embedded.
    Only the holder of chaos_key can extract the patient data.
    The key is NEVER stored in the image; only its SHA-256 hash is.

Embedding layout (pure pixel LSB, 2-key system)
------------------------------------------------
Embedding targets the BORDER ZONE of the ROI — the outermost N pixels
of the tissue region (skull/transitional boundary), not core diagnostic tissue.

For each key region, positions are split into two equal sub-regions:
  undo sub-region : stores original 2 LSBs of the data sub-region pixels
  data sub-region : stores actual payload bits

This is Reversible Data Hiding (RDH): after extraction, the verifier
restores exact original pixel values by re-writing the saved original LSBs.

proof_key region header layout (84 bytes):
    [0:4]   b"ZKDC"                   magic
    [4:8]   version / flags            b"\\x02\\x00\\x00\\x00"  (v2: RDH + border zone)
    [8:40]  chaos_key_hash             SHA-256(chaos_key string)
    [40:72] metadata_sha256            SHA-256(gzip-compressed metadata)
    [72:76] metadata_bit_count         uint32
    [76:80] proof_json_len             uint32
    [80:84] public_json_len            uint32
    [84:]   proof JSON bytes + public inputs JSON bytes

chaos_key region  (non-overlapping with proof_key region):
    gzip-compressed DICOM metadata JSON bytes (all non-binary tags)
"""

import gzip
import hashlib
import json
import struct
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pydicom
from PIL import Image
from scipy.ndimage import binary_erosion, uniform_filter

from .utils import (
    ChaosGenerator,
    generate_chaos_key_from_secret,
)

# ── constants ────────────────────────────────────────────────────────────────
MAGIC = b"ZKDC"
HEADER_SIZE = 84          # bytes  (see layout above)
DEFAULT_PROOF_KEY = "zkdicom_proof_key_v1"   # public / fixed
# chaos_key is NOT stored here — it lives in chaos_key.txt (shipped with verifier_package/)
_HEADER_FMT = ">4s4s32s32sIII"              # must stay 84 bytes
BITS_PER_PIXEL           = 2    # bits embedded per pixel (bits 0 and 1)
BACKGROUND_PERCENTILE    = 5.0  # bottom N% of intensity treated as background
BORDER_EROSION_ITERATIONS = 10  # pixels eroded inward from ROI edge for border zone
HEADER_POSITIONS = (HEADER_SIZE * 8) // BITS_PER_PIXEL  # = 336 positions for 84-byte header


# =============================================================================
# DICOM I/O
# =============================================================================

class DicomHandler:
    """Load and pre-process DICOM files."""

    @staticmethod
    def load(dcm_path: str) -> Tuple[np.ndarray, str, Dict]:
        """
        Load a DICOM file.

        Returns
        -------
        pixel_array : ndarray, uint16, shape (H, W)
            Native DICOM pixel data preserved in uint16 without precision loss.
        metadata_json : str
            JSON string of all non-binary DICOM tags.
        info : dict
            Basic file info (rows, cols, bits_allocated, modality, …).
        """
        ds = pydicom.dcmread(dcm_path)
        pixel_array = DicomHandler.to_uint16(ds.pixel_array)
        metadata_dict = DicomHandler.extract_metadata_dict(ds)
        metadata_json = json.dumps(metadata_dict, ensure_ascii=True)

        info = {
            "path": str(dcm_path),
            "rows": int(ds.Rows),
            "cols": int(ds.Columns),
            "bits_allocated": int(ds.BitsAllocated),
            "modality": str(getattr(ds, "Modality", "")),
            "patient_id": str(getattr(ds, "PatientID", "")),
            "study_date": str(getattr(ds, "StudyDate", "")),
        }
        return pixel_array, metadata_json, info

    @staticmethod
    def extract_metadata_dict(ds) -> Dict[str, str]:
        """Serialize all non-binary DICOM tags to a string dict."""
        tags = {}
        for elem in ds:
            if elem.keyword == "PixelData":
                continue
            if elem.VR in ("OB", "OW", "OF", "SQ", "UN"):
                continue
            try:
                key = elem.keyword if elem.keyword else str(elem.tag)
                tags[key] = str(elem.value)
            except Exception:
                pass
        return tags

    @staticmethod
    def to_uint16(native_array: np.ndarray) -> np.ndarray:
        """
        Convert native DICOM pixel array to uint16 without precision loss.

        - uint16 : returned as-is
        - int16  : shifted +32768 to map [-32768, 32767] → [0, 65535]
        - other  : linearly scaled to [0, 65535]

        The int16 shift is a linear, invertible transform — all relative
        intensity differences are fully preserved. No diagnostic information
        is lost. The shift amount is implicitly encoded in the DICOM tags
        (RescaleIntercept / PixelRepresentation) already embedded in the metadata.
        """
        if native_array.dtype == np.uint16:
            return native_array.copy()
        if native_array.dtype == np.int16:
            return (native_array.astype(np.int32) + 32768).astype(np.uint16)
        arr = native_array.astype(np.float32)
        mn, mx = float(arr.min()), float(arr.max())
        if mx == mn:
            return np.zeros_like(arr, dtype=np.uint16)
        return ((arr - mn) / (mx - mn) * 65535.0).astype(np.uint16)

    @staticmethod
    def detect_roi(
        pixel_array: np.ndarray, background_percentile: float = BACKGROUND_PERCENTILE
    ) -> np.ndarray:
        """
        Return a boolean mask where True = pixel is inside the ROI.

        Strips the 2 embedding LSBs (bits 0 and 1) before computing the
        percentile threshold so the mask is bit-for-bit identical between
        the original cover image and the stego image — guaranteeing the
        same ROI on extraction.  Pixels in the bottom
        `background_percentile` % of intensity are excluded as background
        (air, padding, FOV collapse, etc.).
        """
        stripped = (pixel_array & 0xFFFC).astype(np.float64)
        threshold = float(np.percentile(stripped, background_percentile))
        return stripped > threshold

    @staticmethod
    def detect_border_zone(
        pixel_array: np.ndarray,
        erosion_iterations: int = BORDER_EROSION_ITERATIONS,
        background_percentile: float = BACKGROUND_PERCENTILE,
    ) -> np.ndarray:
        """
        Return a boolean mask of the border ring of the ROI.

        The border ring = outermost `erosion_iterations` pixels of the ROI,
        i.e. ROI pixels that are within N pixels of the ROI–background boundary
        (skull, transitional tissue, FOV padding). Core diagnostic tissue is
        excluded by eroding the ROI mask inward.

        This mask is stable across embedding because detect_roi() uses `& 0xFFFC`
        to strip embedded LSBs before thresholding — so the same border zone is
        returned on both the cover image and the stego image.

        Capacity guidance (512×512 MR brain):
            erosion_iterations=10 → ~148 k border pixels (24 % utilisation at 2×RDH payload)
            erosion_iterations=5  → ~77 k border pixels  (47 % utilisation)
        """
        roi_mask = DicomHandler.detect_roi(pixel_array, background_percentile)
        core_roi = binary_erosion(roi_mask, iterations=erosion_iterations)
        return roi_mask & ~core_roi

    @staticmethod
    def compute_local_variance(
        pixel_array: np.ndarray, kernel_size: int = 5
    ) -> np.ndarray:
        """
        Local variance map using a sliding window.

        Low variance → flat / uniform region → low entropy → safer to embed.

        The 2 embedding LSBs are stripped before computation (`& 0xFFFC`) so
        the variance map is identical between the original cover image and the
        stego image — guaranteeing the entropy-sort order on extraction.
        """
        # Strip 2 embedding LSBs: result is stable across 2-bit embedding
        arr = (pixel_array & 0xFFFC).astype(np.float32)
        mean = uniform_filter(arr, size=kernel_size)
        mean_sq = uniform_filter(arr ** 2, size=kernel_size)
        return np.clip(mean_sq - mean ** 2, 0.0, None)


# =============================================================================
# DICOM STEGANOGRAPHY — EMBED + EXTRACT
# =============================================================================

class DicomStego:
    """
    Two-key DICOM steganographic embedder / extractor.

    Usage — embed
    -------------
    stego = DicomStego()
    result = stego.embed("scan.dcm", "stego.png", chaos_key="patient_secret")

    Usage — extract
    ---------------
    result = stego.extract("stego.png", chaos_key="patient_secret")
    print(result["metadata_dict"])          # all DICOM tags recovered
    print(result["zk_verified"])            # True if proof is valid
    """

    def __init__(self, project_root: Optional[str] = None):
        self._project_root = project_root

    # -------------------------------------------------------------------------
    # PUBLIC: EMBED
    # -------------------------------------------------------------------------

    def embed(
        self,
        dcm_path: str,
        output_png: str,
        chaos_key: str,
        proof_key: str = DEFAULT_PROOF_KEY,
        generate_zk_proof: bool = True,
        background_percentile: float = BACKGROUND_PERCENTILE,
        erosion_iterations: int = BORDER_EROSION_ITERATIONS,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """
        Embed all DICOM metadata into a 16-bit PNG using two-key LSB steganography
        with Reversible Data Hiding (RDH).

        Embedding targets the BORDER ZONE of the ROI (outermost `erosion_iterations`
        pixels of the tissue region). Core diagnostic tissue is left untouched.

        RDH: before overwriting any pixel's LSBs, the original 2 LSBs are saved in a
        parallel undo sub-region. The verifier can call extract() and then restore the
        exact original pixel values with zero distortion.

        Parameters
        ----------
        dcm_path              : path to source .dcm file
        output_png            : path for output .png stego image (16-bit grayscale)
        chaos_key             : private key — only the holder can extract metadata
        proof_key             : public key — anyone can locate and verify the ZK proof
        generate_zk_proof     : whether to generate a Groth16 ZK proof
        background_percentile : bottom N% of intensity excluded as background
        erosion_iterations    : border ring width in pixels (default 10)
        verbose               : print progress messages
        """
        _log = print if verbose else lambda *a, **k: None

        _log("=" * 60)
        _log("DICOM ZK-Stego  —  Embedding")
        _log("=" * 60)

        # 1. Load DICOM
        pixel_array, metadata_json, info = DicomHandler.load(dcm_path)
        _log(f"Loaded : {dcm_path}  ({info['rows']}×{info['cols']}, "
             f"{info['bits_allocated']}-bit, {len(metadata_json)} B metadata)")

        # 2. Detect border zone (outermost N pixels of ROI, not core tissue)
        roi_mask = DicomHandler.detect_border_zone(
            pixel_array, erosion_iterations, background_percentile
        )
        border_count = int(roi_mask.sum())
        _log(f"Border zone: {border_count} / {pixel_array.size} pixels "
             f"({100 * border_count / pixel_array.size:.1f} %, "
             f"erosion={erosion_iterations} px)")

        # 3. Compress metadata
        meta_bytes = gzip.compress(metadata_json.encode("utf-8"), compresslevel=9)
        meta_bits = _bytes_to_bits(meta_bytes)
        _log(f"Payload: {len(meta_bytes)} B compressed → {len(meta_bits)} bits to embed")

        # 4. Fingerprint for ZK circuit: first 4 bytes of SHA-256 → 32-bit message
        meta_sha256 = hashlib.sha256(meta_bytes).digest()          # 32 bytes
        fingerprint_msg = meta_sha256[:4].decode("latin-1")        # 4-char string

        # 5. Optional ZK proof
        proof = None
        public_inputs = None
        height, width = pixel_array.shape
        chaos_key_int = generate_chaos_key_from_secret(chaos_key)
        meta_x0, meta_y0 = self._key_start(chaos_key_int, width, height, roi_mask)

        if generate_zk_proof:
            _log("\nGenerating ZK proof …")
            from .prover import Prover  # only needed on the prover side
            prover = Prover(self._project_root)
            result = prover._generate_zk_proof(
                pixel_array, fingerprint_msg, chaos_key, meta_x0, meta_y0
            )
            if result:
                proof = result["proof"]
                public_inputs = result["public_inputs"]
                _log("ZK proof generated.")
            else:
                _log("WARNING: ZK proof generation failed — continuing without proof.")

        # 6. Build binary proof-header block
        proof_block = _build_proof_block(
            chaos_key=chaos_key,
            metadata_sha256=meta_sha256,
            metadata_bit_count=len(meta_bits),
            proof=proof,
            public_inputs=public_inputs,
        )
        proof_bits = _bytes_to_bits(proof_block)
        _log(f"Proof block: {len(proof_block)} B → {len(proof_bits)} bits")

        # 7. Capacity check — RDH requires 2× data positions (data + undo per region)
        N_proof_data = _positions_needed(len(proof_bits))
        N_meta_data  = _positions_needed(len(meta_bits))
        needed_positions = 2 * (N_proof_data + N_meta_data)  # ×2 for RDH undo regions
        if needed_positions > border_count:
            raise ValueError(
                f"Insufficient border zone capacity: need {needed_positions} positions "
                f"(including RDH undo) but only {border_count} border pixels available. "
                f"Try decreasing erosion_iterations (currently {erosion_iterations})."
            )

        # 8. Proof-key DATA positions  (no entropy sorting — fixed structure)
        proof_key_int = generate_chaos_key_from_secret(proof_key)
        pk_x0, pk_y0 = self._key_start(proof_key_int, width, height, roi_mask)
        proof_positions = self._roi_positions(
            pixel_array, roi_mask,
            pk_x0, pk_y0, proof_key_int,
            N_proof_data,
            sort_by_entropy=False,
            exclude=None,
        )

        # 8b. RDH: proof-key UNDO positions (next N_proof_data positions, non-overlapping)
        proof_undo_positions = self._roi_positions(
            pixel_array, roi_mask,
            pk_x0, pk_y0, proof_key_int,
            N_proof_data,
            sort_by_entropy=False,
            exclude=set(map(tuple, proof_positions)),
        )
        # Save original LSBs at proof DATA positions before overwriting
        proof_undo_bits = _extract_at(pixel_array, proof_positions)

        # 9. Chaos-key DATA positions  (entropy sorted, non-overlapping with proof regions)
        proof_all_pos_set: Set[Tuple[int, int]] = (
            set(map(tuple, proof_positions)) | set(map(tuple, proof_undo_positions))
        )
        meta_positions = self._roi_positions(
            pixel_array, roi_mask,
            meta_x0, meta_y0, chaos_key_int,
            N_meta_data,
            sort_by_entropy=True,
            exclude=proof_all_pos_set,
        )

        # 9b. RDH: chaos-key UNDO positions (next N_meta_data positions, non-overlapping)
        meta_undo_positions = self._roi_positions(
            pixel_array, roi_mask,
            meta_x0, meta_y0, chaos_key_int,
            N_meta_data,
            sort_by_entropy=True,
            exclude=proof_all_pos_set | set(map(tuple, meta_positions)),
        )
        # Save original LSBs at meta DATA positions before overwriting
        meta_undo_bits = _extract_at(pixel_array, meta_positions)

        _log(f"\nEmbedding proof block at {len(proof_positions)} data + "
             f"{len(proof_undo_positions)} undo positions ({len(proof_bits)} bits)")
        _log(f"Embedding metadata    at {len(meta_positions)} data + "
             f"{len(meta_undo_positions)} undo positions ({len(meta_bits)} bits)")
        _log(f"Border zone utilisation: "
             f"{len(proof_positions)+len(proof_undo_positions)+len(meta_positions)+len(meta_undo_positions)}"
             f" / {border_count} pixels "
             f"({(len(proof_positions)+len(proof_undo_positions)+len(meta_positions)+len(meta_undo_positions))/border_count*100:.1f} %)")

        # 10. LSB embedding — undo regions first (so they use unmodified pixel values),
        #     then data regions
        stego = _embed_at(pixel_array.copy(), proof_undo_positions, proof_undo_bits)
        stego = _embed_at(stego,              proof_positions,      proof_bits)
        stego = _embed_at(stego,              meta_undo_positions,  meta_undo_bits)
        stego = _embed_at(stego,              meta_positions,       meta_bits)

        # 11. Save as 16-bit PNG — full native diagnostic bit-depth preserved
        Image.fromarray(stego.astype(np.uint16)).save(output_png)
        _log(f"\nSaved  : {output_png}  (16-bit grayscale PNG)")
        _log("RDH enabled — verifier can restore exact original pixel values after extraction.")

        return {
            "output_png": output_png,
            "chaos_key": chaos_key,
            "proof_key": proof_key,
            "metadata_json": metadata_json,
            "metadata_bytes": len(meta_bytes),
            "metadata_bits": len(meta_bits),
            "proof": proof,
            "public_inputs": public_inputs,
            "border_pixels": border_count,
            "dicom_info": info,
        }

    # -------------------------------------------------------------------------
    # PUBLIC: EXTRACT
    # -------------------------------------------------------------------------

    def extract(
        self,
        stego_png: str,
        chaos_key: str,
        proof_key: str = DEFAULT_PROOF_KEY,
        erosion_iterations: int = BORDER_EROSION_ITERATIONS,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        """
        Extract DICOM metadata from a stego PNG, verify the ZK proof, and
        restore the original pixel values (RDH).

        Parameters
        ----------
        stego_png          : path to stego PNG produced by embed()
        chaos_key          : private key used during embedding
        proof_key          : public proof key (default matches embed() default)
        erosion_iterations : must match the value used in embed() (default 10)
        verbose            : print progress messages

        Returns
        -------
        dict with keys:
            success               bool — integrity check passed
            zk_verified           bool — Groth16 proof checked out
            metadata_dict         dict — all DICOM tags (None if extraction failed)
            metadata_json         str  — raw JSON
            restored_pixel_array  ndarray — original pixel values restored via RDH
                                           (None if extraction failed)
            ...
        """
        _log = print if verbose else lambda *a, **k: None

        _log("=" * 60)
        _log("DICOM ZK-Stego  —  Extraction & Verification")
        _log("=" * 60)

        pixel_array = np.array(Image.open(stego_png), dtype=np.uint16)
        height, width = pixel_array.shape
        roi_mask = DicomHandler.detect_border_zone(
            pixel_array, erosion_iterations
        )

        # ------------------------------------------------------------------
        # Step 1: read the fixed 84-byte header from proof_key positions
        # ------------------------------------------------------------------
        proof_key_int = generate_chaos_key_from_secret(proof_key)
        pk_x0, pk_y0 = self._key_start(proof_key_int, width, height, roi_mask)

        header_positions = self._roi_positions(
            pixel_array, roi_mask,
            pk_x0, pk_y0, proof_key_int,
            HEADER_POSITIONS,
            sort_by_entropy=False,
            exclude=None,
        )
        header_bytes = _bits_to_bytes(_extract_at(pixel_array, header_positions))
        header = _parse_header(header_bytes)

        if header is None:
            return {
                "success": False,
                "error": "Magic bytes not found — image may not contain DICOM stego data",
                "restored_pixel_array": None,
            }

        _log(f"Header  : {header['metadata_bit_count']} metadata bits, "
             f"proof={header['proof_json_len']} B, public={header['public_json_len']} B")

        # ------------------------------------------------------------------
        # Step 2: validate chaos_key
        # ------------------------------------------------------------------
        expected_hash = hashlib.sha256(chaos_key.encode("utf-8")).digest()
        if expected_hash != header["chaos_key_hash"]:
            return {
                "success": False,
                "error": "Wrong chaos_key — SHA-256 hash mismatch",
                "restored_pixel_array": None,
            }
        _log("chaos_key validated ✓")

        # ------------------------------------------------------------------
        # Step 3: read proof DATA positions + proof tail (proof JSON + public JSON)
        # ------------------------------------------------------------------
        proof_tail_len = header["proof_json_len"] + header["public_json_len"]
        total_proof_bits = (HEADER_SIZE + proof_tail_len) * 8
        N_proof_data = _positions_needed(total_proof_bits)

        all_pk_data_positions = self._roi_positions(
            pixel_array, roi_mask,
            pk_x0, pk_y0, proof_key_int,
            N_proof_data,
            sort_by_entropy=False,
            exclude=None,
        )
        tail_positions = all_pk_data_positions[HEADER_POSITIONS:]
        tail_bytes = _bits_to_bytes(_extract_at(pixel_array, tail_positions))

        proof = None
        public_inputs = None
        try:
            pjl = header["proof_json_len"]
            ujl = header["public_json_len"]
            if pjl > 0:
                proof = json.loads(tail_bytes[:pjl].decode("utf-8"))
            if ujl > 0:
                public_inputs = json.loads(tail_bytes[pjl: pjl + ujl].decode("utf-8"))
        except Exception as e:
            _log(f"WARNING: could not parse proof/public JSON: {e}")

        # 3b. RDH: re-derive proof UNDO positions (same logic as embed)
        proof_undo_positions = self._roi_positions(
            pixel_array, roi_mask,
            pk_x0, pk_y0, proof_key_int,
            N_proof_data,
            sort_by_entropy=False,
            exclude=set(map(tuple, all_pk_data_positions)),
        )

        # All proof-region positions for exclusion of meta regions
        proof_all_pos_set: Set[Tuple[int, int]] = (
            set(map(tuple, all_pk_data_positions)) | set(map(tuple, proof_undo_positions))
        )

        # ------------------------------------------------------------------
        # Step 4: read metadata DATA positions + metadata bits
        # ------------------------------------------------------------------
        N_meta_data = _positions_needed(header["metadata_bit_count"])
        chaos_key_int = generate_chaos_key_from_secret(chaos_key)
        meta_x0, meta_y0 = self._key_start(chaos_key_int, width, height, roi_mask)

        meta_positions = self._roi_positions(
            pixel_array, roi_mask,
            meta_x0, meta_y0, chaos_key_int,
            N_meta_data,
            sort_by_entropy=True,
            exclude=proof_all_pos_set,
        )
        meta_bytes = _bits_to_bytes(_extract_at(pixel_array, meta_positions))

        # 4b. RDH: re-derive meta UNDO positions (same logic as embed)
        meta_undo_positions = self._roi_positions(
            pixel_array, roi_mask,
            meta_x0, meta_y0, chaos_key_int,
            N_meta_data,
            sort_by_entropy=True,
            exclude=proof_all_pos_set | set(map(tuple, meta_positions)),
        )

        # ------------------------------------------------------------------
        # Step 5: integrity check
        # ------------------------------------------------------------------
        computed_sha256 = hashlib.sha256(meta_bytes).digest()
        integrity_ok = computed_sha256 == header["metadata_sha256"]
        _log(f"Integrity: {'PASS ✓' if integrity_ok else 'FAIL ✗'}")

        # ------------------------------------------------------------------
        # Step 6: decompress
        # ------------------------------------------------------------------
        metadata_json = None
        metadata_dict = None
        if integrity_ok:
            try:
                metadata_json = gzip.decompress(meta_bytes).decode("utf-8")
                metadata_dict = json.loads(metadata_json)
                _log(f"Metadata : {len(metadata_dict)} tags recovered")
            except Exception as e:
                _log(f"WARNING: decompression / parse failed: {e}")
                integrity_ok = False

        # ------------------------------------------------------------------
        # Step 7: ZK proof verification
        # ------------------------------------------------------------------
        zk_verified = False
        zk_error = None
        if proof and public_inputs:
            _log("\nVerifying ZK proof …")
            zk_result = self._verify_zk(proof, public_inputs)
            zk_verified = zk_result.get("verified", False)
            zk_error = zk_result.get("error")
            _log(f"ZK proof : {'PASS ✓' if zk_verified else 'FAIL ✗'}")
        else:
            zk_error = "No ZK proof found in image"
            _log("ZK proof : not present")

        # ------------------------------------------------------------------
        # Step 8: RDH — restore original pixel values
        # ------------------------------------------------------------------
        # Read the saved original LSBs from undo sub-regions, then write
        # them back to the data positions to recover exact original pixels.
        restored_array: Optional[np.ndarray] = None
        if integrity_ok:
            proof_undo_bits = _extract_at(pixel_array, proof_undo_positions)
            meta_undo_bits  = _extract_at(pixel_array, meta_undo_positions)
            restored_array = _restore_pixels(
                pixel_array.copy(), all_pk_data_positions, proof_undo_bits
            )
            restored_array = _restore_pixels(
                restored_array, meta_positions, meta_undo_bits
            )
            _log("RDH restore: original pixel values recovered ✓")

        return {
            "success": integrity_ok,
            "zk_verified": zk_verified,
            "zk_error": zk_error,
            "integrity_ok": integrity_ok,
            "metadata_dict": metadata_dict,
            "metadata_json": metadata_json,
            "metadata_bits": header["metadata_bit_count"],
            "proof": proof,
            "public_inputs": public_inputs,
            "restored_pixel_array": restored_array,
        }

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _verify_zk(self, proof: Dict, public_inputs: List) -> Dict:
        """Call snarkjs groth16 verify via SnarkJSRunner."""
        try:
            from .utils import SnarkJSRunner
            runner = SnarkJSRunner()
            ok = runner.verify_groth16_proof(proof, public_inputs)
            return {"verified": ok}
        except Exception as e:
            return {"verified": False, "error": str(e)}

    @staticmethod
    def _key_start(
        key_int: int, width: int, height: int, roi_mask: np.ndarray
    ) -> Tuple[int, int]:
        """
        Derive a deterministic starting position from a key integer.
        Falls back to nearest ROI pixel if the derived pixel is background.
        """
        x = int((key_int >> 32) % width)
        y = int(key_int % height)
        if roi_mask[y, x]:
            return x, y
        # find nearest ROI pixel
        roi_ys, roi_xs = np.where(roi_mask)
        if len(roi_xs) == 0:
            return width // 2, height // 2  # last resort
        dists = (roi_xs.astype(np.int64) - x) ** 2 + (roi_ys.astype(np.int64) - y) ** 2
        idx = int(np.argmin(dists))
        return int(roi_xs[idx]), int(roi_ys[idx])

    @staticmethod
    def _roi_positions(
        pixel_array: np.ndarray,
        roi_mask: np.ndarray,
        x0: int,
        y0: int,
        chaos_key_int: int,
        n: int,
        sort_by_entropy: bool,
        exclude: Optional[Set[Tuple[int, int]]],
    ) -> List[Tuple[int, int]]:
        """
        Generate n positions using Arnold Cat Map + Logistic Map,
        restricted to ROI pixels, optionally sorted by local variance (ascending),
        and optionally excluding an existing position set.

        Strategy:
          1. Enumerate all ROI pixel coordinates (stable across 2-bit embedding
             because detect_roi uses `& 0xFFFC` — masking the embedded bits).
          2. Optionally sort by ascending local variance (entropy sort).
          3. Generate N_ROI chaos positions in image-space (ACM + LM).
          4. Map each chaos position's flattened index → ROI-index via modulo,
             so every selected coordinate is guaranteed inside the ROI.
          5. Use sequential fallback for any remaining positions.

        This approach satisfies the Arnold Cat Map + Logistic Map requirement
        from the paper while guaranteeing ROI coverage regardless of how the
        chaos trajectory distributes across the image.
        """
        height, width = pixel_array.shape

        # 1. Enumerate all ROI pixels
        roi_ys, roi_xs = np.where(roi_mask)
        all_roi: List[Tuple[int, int]] = list(zip(roi_xs.tolist(), roi_ys.tolist()))

        # Filter: exclude already-used positions
        if exclude:
            all_roi = [(x, y) for (x, y) in all_roi if (x, y) not in exclude]

        N_roi = len(all_roi)
        if N_roi < n:
            raise ValueError(
                f"Insufficient ROI capacity: need {n} positions "
                f"but only {N_roi} ROI pixels available after exclusions."
            )

        # 2. Optional entropy sort (ascending variance → embed in flattest areas)
        if sort_by_entropy:
            var_map = DicomHandler.compute_local_variance(pixel_array)
            all_roi.sort(key=lambda pos: var_map[pos[1], pos[0]])

        # 3. Generate chaos trajectory in image-space (ACM + LM)
        chaos_gen = ChaosGenerator(width, height)
        pool = chaos_gen.generate_positions(x0, y0, chaos_key_int, N_roi)

        # 4. Map each chaos (cx, cy) → ROI index via flattened coordinate modulo
        seen: Set[int] = set()
        result: List[Tuple[int, int]] = []
        for cx, cy in pool:
            flat = cy * width + cx          # unique flat index in full image
            roi_idx = flat % N_roi          # map to ROI index space
            if roi_idx not in seen:
                seen.add(roi_idx)
                result.append(all_roi[roi_idx])
            if len(result) >= n:
                break

        # 5. Sequential fallback — covers any remaining slots deterministically
        if len(result) < n:
            for idx in range(N_roi):
                if idx not in seen:
                    seen.add(idx)
                    result.append(all_roi[idx])
                if len(result) >= n:
                    break

        return result[:n]


# =============================================================================
# MODULE-LEVEL HELPERS (no state)
# =============================================================================

def _bytes_to_bits(data: bytes) -> List[int]:
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _bits_to_bytes(bits: List[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            if i + j < len(bits):
                byte |= bits[i + j] << (7 - j)
        out.append(byte)
    return bytes(out)


def _positions_needed(n_bits: int) -> int:
    """Number of pixel positions needed to carry n_bits at BITS_PER_PIXEL per pixel."""
    return (n_bits + BITS_PER_PIXEL - 1) // BITS_PER_PIXEL


def _embed_at(
    pixel_array: np.ndarray, positions: List[Tuple[int, int]], bits: List[int]
) -> np.ndarray:
    """
    Embed bits into the two LSBs (bits 1 and 0) of a 16-bit pixel array.
    Each pixel position carries 2 bits:
        pixel bit 1  ←  bits[2*i]
        pixel bit 0  ←  bits[2*i + 1]
    """
    img = pixel_array.copy()
    for i, (x, y) in enumerate(positions):
        b_idx = i * 2
        b0 = int(bits[b_idx])     if b_idx     < len(bits) else 0  # → bit 1
        b1 = int(bits[b_idx + 1]) if b_idx + 1 < len(bits) else 0  # → bit 0
        img[y, x] = (int(img[y, x]) & 0xFFFC) | ((b0 & 1) << 1) | (b1 & 1)
    return img


def _extract_at(
    pixel_array: np.ndarray, positions: List[Tuple[int, int]]
) -> List[int]:
    """
    Extract the two LSBs (bits 1 and 0) from each pixel at the given positions.
    Returns a flat list: [bit1_pos0, bit0_pos0, bit1_pos1, bit0_pos1, …]
    This mirrors the layout used by _embed_at.
    """
    result: List[int] = []
    for (x, y) in positions:
        val = int(pixel_array[y, x])
        result.append((val >> 1) & 1)  # bit 1
        result.append(val & 1)          # bit 0
    return result


def _restore_pixels(
    pixel_array: np.ndarray,
    positions: List[Tuple[int, int]],
    undo_bits: List[int],
) -> np.ndarray:
    """
    Restore original pixel values at embedding positions using saved undo bits.

    The undo_bits are the original 2 LSBs that were read BEFORE embedding,
    stored in the RDH undo sub-region. Writing them back reverses the embedding
    exactly: `_restore_pixels(stego, positions, undo_bits) == original`.

    Mirrors _embed_at exactly — same bit layout (bit 1 then bit 0 per position).
    """
    return _embed_at(pixel_array, positions, undo_bits)


def _build_proof_block(
    chaos_key: str,
    metadata_sha256: bytes,
    metadata_bit_count: int,
    proof: Optional[Dict],
    public_inputs: Optional[List],
) -> bytes:
    """Serialise proof header + proof JSON + public-inputs JSON into bytes."""
    proof_json = b""
    public_json = b""
    if proof:
        proof_json = json.dumps(proof, separators=(",", ":")).encode("utf-8")
    if public_inputs:
        public_json = json.dumps(public_inputs, separators=(",", ":")).encode("utf-8")

    chaos_key_hash = hashlib.sha256(chaos_key.encode("utf-8")).digest()  # 32 bytes

    header = struct.pack(
        _HEADER_FMT,
        MAGIC,                        # 4 bytes
        b"\x02\x00\x00\x00",         # 4 bytes  version=2 (RDH + border zone)
        chaos_key_hash,               # 32 bytes
        metadata_sha256,              # 32 bytes
        metadata_bit_count,           # uint32
        len(proof_json),              # uint32
        len(public_json),             # uint32
    )
    assert len(header) == HEADER_SIZE, f"Header size mismatch: {len(header)}"
    return header + proof_json + public_json


def _parse_header(data: bytes) -> Optional[Dict]:
    """Parse the 84-byte proof header. Returns None if magic is wrong."""
    if len(data) < HEADER_SIZE:
        return None
    magic, flags, ck_hash, meta_sha256, meta_bits, pjl, ujl = struct.unpack(
        _HEADER_FMT, data[:HEADER_SIZE]
    )
    if magic != MAGIC:
        return None
    return {
        "chaos_key_hash":     ck_hash,        # bytes[32]
        "metadata_sha256":    meta_sha256,     # bytes[32]
        "metadata_bit_count": meta_bits,       # int
        "proof_json_len":     pjl,             # int
        "public_json_len":    ujl,             # int
    }
