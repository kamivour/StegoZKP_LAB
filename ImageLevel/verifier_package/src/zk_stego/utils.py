"""
ZK-SNARK Steganography - Utility Functions
Contains helper functions for chaos generation, embedding, and PNG handling
"""

import numpy as np
import hashlib
import json
import struct
import zlib
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image


# =============================================================================
# CHAOS GENERATION
# =============================================================================

class ChaosGenerator:
    """Arnold Cat Map + Logistic Map for position generation"""
    
    def __init__(self, image_width: int, image_height: int):
        self.width = image_width
        self.height = image_height
        
    def get_arnold_matrix(self) -> np.ndarray:
        """Return the Arnold Cat Map transformation matrix"""
        return np.array([[2, 1], 
                        [1, 1]], dtype=int)
    
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
        
        # Derive chaos parameters from chaos_key
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
        
        # Fallback if not enough unique positions
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


# =============================================================================
# LSB EMBEDDING/EXTRACTION
# =============================================================================

class LSBProcessor:
    """LSB embedding/extraction using chaos-generated positions"""
    
    def __init__(self, image_array: np.ndarray):
        self.image = image_array.copy()
        self.height, self.width = image_array.shape[:2]
        self.chaos_gen = ChaosGenerator(self.width, self.height)
    
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


# =============================================================================
# PNG CHUNK HANDLING
# =============================================================================

class PNGChunkHandler:
    """Handle custom PNG chunk (zkPF) for metadata storage"""
    
    CHUNK_TYPE = b'zkPF'
    
    @staticmethod
    def embed_metadata(png_path: str, metadata: Dict[str, Any]) -> bool:
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
            chunk_type = PNGChunkHandler.CHUNK_TYPE
            chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + metadata_bytes) & 0xffffffff)
            
            full_chunk = chunk_length + chunk_type + metadata_bytes + chunk_crc
            
            new_png = png_data[:iend_chunk_start] + full_chunk + png_data[iend_chunk_start:]
            
            with open(png_path, 'wb') as f:
                f.write(new_png)
                
            return True
            
        except Exception as e:
            print(f"Error embedding PNG chunk: {e}")
            return False
    
    @staticmethod
    def extract_metadata(png_path: str) -> Optional[Dict[str, Any]]:
        """Extract metadata from PNG chunk"""
        try:
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            pos = 8  # Skip PNG signature
            
            while pos < len(png_data):
                if pos + 8 > len(png_data):
                    break
                    
                chunk_length = struct.unpack('>I', png_data[pos:pos+4])[0]
                chunk_type = png_data[pos+4:pos+8]
                
                if chunk_type == PNGChunkHandler.CHUNK_TYPE:
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


# =============================================================================
# CRYPTO & HASH UTILITIES
# =============================================================================

def generate_chaos_key_from_secret(secret: str) -> int:
    """Generate deterministic chaos key from secret string (64-bit)"""
    hash_obj = hashlib.sha256(secret.encode())
    return int(hash_obj.hexdigest()[:16], 16)  # 64-bit key


def generate_random_chaos_key() -> str:
    """Generate cryptographically secure random chaos key"""
    return secrets.token_hex(32)  # 256-bit key as hex string


