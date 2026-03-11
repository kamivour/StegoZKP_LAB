"""
Chaos-based Steganography with Arnold Cat Map and Logistic Map
Generates pseudo-random positions for LSB embedding using chaotic systems
"""

import numpy as np
from typing import List, Tuple, Optional
import hashlib

class ChaosGenerator:
    """Arnold Cat Map + Logistic Map for position generation"""
    
    def __init__(self, image_width: int, image_height: int):
        self.width = image_width
        self.height = image_height
        
    def get_arnold_matrix(self) -> np.ndarray:
        """Return the Arnold Cat Map transformation matrix"""
        return np.array([[2, 1], 
                        [1, 1]], dtype=int)
    
    def arnold_cat_map_matrix(self, x: int, y: int, iterations: int) -> Tuple[int, int]:
        """Arnold Cat Map using explicit matrix multiplication"""
        arnold_matrix = self.get_arnold_matrix()
        
        for _ in range(iterations):
            position_vector = np.array([x, y])
            new_position = arnold_matrix @ position_vector
            
            x = new_position[0] % self.width
            y = new_position[1] % self.height
            
        return x, y
        
    def arnold_cat_map(self, x: int, y: int, iterations: int) -> Tuple[int, int]:
        """Arnold Cat Map transformation using standard matrix form"""
        for _ in range(iterations):
            x_new = (2 * x + y) % self.width
            y_new = (x + y) % self.height
            x, y = x_new, y_new
        return x, y
    
    def logistic_map(self, x0: float, r: float, n: int) -> List[float]:
        """Logistic Map sequence generation"""
        sequence = []
        x = x0
        for _ in range(n):
            x = r * x * (1 - x)
            sequence.append(x)
        return sequence
    
    def generate_positions(
        self, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        num_positions: int
    ) -> List[Tuple[int, int]]:
        """Generate chaos-based embedding positions (ensuring uniqueness)"""
        
        r = 3.57 + (chaos_key % 4300) / 10000  # r ∈ [3.57, 4.0) - full chaotic regime
        logistic_x0 = (chaos_key % 10000) / 10000
        arnold_iterations = (chaos_key // 10000) % 10 + 1
        
        positions = []
        used_positions = set()
        
        if (x0, y0) not in used_positions:
            positions.append((x0, y0))
            used_positions.add((x0, y0))
        
        logistic_seq = self.logistic_map(logistic_x0, r, num_positions * 4)
        
        current_x, current_y = x0, y0
        logistic_idx = 0
        
        while len(positions) < num_positions and logistic_idx < len(logistic_seq) - 1:
            current_x, current_y = self.arnold_cat_map(
                current_x, current_y, arnold_iterations
            )
            
            dx = int(logistic_seq[logistic_idx] * 10) - 5
            dy = int(logistic_seq[logistic_idx + 1] * 10) - 5
            logistic_idx += 2
            
            final_x = (current_x + dx) % self.width
            final_y = (current_y + dy) % self.height
            
            pos = (final_x, final_y)
            if pos not in used_positions:
                positions.append(pos)
                used_positions.add(pos)
            
        if len(positions) < num_positions:
            for y in range(self.height):
                for x in range(self.width):
                    if len(positions) >= num_positions:
                        break
                    pos = (x, y)
                    if pos not in used_positions:
                        positions.append(pos)
                        used_positions.add(pos)
                if len(positions) >= num_positions:
                    break
            
        return positions[:num_positions]
    
    def verify_chaos_sequence(
        self,
        positions: List[Tuple[int, int]],
        x0: int,
        y0: int, 
        chaos_key: int
    ) -> bool:
        """Verify that positions were generated with given parameters"""
        expected_positions = self.generate_positions(x0, y0, chaos_key, len(positions))
        return positions == expected_positions

class ChaosEmbedding:
    """LSB embedding using chaos-generated positions"""
    
    def __init__(self, image_array: np.ndarray):
        self.image = image_array.copy()
        self.height, self.width = image_array.shape[:2]
        self.chaos_gen = ChaosGenerator(self.width, self.height)
    
    def embed_message(self, message: str, secret_key: str = "default_key") -> 'PIL.Image.Image':
        """High-level method to embed a text message"""
        from PIL import Image
        
        message_bytes = message.encode('utf-8')
        bits = []
        for byte in message_bytes:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)
        
        chaos_key = generate_chaos_key_from_secret(secret_key)
        
        x0 = self.width // 2
        y0 = self.height // 2
        
        stego_array = self.embed_bits(bits, x0, y0, chaos_key)
        
        return Image.fromarray(stego_array.astype('uint8'))
    
    def extract_message(self, message_length: int, secret_key: str = "default_key") -> str:
        """High-level method to extract a text message"""
        chaos_key = generate_chaos_key_from_secret(secret_key)
        
        x0 = self.width // 2
        y0 = self.height // 2
        
        num_bits = message_length * 8
        
        bits = self.extract_bits(num_bits, x0, y0, chaos_key)
        
        message_bytes = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(bits):
                    byte |= bits[i + j] << (7 - j)
            message_bytes.append(byte)
        
        return message_bytes.decode('utf-8', errors='ignore')
    
    def embed_bits(
        self, 
        bits: List[int], 
        x0: int, 
        y0: int, 
        chaos_key: int,
        channel: int = 0
    ) -> np.ndarray:
        """Embed bits using chaos-based positioning"""
        
        positions = self.chaos_gen.generate_positions(x0, y0, chaos_key, len(bits))
        
        if len(positions) < len(bits):
            raise ValueError(f"Not enough positions: need {len(bits)}, got {len(positions)}")
        
        is_grayscale = len(self.image.shape) == 2
        
        for i, bit in enumerate(bits):
            x, y = positions[i]
            if 0 <= x < self.width and 0 <= y < self.height:
                if is_grayscale:
                    pixel_value = self.image[y, x]
                    self.image[y, x] = (pixel_value & 0xFE) | (bit & 1)
                else:
                    ch = channel % self.image.shape[2]
                    pixel_value = self.image[y, x, ch]
                    self.image[y, x, ch] = (pixel_value & 0xFE) | (bit & 1)
            
        return self.image
    
    def extract_bits(
        self, 
        num_bits: int, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        channel: int = 0
    ) -> List[int]:
        """Extract bits using chaos-based positioning"""
        
        positions = self.chaos_gen.generate_positions(x0, y0, chaos_key, num_bits)
        is_grayscale = len(self.image.shape) == 2
        
        bits = []
        for i in range(num_bits):
            if i < len(positions):
                x, y = positions[i]
                if 0 <= x < self.width and 0 <= y < self.height:
                    if is_grayscale:
                        lsb = self.image[y, x] & 1
                    else:
                        ch = channel % self.image.shape[2]
                        lsb = self.image[y, x, ch] & 1
                    bits.append(lsb)
                else:
                    bits.append(0)
            else:
                bits.append(0)
                
        return bits
    
    def calculate_capacity(self) -> int:
        """Calculate maximum embedding capacity"""
        if len(self.image.shape) == 3:
            return self.width * self.height * self.image.shape[2]
        else:
            return self.width * self.height

