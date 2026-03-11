#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZK-SNARK Steganography - Embed CLI
Embeds a hidden message into a cover image and generates a ZK proof.
"""

import argparse
import json
import sys
import io
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root so 'src' is importable
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / 'src'))

from src.zk_stego.prover import Prover


def main():
    parser = argparse.ArgumentParser(
        description='Embed a hidden message into a cover image with a ZK-SNARK proof',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Embed with ZK proof (full flow)
  python scripts/embed.py cover.png stego.png "Secret message" --key "my_chaos_key"

  # Embed without generating a ZK proof (faster, no snarkjs required)
  python scripts/embed.py cover.png stego.png "Secret message" --key "my_chaos_key" --no-proof

  # Verbose output
  python scripts/embed.py cover.png stego.png "Secret message" --key "my_chaos_key" -v

  # JSON output (for scripting)
  python scripts/embed.py cover.png stego.png "Secret message" --key "my_chaos_key" --json

NOTE:
  Keep --key private — it is needed later to extract the hidden message.
  Anyone can verify the ZK proof without knowing the key.
  The key is never stored in the output image.
        """
    )

    parser.add_argument('cover',  help='Path to the cover (input) image')
    parser.add_argument('output', help='Path to save the stego (output) image')
    parser.add_argument('message', help='Secret message to embed')
    parser.add_argument('--key',  '-k', required=True,
                        help='Chaos key used for scrambling pixel positions')
    parser.add_argument('--no-proof', action='store_true',
                        help='Skip ZK proof generation (embed only)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    parser.add_argument('--json', '-j', action='store_true',
                        help='Output result as JSON')

    args = parser.parse_args()

    if not Path(args.cover).exists():
        print(f"ERROR: Cover image not found: {args.cover}")
        sys.exit(1)

    with_proof = not args.no_proof

    if args.verbose and not args.json:
        print(f"Cover image : {args.cover}")
        print(f"Output image: {args.output}")
        print(f"Message     : {args.message}")
        print(f"ZK proof    : {'yes' if with_proof else 'no'}")
        print()

    prover = Prover()
    result = prover.embed_and_prove(
        cover_image_path=args.cover,
        output_path=args.output,
        message=args.message,
        chaos_key=args.key,
        generate_zk_proof=with_proof,
    )

    if args.json:
        # Remove large raw-array fields before printing
        safe = {k: v for k, v in result.items()
                if k not in ('cover_pixels', 'stego_pixels')}
        print(json.dumps(safe, indent=2, default=str))
        return

    if result.get('success', True):
        print(f"[SUCCESS] Message embedded -> {args.output}")
        print(f"   Bits embedded : {result.get('message_bits', '?')}")
        print(f"   Starting pos  : ({result.get('x0', '?')}, {result.get('y0', '?')})")
        if with_proof:
            print(f"   ZK proof      : {'generated' if result.get('proof') else 'NOT generated'}")
    else:
        print(f"[FAILED] Embedding failed: {result.get('error', 'unknown error')}")
        sys.exit(1)


if __name__ == '__main__':
    main()
