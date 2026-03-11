"""
ZK-SNARK Steganography - Prover Module
Handles message embedding and ZK proof generation
"""

import json
import time
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from .utils import (
    ChaosGenerator,
    LSBProcessor,
    PNGChunkHandler,
    SnarkJSRunner,
    generate_chaos_key_from_secret,
    generate_random_chaos_key,
    compute_image_hash,
    compute_file_hash,
    extract_feature_point,
    message_to_bits,
    bytes_to_bits,
    hash_to_field_elements,
)


class Prover:
    """
    ZK-SNARK Steganography Prover
    
    Handles:
    - Message embedding into cover image using chaos-based LSB
    - ZK proof generation for proving correct embedding
    - PNG chunk metadata embedding
    
    Usage:
        prover = Prover()
        result = prover.embed_and_prove(
            cover_image_path="cover.png",
            output_path="stego.png", 
            message="Secret message",
            chaos_key="my_secret_key"
        )
    """
    
    def __init__(self, project_root: Optional[str] = None):
        """
        Initialize Prover
        
        Args:
            project_root: Optional path to project root (for finding circuit files)
        """
        self.snarkjs = SnarkJSRunner(project_root)
        self.chunk_handler = PNGChunkHandler()
    
    # =========================================================================
    # HIGH-LEVEL API
    # =========================================================================
    
    def embed_and_prove(
        self,
        cover_image_path: str,
        output_path: str,
        message: str,
        chaos_key: Optional[str] = None,
        x0: Optional[int] = None,
        y0: Optional[int] = None,
        generate_zk_proof: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Complete embedding workflow: embed message + generate ZK proof
        
        Args:
            cover_image_path: Path to cover image (PNG)
            output_path: Path for output stego image
            message: Message to embed (private input)
            chaos_key: Secret key for chaos generation (private input)
                      If None, generates a new random key
            x0, y0: Optional starting position (auto-detected if None)
            generate_zk_proof: Whether to generate ZK proof (default True)
            
        Returns:
            Dict containing:
            - stego_image_path: Path to stego image
            - chaos_key: The chaos key used (SAVE THIS!)
            - proof: ZK proof (if generated)
            - public_inputs: Public inputs for verification
            - metadata: Embedding metadata
        """
        print("=" * 60)
        print("ZK-SNARK Steganography Prover")
        print("=" * 60)
        
        # Load cover image
        cover_img = Image.open(cover_image_path)
        cover_array = np.array(cover_img)
        print(f"Cover image: {cover_image_path}")
        print(f"Image size: {cover_array.shape}")
        
        # Generate or use provided chaos_key
        if chaos_key is None:
            chaos_key = generate_random_chaos_key()
            print(f"Generated new chaos_key: {chaos_key[:16]}... (SAVE THIS!)")
        else:
            print(f"Using provided chaos_key: {chaos_key[:16]}...")
        
        chaos_key_int = generate_chaos_key_from_secret(chaos_key)
        
        # Extract feature point for starting position
        if x0 is None or y0 is None:
            x0, y0 = extract_feature_point(cover_array)
            print(f"Auto-detected starting position: ({x0}, {y0})")
        else:
            print(f"Using provided starting position: ({x0}, {y0})")
        
        # Convert message to bits
        message_bits = message_to_bits(message)
        print(f"Message length: {len(message)} chars, {len(message_bits)} bits")
        
        # Embed message into image
        print("\nEmbedding message...")
        lsb = LSBProcessor(cover_array)
        stego_array = lsb.embed_bits(message_bits, x0, y0, chaos_key_int)
        
        # Save stego image
        stego_img = Image.fromarray(stego_array.astype(np.uint8))
        stego_img.save(output_path)
        print(f"Stego image saved: {output_path}")
        
        # Prepare result
        result = {
            "stego_image_path": output_path,
            "chaos_key": chaos_key,
            "x0": x0,
            "y0": y0,
            "message_length": len(message),
            "message_bits": len(message_bits),
            "timestamp": int(time.time()),
            "proof": None,
            "public_inputs": None,
        }
        
        # Generate ZK proof if requested
        if generate_zk_proof:
            print("\nGenerating ZK proof...")
            proof_result = self._generate_zk_proof(
                cover_array, message, chaos_key, x0, y0
            )
            
            if proof_result:
                result["proof"] = proof_result["proof"]
                result["public_inputs"] = proof_result["public_inputs"]
                result["witness_input"] = proof_result["witness_input"]
                print("ZK proof generated successfully!")
            else:
                print("WARNING: ZK proof generation failed, continuing without proof")
        
        # Create and embed metadata chunk
        print("\nEmbedding metadata chunk...")
        chaos_metadata = self._create_chaos_metadata(
            x0, y0, chaos_key_int, len(message_bits)
        )

        chunk_metadata = {
            "chaos": chaos_metadata,
            "public": {
                "image_hash": compute_file_hash(cover_image_path),
                "message_length": len(message),
                "proof_length": len(message_bits),
                "timestamp": result["timestamp"],
            },
            "meta": {
                "version": "2.0",
                "algorithm": "chaos_lsb_zksnark_v2",
            },
            "timestamp": result["timestamp"],
        }

        if result["public_inputs"]:
            # Store the three v2 public inputs by name for clarity
            pi = result["public_inputs"]
            chunk_metadata["public"]["public_inputs"] = pi
            # v2 public order from circuit: [publicCommitment, publicImageHash[8]..., publicNullifier]
            if len(pi) >= 10:
                chunk_metadata["public"]["publicCommitment"] = pi[0]
                chunk_metadata["public"]["publicImageHash"]  = pi[1:9]
                chunk_metadata["public"]["publicNullifier"]  = pi[9]

        if result["proof"]:
            chunk_metadata["proof"] = result["proof"]
        
        success = PNGChunkHandler.embed_metadata(output_path, chunk_metadata)
        if success:
            print("Metadata chunk embedded successfully!")
            result["metadata"] = chunk_metadata
        else:
            print("WARNING: Failed to embed metadata chunk")
        
        print("\n" + "=" * 60)
        print("Embedding complete!")
        print(f"Output: {output_path}")
        print(f"Chaos key (SAVE THIS!): {chaos_key}")
        print("=" * 60)
        
        return result
    
    def embed_only(
        self,
        cover_image_path: str,
        output_path: str,
        message: str,
        chaos_key: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Embed message without generating ZK proof (faster)
        
        Args:
            cover_image_path: Path to cover image
            output_path: Path for output stego image
            message: Message to embed
            chaos_key: Secret key for chaos generation
            x0, y0: Optional starting position
            
        Returns:
            Embedding result dict
        """
        return self.embed_and_prove(
            cover_image_path=cover_image_path,
            output_path=output_path,
            message=message,
            chaos_key=chaos_key,
            x0=x0,
            y0=y0,
            generate_zk_proof=False
        )
    
    def generate_proof_only(
        self,
        cover_image_path: str,
        message: str,
        chaos_key: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate ZK proof without embedding (for pre-embedded images)
        
        Args:
            cover_image_path: Path to original cover image
            message: Message that was embedded
            chaos_key: Chaos key that was used
            x0, y0: Starting position that was used
            
        Returns:
            Proof package dict
        """
        cover_img = Image.open(cover_image_path)
        cover_array = np.array(cover_img)
        
        if x0 is None or y0 is None:
            x0, y0 = extract_feature_point(cover_array)
        
        return self._generate_zk_proof(cover_array, message, chaos_key, x0, y0)
    
    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================
    
    def _create_chaos_metadata(
        self, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        proof_length: int
    ) -> Dict[str, Any]:
        """Create metadata for PNG chunk"""
        import hashlib
        chaos_key_hash = hashlib.sha256(str(chaos_key).encode()).hexdigest()[:16]
        
        return {
            "initial_position": {"x": x0, "y": y0},
            "chaos_key_hash": chaos_key_hash,
            "proof_length": proof_length,
            "algorithm": "arnold_cat_logistic",
            "version": "2.0"
        }
    
    def _generate_zk_proof(
        self,
        image_array: np.ndarray,
        message: str,
        chaos_key: str,
        x0: int,
        y0: int
    ) -> Optional[Dict[str, Any]]:
        """Generate ZK proof for embedding"""
        try:
            # Setup trusted setup if needed
            if not self.snarkjs.setup_trusted_setup():
                return None
            
            # Extract chaos parameters
            chaos_params = self._extract_chaos_parameters(
                image_array, message, chaos_key, x0, y0
            )
            
            # Create witness input
            witness_input = self._create_witness_input(chaos_params)
            
            # Generate witness
            witness_file = self.snarkjs.generate_witness(witness_input)
            if not witness_file:
                return None
            
            # Generate proof
            proof_result = self.snarkjs.generate_groth16_proof(witness_file)
            if not proof_result:
                return None
            
            proof, public_inputs = proof_result
            
            return {
                "proof": proof,
                "public_inputs": public_inputs,
                "chaos_parameters": chaos_params,
                "witness_input": witness_input,
            }
            
        except Exception as e:
            print(f"ERROR: ZK proof generation failed: {e}")
            return None
    
    def _extract_chaos_parameters(
        self,
        image_array: np.ndarray,
        message: str,
        chaos_key: str,
        x0: int,
        y0: int
    ) -> Dict[str, Any]:
        """
        Compute all witness parameters for the v2 SecureChaosZKStego circuit.

        Uses the real circomlib Poseidon hash (via poseidon_helper.js / circomlibjs)
        so every value exactly matches what the Groth16 circuit verifier checks.

        v2 public outputs:   publicCommitment, publicImageHash[8], publicNullifier
        v2 private inputs:   messageBits[32], chaosKey, randomness, secret, nonce,
                             x0, y0, positions[16][2], imageHashPrivate[8]
        """
        import hashlib
        from .poseidon import compute_all_zk_params

        BN254_P = 21888242871839275222246405745257275088548364400416034343698204186575808495617

        # chaos key as a BN254 field element
        chaos_key_int = generate_chaos_key_from_secret(chaos_key)

        # image hash: SHA-256 → 8 × 32-bit field elements
        image_hash_hex      = compute_image_hash(image_array)
        image_hash_elements = hash_to_field_elements(image_hash_hex, n_elements=8)

        # message bits: first 4 bytes → 32 bits, zero-padded
        message_bytes = message.encode('utf-8')[:4]
        message_bits  = []
        for byte in message_bytes:
            for i in range(7, -1, -1):
                message_bits.append((byte >> i) & 1)
        message_bits = (message_bits + [0] * 32)[:32]

        # randomness / secret / nonce – deterministic from chaos_key
        randomness = int(hashlib.sha256(f"randomness:{chaos_key}".encode()).hexdigest(), 16) % BN254_P
        secret     = int(hashlib.sha256(f"secret:{chaos_key}".encode()).hexdigest(), 16)     % BN254_P
        nonce      = int(hashlib.sha256(f"nonce:{chaos_key}".encode()).hexdigest(), 16)       % BN254_P

        # all Poseidon-based values computed in one Node.js call
        print("  Computing Poseidon hashes (circomlibjs)...")
        zk_params = compute_all_zk_params(
            x0, y0, chaos_key_int, randomness, secret, nonce, message_bits
        )

        return {
            "x0": x0,
            "y0": y0,
            "chaos_key": chaos_key,
            "chaos_key_int": chaos_key_int,
            "image_hash_elements": image_hash_elements,
            "message_bits": message_bits,
            "positions": zk_params["positions"],
            "randomness": randomness,
            "secret": secret,
            "nonce": nonce,
            "public_commitment": zk_params["public_commitment"],
            "public_nullifier": zk_params["public_nullifier"],
            "proof_length": len(message),
            "timestamp": int(time.time()),
        }

    def _create_witness_input(self, chaos_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create witness input JSON for the v2 SecureChaosZKStego circuit.

        Signal mapping (matches component main declaration):
            PUBLIC  publicCommitment         → single integer
            PUBLIC  publicImageHash[8]       → array of 8 integers
            PUBLIC  publicNullifier          → single integer
            PRIVATE messageBits[32]          → array of 32 bits (0/1)
            PRIVATE chaosKey                 → single integer
            PRIVATE randomness               → single integer
            PRIVATE secret                   → single integer
            PRIVATE nonce                    → single integer
            PRIVATE x0                       → single integer
            PRIVATE y0                       → single integer
            PRIVATE positions[16][2]         → 16 pairs of integers
            PRIVATE imageHashPrivate[8]      → array of 8 integers
        """
        return {
            # Public inputs
            "publicCommitment":  str(chaos_params["public_commitment"]),
            "publicImageHash":   [str(e) for e in chaos_params["image_hash_elements"]],
            "publicNullifier":   str(chaos_params["public_nullifier"]),
            # Private inputs
            "messageBits":       [str(b) for b in chaos_params["message_bits"]],
            "chaosKey":          str(chaos_params["chaos_key_int"]),
            "randomness":        str(chaos_params["randomness"]),
            "secret":            str(chaos_params["secret"]),
            "nonce":             str(chaos_params["nonce"]),
            "x0":                str(chaos_params["x0"]),
            "y0":                str(chaos_params["y0"]),
            "positions":         [[str(p[0]), str(p[1])] for p in chaos_params["positions"]],
            "imageHashPrivate":  [str(e) for e in chaos_params["image_hash_elements"]],
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def embed(
    cover_image: str,
    output_path: str,
    message: str,
    chaos_key: Optional[str] = None,
    with_proof: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to embed message into image
    
    Args:
        cover_image: Path to cover image
        output_path: Path for stego image
        message: Message to embed
        chaos_key: Secret key (auto-generated if None)
        with_proof: Generate ZK proof (default True)
        
    Returns:
        Result dict with chaos_key, proof, etc.
    """
    prover = Prover()
    return prover.embed_and_prove(
        cover_image_path=cover_image,
        output_path=output_path,
        message=message,
        chaos_key=chaos_key,
        generate_zk_proof=with_proof
    )

