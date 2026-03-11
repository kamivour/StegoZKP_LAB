"""
Hybrid ZK-SNARK Steganography: PNG Chunk + Chaos-based LSB Embedding
Combines robust PNG chunk metadata with chaos-based position generation
"""

import json
import hashlib
import struct
import zlib
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional, Tuple, List
import time

from .chaos_embedding import ChaosProofArtifact, generate_chaos_key_from_secret, ChaosEmbedding

class HybridProofArtifact:
    """Hybrid approach: PNG chunk metadata + Chaos-based LSB embedding"""
    
    def __init__(self, image=None):
        """
        Initialize HybridProofArtifact
        
        Args:
            image: Optional PIL Image or numpy array to process
        """
        self.chaos_artifact = ChaosProofArtifact()
        self.chunk_type = b'zkPF'
        self._zk_generator = None
        self.image = image
        
    @property
    def zk_generator(self):
        """Lazy loading of ZK generator to avoid circular imports"""
        if self._zk_generator is None:
            from .zk_proof_generator import ZKProofGenerator
            self._zk_generator = ZKProofGenerator()
        return self._zk_generator
        
    def generate_proof(self, image_array: np.ndarray, message: str) -> Optional[Dict[str, Any]]:
        """
        Generate ZK proof for steganographic embedding
        
        Args:
            image_array: Input image as numpy array
            message: Message to prove embedding for
            
        Returns:
            Complete ZK proof package or None if failed
        """
        print("Generating ZK proof for steganographic data...")
        
        try:
            proof_package = self.zk_generator.generate_complete_proof(image_array, message)
            
            if proof_package:
                print("ZK proof generation completed successfully")
                print(f"Proof size: {len(json.dumps(proof_package['proof']))} bytes")
                print(f"Public inputs: {len(proof_package['public_inputs'])} elements")
                print(f"Generation timestamp: {proof_package['generation_timestamp']}")
                
            return proof_package
            
        except Exception as e:
            print(f"ERROR: Error generating ZK proof: {e}")
            return None
    
    def verify_proof(self, proof_package: Dict[str, Any]) -> bool:
        """
        Verify ZK proof package
        
        Args:
            proof_package: Complete proof package from generate_proof
            
        Returns:
            True if proof is valid, False otherwise
        """
        print("Verifying ZK proof...")
        
        try:
            proof = proof_package.get("proof")
            public_inputs = proof_package.get("public_inputs")
            
            if not proof or not public_inputs:
                print("ERROR: Invalid proof package structure")
                return False
                
            is_valid = self.zk_generator.verify_proof(proof, public_inputs)
            
            if is_valid:
                print("ZK proof verification PASSED")
            else:
                print("ERROR: ZK proof verification FAILED")
                
            return is_valid
            
        except Exception as e:
            print(f"ERROR: Error verifying ZK proof: {e}")
            return False
    
    def embed_with_proof(
        self,
        image_array: np.ndarray,
        message: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None,
        chaos_key: str = "default_key"
    ) -> Optional[Tuple[Image.Image, Dict[str, Any]]]:
        """
        High-level method to embed message with ZK proof
        
        Args:
            image_array: Input image as numpy array
            message: Message to embed
            x0: Optional starting X position
            y0: Optional starting Y position
            chaos_key: Secret key for chaos parameters
            
        Returns:
            Tuple of (stego_image, proof_package) or None if failed
        """
        try:
            if x0 is None or y0 is None:
                x0, y0 = self.extract_image_feature_point(image_array)
                print(f"Extracted feature-based starting point: ({x0}, {y0})")
            
            proof_package = self.generate_proof(image_array, message)
            if not proof_package:
                print("WARNING: Failed to generate ZK proof, continuing with embedding only...")
            
            chaos_embed = ChaosEmbedding(image_array)
            chaos_key_int = generate_chaos_key_from_secret(chaos_key)
            
            message_bytes = message.encode('utf-8')
            bits = []
            for byte in message_bytes:
                for i in range(7, -1, -1):
                    bits.append((byte >> i) & 1)
            
            stego_array = chaos_embed.embed_bits(bits, x0, y0, chaos_key_int)
            stego_image = Image.fromarray(stego_array.astype(np.uint8))
            
            return stego_image, proof_package
            
        except Exception as e:
            print(f"ERROR: Error in embed_with_proof: {e}")
            return None
        
    def extract_image_feature_point(self, image_array: np.ndarray) -> Tuple[int, int]:
        """Extract distinctive features from image to determine starting point"""
        height, width = image_array.shape[:2]
        
        if len(image_array.shape) == 3:
            gray = np.mean(image_array, axis=2).astype(np.uint8)
        else:
            gray = image_array
            
        grad_x = np.abs(np.diff(gray, axis=1))
        grad_y = np.abs(np.diff(gray, axis=0))
        
        grad_x = np.pad(grad_x, ((0, 0), (0, 1)), mode='edge')
        grad_y = np.pad(grad_y, ((0, 1), (0, 0)), mode='edge')
        
        gradient_mag = grad_x + grad_y
        
        window_size = min(16, width//4, height//4)
        max_texture = 0
        best_x, best_y = width//2, height//2
        
        for y in range(window_size//2, height - window_size//2, window_size//4):
            for x in range(window_size//2, width - window_size//2, window_size//4):
                window = gradient_mag[y-window_size//2:y+window_size//2, 
                                    x-window_size//2:x+window_size//2]
                texture_score = np.sum(window)
                
                if texture_score > max_texture:
                    max_texture = texture_score
                    best_x, best_y = x, y
        
        best_x = max(1, min(best_x, width-2))
        best_y = max(1, min(best_y, height-2))
        
        return best_x, best_y
        
    def embed_hybrid_proof(
        self,
        cover_image_path: str,
        stego_image_path: str,
        proof_json: Dict[str, Any],
        public_json: Dict[str, Any],
        secret_key: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None
    ) -> bool:
        """Embed ZK proof using hybrid approach"""
        try:
            cover_img = Image.open(cover_image_path)
            cover_array = np.array(cover_img)
            
            chaos_key = generate_chaos_key_from_secret(secret_key)
            
            if x0 is None or y0 is None:
                feature_x, feature_y = self.extract_image_feature_point(cover_array)
                x0 = feature_x if x0 is None else x0
                y0 = feature_y if y0 is None else y0
                print(f"Extracted feature-based starting point: ({x0}, {y0})")
            else:
                print(f"Using provided starting point: ({x0}, {y0})")
                
            proof_bytes = json.dumps(proof_json, separators=(',', ':')).encode('utf-8')
            
            stego_array, chaos_metadata = self.chaos_artifact.embed_proof_chaos(
                cover_array, proof_bytes, x0, y0, chaos_key
            )
            
            chaos_metadata["proof_byte_length"] = len(proof_bytes)
            
            image_hash = self._calculate_image_hash(cover_image_path)
            
            chunk_metadata = {
                "chaos": chaos_metadata,
                "public": self._optimize_public_inputs(public_json, image_hash),
                "meta": {
                    "vk_id": "chaos_zk_stego_20241011",
                    "version": "1.0",
                    "domain": "chaos_steganography",
                    "algorithm": "hybrid_png_chaos"
                },
                "timestamp": int(time.time())
            }
            
            stego_img = Image.fromarray(stego_array.astype(np.uint8))
            stego_img.save(stego_image_path)
            
            return self._embed_metadata_chunk(stego_image_path, chunk_metadata)
            
        except Exception as e:
            print(f"Error in hybrid embedding: {e}")
            return False
    
    def extract_hybrid_proof(self, stego_image_path: str, secret_key: str = None) -> Optional[Dict[str, Any]]:
        """Extract ZK proof using hybrid approach
        
        Args:
            stego_image_path: Path to the steganographic image
            secret_key: Secret key for chaos extraction (REQUIRED for version 2.0+)
                       Must be transmitted via secure channel
                       
        Returns:
            Extracted proof artifact or None if extraction fails
        """
        try:
            metadata = self._extract_metadata_chunk(stego_image_path)
            if not metadata:
                print("ERROR: No zkPF metadata chunk found in image.")
                return None

            # In the v2 system the proof (pi_a/pi_b/pi_c) is stored directly
            # inside the PNG chunk under the key "proof".  The LSB pixels hold
            # the embedded *message*, not the proof bytes.
            proof_json = metadata.get("proof")
            if not proof_json:
                print("ERROR: No proof found in PNG chunk metadata.")
                return None

            return {
                "proof":     proof_json,
                "public":    metadata.get("public", {}),
                "meta":      metadata.get("meta", {}),
                "chaos":     metadata.get("chaos", {}),
                "timestamp": metadata.get("timestamp"),
            }

        except Exception as e:
            print(f"Error in hybrid extraction: {e}")
            return None
    
    def _calculate_image_hash(self, image_path: str) -> str:
        """Calculate SHA256 hash of image"""
        with open(image_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    
    def _optimize_public_inputs(self, public_json: Dict[str, Any], image_hash: str) -> Dict[str, Any]:
        """Create optimized public inputs for ZK verification"""
        # If actual public_inputs from snarkjs are provided, use them
        if 'public_inputs' in public_json and public_json['public_inputs']:
            actual_public_inputs = public_json['public_inputs']
            # Extract values from actual public inputs list
            # Format: [commitmentRoot, proofLength, timestamp]
            if len(actual_public_inputs) >= 3:
                return {
                    "image_hash": image_hash,
                    "commitment_root": hex(int(actual_public_inputs[0]))[2:],  # Convert back to hex
                    "proof_length": int(actual_public_inputs[1]),
                    "timestamp": int(actual_public_inputs[2]),
                    "public_inputs": actual_public_inputs  # Store actual for verification
                }
        
        # Fallback to calculating from positions
        chaos_positions = public_json.get('positions', [])
        
        positions_str = ','.join([f"{x},{y}" for x, y in chaos_positions])
        commitment_root = hashlib.sha256(positions_str.encode()).hexdigest()[:16]
        
        return {
            "image_hash": image_hash,
            "commitment_root": commitment_root,
            "proof_length": public_json.get('proof_length', 0),
            "timestamp": int(time.time())
        }
    
    def _embed_metadata_chunk(self, png_path: str, metadata: Dict[str, Any]) -> bool:
        """Embed metadata in PNG chunk"""
        try:
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            metadata_json = json.dumps(metadata, separators=(',', ':'))
            metadata_bytes = metadata_json.encode('utf-8')
            
            iend_pos = png_data.rfind(b'IEND')
            if iend_pos == -1:
                return False
                
            iend_chunk_start = iend_pos - 4
            
            chunk_length = struct.pack('>I', len(metadata_bytes))
            chunk_type = self.chunk_type
            chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + metadata_bytes) & 0xffffffff)
            
            full_chunk = chunk_length + chunk_type + metadata_bytes + chunk_crc
            
            new_png = png_data[:iend_chunk_start] + full_chunk + png_data[iend_chunk_start:]
            
            with open(png_path, 'wb') as f:
                f.write(new_png)
                
            return True
            
        except Exception as e:
            print(f"Error embedding PNG chunk: {e}")
            return False
    
    def _extract_metadata_chunk(self, png_path: str) -> Optional[Dict[str, Any]]:
        """Extract metadata from PNG chunk"""
        try:
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            pos = 8
            
            while pos < len(png_data):
                if pos + 8 > len(png_data):
                    break
                    
                chunk_length = struct.unpack('>I', png_data[pos:pos+4])[0]
                chunk_type = png_data[pos+4:pos+8]
                
                if chunk_type == self.chunk_type:
                    data_start = pos + 8
                    data_end = data_start + chunk_length
                    
                    if data_end + 4 <= len(png_data):
                        chunk_data = png_data[data_start:data_end]
                        
                        expected_crc = struct.unpack('>I', png_data[data_end:data_end+4])[0]
                        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xffffffff
                        
                        if expected_crc == actual_crc:
                            metadata_json = chunk_data.decode('utf-8')
                            return json.loads(metadata_json)
                
                pos += 8 + chunk_length + 4
                
                if chunk_type == b'IEND':
                    break
            
            return None
            
        except Exception as e:
            print(f"Error extracting PNG chunk: {e}")
            return None

def embed_chaos_proof(
    cover_image_path: str,
    stego_image_path: str,
    proof_json_path: str,
    public_json_path: str,
    secret_key: str,
    x0: Optional[int] = None,
    y0: Optional[int] = None
) -> bool:
    """High-level function to embed proof using hybrid chaos approach"""
    
    with open(proof_json_path, 'r') as f:
        proof_json = json.load(f)
        
    with open(public_json_path, 'r') as f:
        public_json = json.load(f)
    
    hybrid = HybridProofArtifact()
    
    return hybrid.embed_hybrid_proof(
        cover_image_path, stego_image_path, 
        proof_json, public_json, secret_key, x0, y0
    )

def extract_chaos_proof(stego_image_path: str, secret_key: str = None) -> Optional[Dict[str, Any]]:
    """Extract the ZK proof artifact from a v2 stego image.

    In the v2 system the proof is stored inside the PNG chunk, so no
    secret_key is needed for extraction.  The argument is kept for
    backwards-compatibility but is no longer used.

    Args:
        stego_image_path: Path to the steganographic image.
        secret_key: Ignored in v2 (proof lives in the PNG chunk).

    Returns:
        Dict with 'proof', 'public', 'meta', 'chaos', 'timestamp', or None.
    """
    hybrid = HybridProofArtifact()
    return hybrid.extract_hybrid_proof(stego_image_path)

def verify_chaos_stego(stego_image_path: str, secret_key: str = None) -> bool:
    """Single-command check that a v2 stego image contains a valid proof structure.

    Args:
        stego_image_path: Path to the steganographic image.
        secret_key: Ignored in v2.
    """
    artifact = extract_chaos_proof(stego_image_path)
    if not artifact:
        return False
    return all(field in artifact for field in ['proof', 'public'])

if __name__ == "__main__":
    print("Hybrid ZK-SNARK Chaos Steganography")
    print("Usage:")
    print("  python3 hybrid_proof_artifact.py embed <cover.png> <stego.png> <proof.json> <public.json> <secret>")
    print("  python3 hybrid_proof_artifact.py extract <stego.png>")
    print("  python3 hybrid_proof_artifact.py verify <stego.png>")
