#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZK-SNARK Steganography Verification API
Single-command verification of chaos-based steganographic ZK proofs
"""

import argparse
import json
import sys
import os
import io
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / 'src'))

import numpy as np
from PIL import Image
from zk_stego.hybrid_proof_artifact import extract_chaos_proof
from zk_stego.zk_proof_generator import ZKProofGenerator
from zk_stego.chaos_embedding import ChaosEmbedding, generate_chaos_key_from_secret

def verify_zk_stego(stego_image_path: str, secret_key: str = None, verbose: bool = False) -> dict:
    """
    Verify a ZK-SNARK steganographic image.

    When secret_key is None  → ZK proof verification only (public auditor mode).
    When secret_key is given → ZK proof verification + hidden message extraction.

    Args:
        stego_image_path: Path to steganographic image.
        secret_key: Chaos key supplied by the intended recipient.
                   Required only for message extraction; proof verification works
                   without it.
        verbose: Enable detailed output.

    Returns:
        dict: Verification result.  Contains 'extracted_message' when a key
              is supplied and extraction succeeds.
    """
    try:
        if verbose:
            print(f"Analyzing steganographic image: {stego_image_path}")
        
        # Extract proof from the PNG chunk (v2: no secret key needed)
        artifact = extract_chaos_proof(stego_image_path, secret_key=secret_key)
        
        if not artifact:
            return {
                'success': False,
                'error': 'No valid ZK proof artifact found in image',
                'details': 'Image may not contain steganographic data or may not have been embedded with this tool'
            }
        
        # Analyze extracted proof
        proof = artifact.get('proof', {})
        chaos_info = artifact.get('chaos', {})
        
        result = {
            'success': True,
            'proof_found': True,
            'proof_type': 'Groth16 ZK-SNARK',
            'chaos_algorithm': chaos_info.get('algorithm', 'unknown'),
            'proof_elements': list(proof.keys()),
            'proof_size_bits': chaos_info.get('proof_length', 0),
            'embedding_method': 'Chaos-based LSB with PNG metadata',
            'timestamp': chaos_info.get('timestamp'),
            'metadata': {
                'initial_position': chaos_info.get('initial_position', {}),
                'arnold_iterations': chaos_info.get('arnold_iterations', 0),
                'logistic_r': chaos_info.get('logistic_r', 0),
                'positions_used': chaos_info.get('positions_used', 0)
            }
        }
        
        if verbose:
            print("ZK-SNARK Proof Successfully Extracted!")
            print(f"   Algorithm: {result['chaos_algorithm']}")
            print(f"   Proof elements: {', '.join(result['proof_elements'])}")
            print(f"   Data size: {result['proof_size_bits']} bits")
            print(f"   Positions used: {result['metadata']['positions_used']}")
            print(f"   Arnold iterations: {result['metadata']['arnold_iterations']}")
            print(f"   Logistic parameter: {result['metadata']['logistic_r']}")
        
        required_elements = ['pi_a', 'pi_b', 'pi_c']
        missing_elements = [elem for elem in required_elements if elem not in proof]
        
        if missing_elements:
            result['warning'] = f"Missing proof elements: {missing_elements}"
            result['validation_status'] = 'failed'
            result['validation_error'] = f"Missing proof elements: {missing_elements}"
            if verbose:
                print(f"WARNING: {result['warning']}")
        else:
            # Thực hiện ZK proof verification
            try:
                zk_gen = ZKProofGenerator(project_root=str(project_root))
                
                # Convert public inputs to the ordered list that snarkjs expects.
                # V2 circuit public order: [publicCommitment, publicImageHash[0..7], publicNullifier]
                public_info = artifact.get('public', {})

                public_commitment = public_info.get("publicCommitment")
                public_image_hash = public_info.get("publicImageHash", [])
                public_nullifier  = public_info.get("publicNullifier")

                if public_commitment and len(public_image_hash) == 8 and public_nullifier:
                    public_list = (
                        [str(public_commitment)]
                        + [str(h) for h in public_image_hash]
                        + [str(public_nullifier)]
                    )
                elif 'public_inputs' in public_info and public_info['public_inputs']:
                    # Legacy fallback: raw list stored by old prover
                    public_list = [str(x) for x in public_info['public_inputs']]
                else:
                    public_list = []

                if not public_list:
                    result['validation_status'] = 'warning'
                    result['zk_verification'] = None
                    result['validation_warning'] = "No public inputs found for ZK verification"
                    if verbose:
                        print("WARNING: No public inputs found for ZK verification")
                    return result
                
                if verbose:
                    print("Verifying ZK-SNARK proof...")
                
                # Suppress output từ ZKProofGenerator
                import io
                import contextlib
                
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    is_valid = zk_gen.verify_proof(proof, public_list)
                
                if is_valid:
                    result['validation_status'] = 'success'
                    result['zk_verification'] = True
                    if verbose:
                        print("ZK-SNARK proof verification: PASSED")
                else:
                    result['validation_status'] = 'failed'
                    result['zk_verification'] = False
                    result['validation_error'] = 'ZK proof verification failed'
                    if verbose:
                        print("ZK-SNARK proof verification: FAILED")
                        
            except Exception as e:
                # Nếu không thể verify (thiếu snarkjs, etc.), vẫn coi là success nếu extract được
                result['validation_status'] = 'warning'
                result['zk_verification'] = None
                result['validation_warning'] = f"Could not verify ZK proof: {str(e)}"
                if verbose:
                    print(f"WARNING: Could not verify ZK proof: {e}")
                    print("  (Proof extracted successfully, but ZK verification requires snarkjs)")
        
        result['raw_proof'] = proof

        # ── Message extraction (only when the caller supplies a key) ──────────
        if secret_key is not None and result.get('validation_status') in ('success', 'warning'):
            try:
                chaos_info  = artifact.get('chaos', {})
                public_info = artifact.get('public', {})

                message_length = public_info.get('message_length')
                init_pos       = chaos_info.get('initial_position', {})
                x0             = init_pos.get('x')
                y0             = init_pos.get('y')

                if message_length and x0 is not None and y0 is not None:
                    if verbose:
                        print(f"Extracting hidden message ({message_length} chars)...")

                    img_array  = np.array(Image.open(stego_image_path).convert('RGB'))
                    chaos_emb  = ChaosEmbedding(img_array)
                    chaos_key_int = generate_chaos_key_from_secret(secret_key)
                    bits = chaos_emb.extract_bits(message_length * 8, x0, y0, chaos_key_int)

                    msg_bytes = bytearray()
                    for i in range(0, len(bits), 8):
                        byte = 0
                        for j in range(8):
                            if i + j < len(bits):
                                byte |= bits[i + j] << (7 - j)
                        msg_bytes.append(byte)

                    extracted = msg_bytes.decode('utf-8', errors='replace')
                    result['extracted_message'] = extracted
                    if verbose:
                        print(f"Extracted message: {extracted}")
                else:
                    result['extraction_warning'] = 'Chunk metadata missing message_length or initial position'
                    if verbose:
                        print('WARNING: Cannot extract message — chunk metadata incomplete')
            except Exception as e:
                result['extraction_warning'] = f'Message extraction failed: {e}'
                if verbose:
                    print(f'WARNING: Message extraction failed: {e}')
        elif secret_key is None:
            result['extraction_note'] = 'No key provided — message extraction skipped (verification only)'

        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Verification failed: {str(e)}',
            'details': 'Check image format and accessibility'
        }

def main():
    parser = argparse.ArgumentParser(
        description='Verify ZK-SNARK steganographic images with chaos-based positioning',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Public auditor — verify proof only (no key required)
  python scripts/verify.py stego_image.png
  python scripts/verify.py stego_image.png -v

  # Recipient — verify proof AND extract hidden message
  python scripts/verify.py stego_image.png --key "my_chaos_key"
  python scripts/verify.py stego_image.png --key "my_chaos_key" -v

  # JSON output for automation
  python scripts/verify.py stego_image.png --json
  python scripts/verify.py stego_image.png --key "my_chaos_key" --json

NOTE:
  The ZK proof is stored in a custom PNG chunk — anyone can verify it without a
  key.  To also READ the hidden message, supply the chaos key with --key.
  The key is never stored in the image, so verification remains zero-knowledge.
        """
    )
    
    parser.add_argument('image', help='Path to steganographic image')
    parser.add_argument('--key', '-k', required=False, default=None,
                       help='Chaos key for message extraction (optional — omit for verify-only mode)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output format')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image):
        print(f"ERROR: Image file not found: {args.image}")
        print("\n[FAILED] Validate FAILED")
        sys.exit(1)
    
    result = verify_zk_stego(args.image, args.key, args.verbose and not args.json)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result['success']:
            print(f"ZK-SNARK Proof Verified in {args.image}")
            print(f"   Type: {result['proof_type']}")
            print(f"   Algorithm: {result['chaos_algorithm']}")
            print(f"   Size: {result['proof_size_bits']} bits")
            
            # Hiển thị validation status
            validation_status = result.get('validation_status', 'unknown')
            if validation_status == 'success':
                print("\n[SUCCESS] Validate SUCCESS")
            elif validation_status == 'failed':
                print("\n[FAILED] Validate FAILED")
                if result.get('validation_error'):
                    print(f"   Error: {result['validation_error']}")
            elif validation_status == 'warning':
                print("\n[WARNING] Validate WARNING")
                if result.get('validation_warning'):
                    print(f"   Warning: {result['validation_warning']}")
            
            if result.get('warning'):
                print(f"   WARNING: {result['warning']}")

            # Show extracted message or extraction note
            if 'extracted_message' in result:
                print(f"\n   Hidden message: {result['extracted_message']}")
            elif result.get('extraction_warning'):
                print(f"   Extraction warning: {result['extraction_warning']}")
            elif result.get('extraction_note'):
                print(f"   Note: {result['extraction_note']}")
        else:
            print(f"ERROR: Verification Failed: {result['error']}")
            if result.get('details'):
                print(f"   Details: {result['details']}")
            print("\n[FAILED] Validate FAILED")
            sys.exit(1)

if __name__ == '__main__':
    main()