def compute_image_hash(image_array: np.ndarray) -> str:
    """Compute SHA256 hash of image array"""
    return hashlib.sha256(image_array.tobytes()).hexdigest()


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file"""
    with open(file_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def hash_to_field_elements(hash_hex: str, n_elements: int = 8) -> List[int]:
    """Convert SHA256 hash to field elements"""
    hash_bytes = bytes.fromhex(hash_hex)
    elements = []
    bytes_per_element = len(hash_bytes) // n_elements
    
    for i in range(n_elements):
        start = i * bytes_per_element
        end = start + bytes_per_element
        element_bytes = hash_bytes[start:end]
        element_int = int.from_bytes(element_bytes, 'big')
        elements.append(element_int)
    
    return elements


# =============================================================================
# IMAGE UTILITIES
# =============================================================================

def extract_feature_point(image_array: np.ndarray) -> Tuple[int, int]:
    """Extract distinctive feature point from image for starting position"""
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


def message_to_bits(message: str) -> List[int]:
    """Convert message string to bit array"""
    message_bytes = message.encode('utf-8')
    bits = []
    for byte in message_bytes:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def bits_to_bytes(bits: List[int]) -> bytes:
    """Convert bit array to bytes"""
    byte_array = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            if i + j < len(bits):
                byte |= bits[i + j] << (7 - j)
        byte_array.append(byte)
    return bytes(byte_array)


def bytes_to_bits(data: bytes) -> List[int]:
    """Convert bytes to bit array"""
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


# =============================================================================
# SNARKJS COMMAND RUNNER
# =============================================================================

class SnarkJSRunner:
    """Handle snarkjs command execution"""
    
    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            current_file = Path(__file__).resolve()
            self.project_root = current_file.parent.parent.parent
        else:
            self.project_root = Path(project_root)
            
        self.circuit_dir = self.project_root / "circuits"
        self.artifacts_dir = self.project_root / "artifacts"
        self.build_dir = self.circuit_dir / "compiled" / "build"
        
        circuit_name = "chaos_zk_stego"
        
        self.circuit_wasm = self.build_dir / f"{circuit_name}_js" / f"{circuit_name}.wasm"
        self.witness_gen = self.build_dir / f"{circuit_name}_js" / "generate_witness.js"
        # Prefer the larger pot16 file; fall back to pot12 if not present
        _pot16 = self.artifacts_dir / "keys" / "pot16_final.ptau"
        _pot12 = self.artifacts_dir / "keys" / "pot12_final.ptau"
        self.ptau_file = _pot16 if _pot16.exists() else _pot12
        self.circuit_zkey = self.build_dir / f"{circuit_name}.zkey"
        self.verification_key = self.build_dir / f"{circuit_name}_verification_key.json"

    def check_prerequisites(self) -> bool:
        """Check that Node.js and snarkjs are installed before attempting ZK operations."""
        import shutil
        import platform

        ok = True

        # --- Check Node.js ---
        node_path = shutil.which("node")
        if node_path is None:
            print("ERROR: Node.js not found.")
            print("       Please install Node.js from https://nodejs.org")
            print("       After installing, restart your terminal and try again.")
            ok = False
        else:
            try:
                result = subprocess.run(
                    [node_path, "--version"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    print(f"Node.js found: {result.stdout.strip()}")
                else:
                    print("ERROR: Node.js found but --version failed.")
                    ok = False
            except Exception as e:
                print(f"ERROR: Could not run node: {e}")
                ok = False

        # --- Check snarkjs ---
        if platform.system() == "Windows":
            npx_candidates = ["npx.cmd", "npx"]
        else:
            npx_candidates = ["npx"]

        npx_path = None
        for candidate in npx_candidates:
            npx_path = shutil.which(candidate)
            if npx_path:
                break

        if npx_path is None:
            print("ERROR: npx not found (comes with Node.js).")
            print("       Re-install Node.js from https://nodejs.org")
            ok = False
        else:
            try:
                result = subprocess.run(
                    [npx_path, "snarkjs", "--version"],
                    capture_output=True, text=True, timeout=30
                )
                # snarkjs exits with code 99 for --version (prints help + version);
                # treat any output containing "snarkjs" as success.
                combined = result.stdout + result.stderr
                first_line = combined.strip().splitlines()[0] if combined.strip() else ""
                if "snarkjs" in combined.lower():
                    print(f"snarkjs found: {first_line}")
                else:
                    print("ERROR: snarkjs is not installed.")
                    print("       Run:  npm install -g snarkjs  (or: cd ImageLevel && npm install)")
                    ok = False
            except Exception as e:
                print(f"ERROR: Could not run snarkjs: {e}")
                print("       Run:  npm install -g snarkjs  (or: cd ImageLevel && npm install)")
                ok = False

        return ok

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600) -> Tuple[bool, str, str]:
        """Run command and return success, stdout, stderr"""
        try:
            import platform
            import shutil
            
            if platform.system() == "Windows" and len(cmd) > 0 and cmd[0] == "npx":
                npx_path = shutil.which("npx.cmd") or shutil.which("npx")
                if npx_path:
                    cmd[0] = npx_path
            
            result = subprocess.run(
                cmd, 
                cwd=str(cwd) if cwd else str(self.build_dir),
                capture_output=True, 
                text=True, 
                timeout=timeout,
                shell=False
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {timeout}s"
        except Exception as e:
            return False, "", str(e)
    
    def setup_trusted_setup(self) -> bool:
        """Setup trusted setup if not already done"""
        if not self.check_prerequisites():
            print("ERROR: Missing prerequisites. ZK proof generation aborted.")
            return False

        if self.circuit_zkey.exists() and self.verification_key.exists():
            print("Trusted setup already completed")
            return True
            
        print("Starting trusted setup...")
        
        r1cs_file = self.build_dir / "chaos_zk_stego.r1cs"
        if not r1cs_file.exists():
            print(f"ERROR: R1CS file not found: {r1cs_file}")
            return False
            
        if not self.ptau_file.exists():
            print(f"ERROR: Powers of Tau not found: {self.ptau_file}")
            return False
        
        setup_cmd = [
            "npx", "snarkjs", "groth16", "setup",
            str(r1cs_file),
            str(self.ptau_file), 
            str(self.circuit_zkey)
        ]
        
        success, stdout, stderr = self.run_command(setup_cmd)
        if not success:
            print(f"ERROR: Groth16 setup failed: {stderr}")
            return False
            
        export_vk_cmd = [
            "npx", "snarkjs", "zkey", "export", "verificationkey",
            str(self.circuit_zkey), str(self.verification_key)
        ]
        
        success, stdout, stderr = self.run_command(export_vk_cmd)
        if not success:
            print(f"ERROR: Verification key export failed: {stderr}")
            return False
            
        print("Trusted setup completed successfully")
        return True
    
    def generate_witness(self, witness_input: Dict[str, Any]) -> Optional[Path]:
        """Generate witness file from input"""
        if not self.circuit_wasm.exists():
            print(f"ERROR: WASM file not found: {self.circuit_wasm}")
            return None
            
        if not self.witness_gen.exists():
            print(f"ERROR: Witness generator not found: {self.witness_gen}")
            return None
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(witness_input, f, indent=2)
            input_file = Path(f.name)
        
        witness_file = self.build_dir / f"witness_{int(time.time())}.wtns"
        
        witness_cmd = [
            "node", str(self.witness_gen.resolve()),
            str(self.circuit_wasm.resolve()),
            str(input_file.resolve()),
            str(witness_file.resolve())
        ]
        
        success, stdout, stderr = self.run_command(witness_cmd, cwd=self.build_dir / "chaos_zk_stego_js")
        input_file.unlink()
        
        if not success:
            print(f"ERROR: Witness generation failed: {stderr}")
            return None
        
        if not witness_file.exists():
            print(f"ERROR: Witness file was not created")
            return None
        
        return witness_file
    
    def generate_groth16_proof(self, witness_file: Path) -> Optional[Tuple[Dict[str, Any], List[str]]]:
        """Generate Groth16 proof from witness"""
        if not self.circuit_zkey.exists():
            print("ERROR: Circuit key not found")
            return None
        
        if not witness_file.exists():
            print(f"ERROR: Witness file not found")
            return None
            
        proof_file = self.build_dir / f"proof_{int(time.time())}.json"
        public_file = self.build_dir / f"public_{int(time.time())}.json"
        
        prove_cmd = [
            "npx", "--yes", "snarkjs", "groth16", "prove",
            str(self.circuit_zkey.resolve()),
            str(witness_file.resolve()),
            str(proof_file.resolve()),
            str(public_file.resolve())
        ]
        
        success, stdout, stderr = self.run_command(prove_cmd)
        if not success:
            print(f"ERROR: Proof generation failed: {stderr}")
            return None
        
        try:
            with open(proof_file, 'r') as f:
                proof = json.load(f)
            with open(public_file, 'r') as f:
                public_inputs = json.load(f)
                
            proof_file.unlink()
            public_file.unlink()
            witness_file.unlink()
            
            return proof, public_inputs
            
        except Exception as e:
            print(f"ERROR: Failed to read proof files: {e}")
            return None
    
    def verify_groth16_proof(self, proof: Dict[str, Any], public_inputs: List[str]) -> bool:
        """Verify Groth16 proof"""
        if not self.check_prerequisites():
            print("ERROR: Missing prerequisites. ZK proof verification aborted.")
            return False

        if not self.verification_key.exists():
            print("ERROR: Verification key not found")
            return False
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(proof, f)
            proof_file = Path(f.name)
            
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(public_inputs, f)
            public_file = Path(f.name)
        
        verify_cmd = [
            "npx", "snarkjs", "groth16", "verify",
            str(self.verification_key),
            str(public_file),
            str(proof_file)
        ]
        
        success, stdout, stderr = self.run_command(verify_cmd)
        
        proof_file.unlink()
        public_file.unlink()
        
        combined = stdout + stderr
        return success and "OK" in combined