class ChaosProofArtifact:
    """Hybrid: PNG Chunk + Chaos-based LSB embedding"""
    
    def __init__(self):
        self.chunk_type = b'zkPF'
        
    def create_chaos_metadata(
        self, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        proof_length: int
    ) -> dict:
        """Create metadata for PNG chunk (chaos_key NOT stored - must be transmitted securely)"""
        # Hash chaos_key for verification (user must provide correct key to extract)
        chaos_key_hash = hashlib.sha256(str(chaos_key).encode()).hexdigest()[:16]
        return {
            "initial_position": {"x": x0, "y": y0},
            "chaos_key_hash": chaos_key_hash,  # Only store hash, not the actual key
            "proof_length": proof_length,
            "algorithm": "arnold_cat_logistic",
            "version": "2.0"  # Version bump for security update
        }
    
    def embed_proof_chaos(
        self,
        cover_image: np.ndarray,
        proof_data: bytes,
        x0: int,
        y0: int,
        chaos_key: int
    ) -> Tuple[np.ndarray, dict]:
        """Embed proof using chaos-based LSB + metadata in PNG chunk"""
        
        proof_bits = []
        for byte in proof_data:
            for i in range(7, -1, -1):
                proof_bits.append((byte >> i) & 1)
        
        chaos_embed = ChaosEmbedding(cover_image)
        
        capacity = chaos_embed.calculate_capacity()
        if len(proof_bits) > capacity:
            raise ValueError(f"Proof too large: {len(proof_bits)} bits > {capacity} capacity")
        
        stego_image = chaos_embed.embed_bits(proof_bits, x0, y0, chaos_key)
        
        metadata = self.create_chaos_metadata(x0, y0, chaos_key, len(proof_bits))
        
        return stego_image, metadata
    
    def extract_proof_chaos(
        self,
        stego_image: np.ndarray,
        metadata: dict,
        chaos_key: int = None
    ) -> bytes:
        """Extract proof using chaos-based positioning
        
        Args:
            stego_image: The steganographic image array
            metadata: Metadata from PNG chunk
            chaos_key: The chaos key (MUST be provided by user via secure channel)
            
        Returns:
            Extracted proof bytes, or None if key verification fails
        """
        x0 = metadata["initial_position"]["x"]
        y0 = metadata["initial_position"]["y"]
        proof_length = metadata["proof_length"]
        
        # Handle backward compatibility: old version stored chaos_key directly
        if "chaos_key" in metadata:
            # Old format (version 1.0) - use stored key (deprecated, insecure)
            if chaos_key is None:
                chaos_key = metadata["chaos_key"]
                print("WARNING: Using legacy insecure format with stored chaos_key")
        elif chaos_key is None:
            raise ValueError("chaos_key is required for extraction (must be transmitted via secure channel)")
        
        # Verify chaos_key hash if available (version 2.0+)
        if "chaos_key_hash" in metadata:
            expected_hash = metadata["chaos_key_hash"]
            actual_hash = hashlib.sha256(str(chaos_key).encode()).hexdigest()[:16]
            if expected_hash != actual_hash:
                raise ValueError("Invalid chaos_key: hash verification failed. Please check your secret key.")
        
        chaos_extract = ChaosEmbedding(stego_image)
        proof_bits = chaos_extract.extract_bits(proof_length, x0, y0, chaos_key)
        
        proof_bytes = bytearray()
        for i in range(0, len(proof_bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(proof_bits):
                    byte |= proof_bits[i + j] << (7 - j)
            proof_bytes.append(byte)
        
        return bytes(proof_bytes)

def generate_chaos_key_from_secret(secret: str) -> int:
    """Generate deterministic chaos key from secret string (64-bit)"""
    hash_obj = hashlib.sha256(secret.encode())
    return int(hash_obj.hexdigest()[:16], 16)  # 64-bit key

def validate_chaos_parameters(x0: int, y0: int, width: int, height: int) -> bool:
    """Validate initial position is within image bounds"""
    return 0 <= x0 < width and 0 <= y0 < height
