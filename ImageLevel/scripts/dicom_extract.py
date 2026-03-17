#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM ZK-Stego  —  Extract & Verify CLI

Extracts hidden DICOM metadata from a stego PNG and verifies
the embedded Groth16 ZK-SNARK proof.

Two verification modes
----------------------
  Public auditor  (--verify-only):
      Does NOT need chaos_key.
      Reads only the proof_key region to locate and verify the ZK proof.
      Confirms the image contains a valid integrity proof — cannot read metadata.

  Recipient  (--key required):
      Full extraction: recovers all DICOM metadata + verifies ZK proof.
      Confirms metadata integrity via SHA-256 fingerprint check.

Usage
-----
  python scripts/dicom_extract.py stego.png --key "patient_secret"
  python scripts/dicom_extract.py stego.png --key "patient_secret" -v
  python scripts/dicom_extract.py stego.png --key "patient_secret" --json
  python scripts/dicom_extract.py stego.png --verify-only
"""

import argparse
import io
import json
import sys
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_stego.dicom_handler import (
    DicomStego,
    DicomHandler,
    DEFAULT_PROOF_KEY,
    BORDER_EROSION_ITERATIONS,
    HEADER_SIZE,
    HEADER_POSITIONS,
    _bytes_to_bits,
    _bits_to_bytes,
    _extract_at,
    _parse_header,
    _positions_needed,
)
from src.zk_stego.utils import generate_chaos_key_from_secret


def verify_only(stego_png: str, proof_key: str, verbose: bool, as_json: bool,
                erosion_iterations: int = BORDER_EROSION_ITERATIONS) -> None:
    """
    Public-auditor mode: verify the ZK proof without the chaos_key.
    Reads only the proof_key region. Metadata remains hidden.
    """
    import numpy as np
    from PIL import Image

    pixel_array = np.array(Image.open(stego_png), dtype=np.uint16)
    height, width = pixel_array.shape
    roi_mask = DicomHandler.detect_border_zone(pixel_array, erosion_iterations)

    proof_key_int = generate_chaos_key_from_secret(proof_key)
    stego_obj = DicomStego()
    pk_x0, pk_y0 = stego_obj._key_start(proof_key_int, width, height, roi_mask)

    # Read header
    header_positions = stego_obj._roi_positions(
        pixel_array, roi_mask, pk_x0, pk_y0, proof_key_int,
        HEADER_POSITIONS, sort_by_entropy=False, exclude=None,
    )
    header_bytes = _bits_to_bytes(_extract_at(pixel_array, header_positions))
    header = _parse_header(header_bytes)

    if header is None:
        if as_json:
            print(json.dumps({"success": False, "error": "No DICOM stego data found"}))
        else:
            print("ERROR: No DICOM stego data found in image.")
            print("[FAILED]")
        sys.exit(1)

    proof_tail = header["proof_json_len"] + header["public_json_len"]
    total_bits = (HEADER_SIZE + proof_tail) * 8

    all_pk_positions = stego_obj._roi_positions(
        pixel_array, roi_mask, pk_x0, pk_y0, proof_key_int,
        _positions_needed(total_bits), sort_by_entropy=False, exclude=None,
    )
    tail_bytes = _bits_to_bytes(_extract_at(pixel_array, all_pk_positions[HEADER_POSITIONS:]))

    proof = public_inputs = None
    try:
        pjl, ujl = header["proof_json_len"], header["public_json_len"]
        if pjl > 0:
            proof = json.loads(tail_bytes[:pjl].decode("utf-8"))
        if ujl > 0:
            public_inputs = json.loads(tail_bytes[pjl: pjl + ujl].decode("utf-8"))
    except Exception as e:
        if verbose:
            print(f"WARNING: could not parse proof JSON: {e}")

    # ZK verification
    zk_verified = False
    zk_error = None
    if proof and public_inputs:
        result = stego_obj._verify_zk(proof, public_inputs)
        zk_verified = result.get("verified", False)
        zk_error = result.get("error")
    else:
        zk_error = "No proof found"

    if as_json:
        print(json.dumps({
            "success": zk_verified,
            "zk_verified": zk_verified,
            "zk_error": zk_error,
            "metadata_bit_count": header["metadata_bit_count"],
            "mode": "public_auditor",
        }, indent=2))
        return

    print(f"ZK proof verification: {'PASS ✓' if zk_verified else 'FAIL ✗'}")
    print(f"   Embedded bits : {header['metadata_bit_count']}")
    print(f"   Mode          : public auditor (metadata hidden, no chaos_key)")
    if zk_error:
        print(f"   Error         : {zk_error}")
    print()
    if zk_verified:
        print("[SUCCESS] ZK proof is valid — image contains legitimately embedded data.")
        print("   Note: supply --key to also extract the hidden DICOM metadata.")
    else:
        print("[FAILED] ZK proof verification failed.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract hidden DICOM metadata from a stego PNG and verify ZK proof",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Recommended: reads chaos_key.txt automatically
  python scripts/dicom_extract.py stego.png

  # Explicit key file
  python scripts/dicom_extract.py stego.png --key-file /path/to/chaos_key.txt

  # Inline key (useful for first-time testing)
  python scripts/dicom_extract.py stego.png --key "my_secret"

  # Public auditor: verify proof only (no chaos_key needed)
  python scripts/dicom_extract.py stego.png --verify-only

  # Verbose and JSON output
  python scripts/dicom_extract.py stego.png -v --json

  # Save recovered metadata to file
  python scripts/dicom_extract.py stego.png --save-meta recovered.json

Key lookup order
----------------
  1. --key "..."         inline string
  2. --key-file FILE     explicit file path
  3. chaos_key.txt       auto-detected in current directory (default)
        """,
    )

    parser.add_argument("image", help="Path to stego PNG image")
    parser.add_argument("--key", "-k", default=None,
                        help="Private chaos key for metadata extraction (use --key-file for pre-stored key)")
    parser.add_argument("--key-file", "-K", default=None, metavar="FILE",
                        help="Path to a file containing the chaos key (one-time setup — avoids typing key every run)")
    parser.add_argument("--proof-key", default=DEFAULT_PROOF_KEY,
                        help=f"Public proof key (default: '{DEFAULT_PROOF_KEY}')")
    parser.add_argument("--verify-only", action="store_true",
                        help="Only verify the ZK proof, do not extract metadata")
    parser.add_argument("--save-meta", metavar="FILE",
                        help="Save recovered metadata JSON to this file")
    parser.add_argument("--restore-output", metavar="FILE",
                        help="Save RDH-restored original image to this file (16-bit PNG). "
                             "Only written if extraction and integrity check both pass.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--json", "-j", action="store_true",
                        help="JSON output format")

    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"ERROR: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    # Public auditor mode
    if args.verify_only:
        verify_only(args.image, args.proof_key, args.verbose, args.json)
        return

    # Warn if --restore-output requested without full extraction
    if getattr(args, "restore_output", None) and args.verify_only:
        print("WARNING: --restore-output requires full extraction (not --verify-only). Ignoring.",
              file=sys.stderr)

    # Resolve chaos_key: --key overrides --key-file
    chaos_key = args.key
    # Resolve chaos_key: --key > --key-file > chaos_key.txt
    chaos_key = args.key
    if chaos_key is None:
        key_file = Path(args.key_file) if args.key_file else Path("chaos_key.txt")
        if not key_file.exists():
            print(
                f"ERROR: No chaos key found.\n"
                f"       Options:\n"
                f"         chaos_key.txt in current directory  (recommended)\n"
                f"         --key-file /path/key.txt\n"
                f"         --key \"my_secret\"\n"
                f"       Use --verify-only for proof-only verification (no key needed).",
                file=sys.stderr,
            )
            sys.exit(1)
        chaos_key = key_file.read_text(encoding="utf-8").strip()
        if not chaos_key:
            print(f"ERROR: Key file is empty: {key_file}", file=sys.stderr)
            sys.exit(1)
    args.key = chaos_key

    stego = DicomStego()
    result = stego.extract(
        stego_png=args.image,
        chaos_key=args.key,
        proof_key=args.proof_key,
        verbose=args.verbose and not args.json,
    )

    # RDH: save restored image if requested
    if getattr(args, "restore_output", None) and result.get("restored_pixel_array") is not None:
        import numpy as np
        from PIL import Image as _PILImage
        _PILImage.fromarray(result["restored_pixel_array"].astype(np.uint16)).save(
            args.restore_output
        )
        if not args.json:
            print(f"RDH restored image saved to: {args.restore_output}")

    if args.json:
        safe = {k: v for k, v in result.items() if k not in ("proof", "public_inputs")}
        print(json.dumps(safe, indent=2, default=str, ensure_ascii=False))
        return

    # Human-readable output
    if result["success"]:
        print(f"[SUCCESS] Metadata extracted and integrity verified.")
        print(f"   ZK proof : {'PASS ✓' if result['zk_verified'] else 'not verified'}")
        print(f"   Bits     : {result['metadata_bits']}")

        meta = result.get("metadata_dict") or {}
        print()
        print("Recovered DICOM metadata (selected tags):")
        important = [
            "PatientID", "PatientName", "PatientBirthDate", "PatientSex",
            "StudyDate", "StudyDescription", "Modality",
            "InstitutionName", "ReferringPhysicianName",
            "SOPInstanceUID", "SeriesDescription",
        ]
        for tag in important:
            if tag in meta:
                print(f"   {tag:<30} : {meta[tag]}")
        remaining = len(meta) - len([t for t in important if t in meta])
        if remaining > 0:
            print(f"   … and {remaining} more tags")

        if args.save_meta and result.get("metadata_json"):
            Path(args.save_meta).write_text(
                result["metadata_json"], encoding="utf-8"
            )
            print(f"\nFull metadata saved to: {args.save_meta}")
    else:
        print(f"[FAILED] Extraction failed: {result.get('error', 'unknown error')}")
        if result.get("zk_error"):
            print(f"   ZK error : {result['zk_error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
