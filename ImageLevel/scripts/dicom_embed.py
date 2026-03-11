#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM ZK-Stego  —  Embed CLI

Hides all patient metadata from a DICOM file inside a PNG image
using two-key LSB steganography + a Groth16 ZK-SNARK integrity proof.

No PNG chunk is added — the data lives entirely in pixel LSBs.

The chaos_key is fixed and pre-shared once with the verifier.  After that
one-time setup, no key needs to travel with subsequent images.

Usage
-----
  python scripts/dicom_embed.py scan.dcm stego.png                      # reads chaos_key.txt
  python scripts/dicom_embed.py scan.dcm stego.png --key-file mykey.txt
  python scripts/dicom_embed.py scan.dcm stego.png --key "patient_secret"
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

from src.zk_stego.dicom_handler import DicomStego, DEFAULT_PROOF_KEY


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed DICOM metadata into a PNG using ZK-SNARK steganography",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Recommended: key stored in chaos_key.txt from one-time setup
  python scripts/dicom_embed.py examples/dicom/1-01.dcm stego.png

  # Explicit key file
  python scripts/dicom_embed.py scan.dcm stego.png --key-file /path/to/chaos_key.txt

  # Inline key (useful for first-time testing)
  python scripts/dicom_embed.py scan.dcm stego.png --key "my_secret"

  # Skip ZK proof (faster, embedding only)
  python scripts/dicom_embed.py scan.dcm stego.png --no-proof

  # Verbose or JSON output
  python scripts/dicom_embed.py scan.dcm stego.png -v
  python scripts/dicom_embed.py scan.dcm stego.png --json

Key lookup order
----------------
  1. --key "..."         inline string
  2. --key-file FILE     explicit file path
  3. chaos_key.txt       auto-detected in current directory (default)

What gets stored
----------------
  DICOM image pixels  -> saved as native 16-bit grayscale PNG
  All non-binary DICOM tags (PatientID, StudyDate, Modality, …)
     -> gzip-compressed and hidden in pixel LSBs at chaos_key positions
  ZK proof (Groth16) + header
     -> hidden in pixel LSBs at proof_key positions (publicly known)

The chaos_key is NEVER stored in the image.
        """,
    )

    parser.add_argument("dcm",    help="Source DICOM file (.dcm)")
    parser.add_argument("output", help="Output stego PNG file (.png)")
    parser.add_argument("--key",  "-k", default=None,
                        help="Inline chaos key string (use --key-file or chaos_key.txt for pre-stored key)")
    parser.add_argument("--key-file", "-K", default=None, metavar="FILE",
                        help="File containing the chaos key (default: chaos_key.txt in cwd)")
    parser.add_argument("--proof-key", default=DEFAULT_PROOF_KEY,
                        help=f"Public proof key (default: '{DEFAULT_PROOF_KEY}')")
    parser.add_argument("--no-proof", action="store_true",
                        help="Skip ZK proof generation (faster)")
    parser.add_argument("--background-percentile", type=float, default=5.0,
                        help="Bottom N%%%% of pixel intensity treated as background (default: 5.0)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--json", "-j", action="store_true",
                        help="JSON output format")

    args = parser.parse_args()

    if not Path(args.dcm).exists():
        print(f"ERROR: DICOM file not found: {args.dcm}", file=sys.stderr)
        sys.exit(1)

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
                f"         --key \"my_secret\"",
                file=sys.stderr,
            )
            sys.exit(1)
        chaos_key = key_file.read_text(encoding="utf-8").strip()
        if not chaos_key:
            print(f"ERROR: Key file is empty: {key_file}", file=sys.stderr)
            sys.exit(1)
    args.key = chaos_key

    stego = DicomStego()

    try:
        result = stego.embed(
            dcm_path=args.dcm,
            output_png=args.output,
            chaos_key=args.key,
            proof_key=args.proof_key,
            generate_zk_proof=not args.no_proof,
            background_percentile=args.background_percentile,
            verbose=args.verbose and not args.json,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected failure — {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        safe = {
            k: v for k, v in result.items()
            if k not in ("metadata_json", "proof", "public_inputs")
        }
        print(json.dumps(safe, indent=2, default=str))
        return

    # Human-readable output
    info = result["dicom_info"]
    print(f"[SUCCESS] Embedded DICOM metadata into {args.output}")
    print(f"   Patient ID   : {info.get('patient_id', '—')}")
    print(f"   Study date   : {info.get('study_date', '—')}")
    print(f"   Modality     : {info.get('modality', '—')}")
    print(f"   Image size   : {info['rows']} × {info['cols']} px")
    print(f"   Metadata     : {result['metadata_bytes']} B compressed  "
          f"({result['metadata_bits']} bits embedded)")
    print(f"   ROI pixels   : {result['roi_pixels']}")
    print(f"   ZK proof     : {'generated' if result['proof'] else 'not generated'}")
    print()
    print("Reminder: chaos_key was pre-shared with verifier during one-time setup.")
    print("          Subsequent transfers need only the stego PNG — no key required.")


if __name__ == "__main__":
    main()
