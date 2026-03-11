"""
ZK-SNARK Steganography — Verifier Package

Extraction and verification only. No embedding, no prover.
"""

# DICOM steganography (extract + verify)
from .dicom_handler import DicomHandler, DicomStego

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
    "DicomHandler",
    "DicomStego",
    "SnarkJSRunner",
    "generate_chaos_key_from_secret",
]
