"""
ZK-SNARK Steganography Core Module

A clean, modular implementation of ZK-SNARK based steganography
using chaos theory (Arnold Cat Map + Logistic Map) for position generation.

Structure:
    - prover.py   : Embed message + generate ZK proof
    - poseidon.py : Circomlib-compatible BN254 Poseidon hash (via Node.js)
    - utils.py    : Helper functions (chaos, LSB, PNG chunks, snarkjs)

Note: Verification is handled by the verifier_package (see verifier_package/).

Quick Start:
    # Prover (embed message)
    from zk_stego import Prover

    prover = Prover()
    result = prover.embed_and_prove(
        cover_image_path="cover.png",
        output_path="stego.png",
        message="Secret message",
        chaos_key="my_secret_key"
    )

Convenience Functions:
    from zk_stego import embed

    # Embed
    result = embed("cover.png", "stego.png", "Hello", "secret_key")
"""

# Main classes
from .prover import Prover

# Convenience functions
from .prover import embed

# Utility classes (for advanced usage)
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
    bits_to_bytes,
    bytes_to_bits,
)

__version__ = "2.0.0"
__all__ = [
    # Main class
    "Prover",

    # Convenience function
    "embed",

    # Utility classes
    "ChaosGenerator",
    "LSBProcessor",
    "PNGChunkHandler",
    "SnarkJSRunner",
    
    # Utility functions
    "generate_chaos_key_from_secret",
    "generate_random_chaos_key",
    "compute_image_hash",
    "compute_file_hash",
    "extract_feature_point",
    "message_to_bits",
    "bits_to_bytes",
    "bytes_to_bits",
]
