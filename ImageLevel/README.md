# ZK-SNARK Steganography System

A steganography system using ZK-SNARK (Zero-Knowledge Succinct Non-Interactive Argument of Knowledge) to prove message embedding without revealing the secret content.

## Overview

This system combines three core technologies:
1. **Chaos-based Steganography**: Uses chaos theory (Arnold Cat Map + Logistic Map) to generate secure embedding positions
2. **ZK-SNARK Proofs**: Mathematical proofs that don't reveal information
3. **Hybrid Embedding**: Combines PNG chunk metadata and LSB embedding

## System Architecture

```
ZK-SNARK Steganography System
├── ZK Circuit Layer (chaos_zk_stego.circom)
│   ├── 32 optimized constraints
│   ├── Arnold Cat Map verification
│   └── Groth16 proof system
├── ZK Proof Layer (zk_proof_generator.py)
│   ├── Automatic witness generation
│   ├── Trusted setup management
│   └── Proof generation and verification
├── Steganography Layer (chaos_embedding.py)
│   ├── Arnold Cat Map for positions
│   ├── Logistic Map for randomness
│   └── LSB embedding with chaos
└── Integration Layer (hybrid_proof_artifact.py)
    ├── PNG chunk metadata
    ├── Chaos-based LSB embedding
    └── ZK proof integration
```

## Core Components

### 1. Chaos Embedding (`src/zk_stego/chaos_embedding.py`)
- **Arnold Cat Map**: Generates embedding positions using chaotic transformation
- **Logistic Map**: Creates random sequences for bit ordering
- **LSB Embedding**: Embeds bits in least significant bits of pixels

### 2. ZK Proof Generator (`src/zk_stego/zk_proof_generator.py`)
- Manages trusted setup (Powers of Tau)
- Generates witnesses from chaos parameters
- Creates and verifies Groth16 ZK-SNARK proofs

### 3. Hybrid Proof Artifact (`src/zk_stego/hybrid_proof_artifact.py`)
- Integrates steganography with ZK proofs
- Handles PNG chunk metadata
- Provides high-level API for embedding and verification

### 4. ZK Circuit (`circuits/source/chaos_zk_stego.circom`)
- Defines constraints for chaos parameter verification
- Validates Arnold Cat Map transformations
- Ensures position commitment correctness

## Installation

### Requirements

```bash
# Node.js and snarkjs (for ZK-SNARK operations)
npm install -g snarkjs

# Python packages
pip install pillow numpy

# Circom compiler (Windows: bin/circom.exe)
```

### Setup

1. **Compile Circuit** (if not already compiled):
```bash
cd circuits/source
circom chaos_zk_stego.circom --r1cs --wasm --sym -o ../compiled/build/
```

2. **Trusted Setup** (automatically handled by system):
```python
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent / 'src'))

from zk_stego.zk_proof_generator import ZKProofGenerator
zk = ZKProofGenerator()
zk.setup_trusted_setup()
```

## Usage

### Basic Embedding with ZK Proof

```python
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent / 'src'))

from zk_stego.hybrid_proof_artifact import HybridProofArtifact
import numpy as np
from PIL import Image

# Load cover image
image = Image.open("examples/testvectors/Lenna_test_image.webp")
image_array = np.array(image)

# Initialize system
hybrid = HybridProofArtifact()

# Embed message with ZK proof
message = "Secret message to embed"
stego_result = hybrid.embed_with_proof(
    image_array, 
    message, 
    x0=100,      # Optional: starting X position
    y0=100,      # Optional: starting Y position
    chaos_key="my_secret_key"
)

if stego_result:
    stego_image, proof_package = stego_result
    print("✓ Embedding successful!")
    print(f"✓ ZK Proof generated: {len(str(proof_package))} bytes")
    
    # Save stego image
    stego_image.save("stego.png")
```

### Verify ZK Proof

```python
# Verify proof from stego image
verification_result = hybrid.verify_proof(proof_package)

if verification_result:
    print("✓ ZK Proof verification PASSED")
    print("✓ Message was authentically embedded")
else:
    print("✗ ZK Proof verification FAILED")
```

### Command Line Verification

```bash
python scripts/verify.py stego_image.png
```

## Project Structure

```
zk-snark-X-Steganography/
├── src/zk_stego/              # Core Python implementation
│   ├── chaos_embedding.py     # Chaos-based steganography
│   ├── zk_proof_generator.py  # ZK-SNARK proof system
│   ├── hybrid_proof_artifact.py # Integration layer
│   └── metadata_message_generator.py # Metadata utilities
├── circuits/
│   ├── source/
│   │   └── chaos_zk_stego.circom # ZK circuit definition
│   └── compiled/build/         # Compiled artifacts
├── scripts/
│   └── verify.py              # Verification tool
├── artifacts/keys/            # Cryptographic keys
├── examples/testvectors/      # Test images
└── README.md                  # This file
```

## Key Features

### Zero-Knowledge Properties
- **Completeness**: Valid proofs always verify
- **Soundness**: Invalid proofs fail with high probability
- **Zero-Knowledge**: Proofs don't reveal message content

### Chaos-Based Security
- **Arnold Cat Map**: Ergodicity ensures uniform position distribution
- **Logistic Map**: High entropy for secure randomness
- **Feature-based initialization**: Uses image features as seed

### Performance
- **Proof Generation**: ~2.3 seconds
- **Proof Verification**: ~0.5 seconds
- **Embedding Speed**: <0.01 seconds
- **Proof Size**: 739 bytes (constant)

## Algorithm Details

### Arnold Cat Map
```
[x_new]   [2 1] [x_old]
[y_new] = [1 1] [y_old] (mod N)
```

Properties:
- Ergodicity: Uniform distribution over image
- Deterministic: Same seed → same sequence
- Unpredictable: Hard to predict next position

### Logistic Map
```
x_{n+1} = r × x_n × (1 - x_n)
```

Parameters:
- r = 3.9 (chaotic regime)
- x₀ from message hash

### LSB Embedding
```python
# Embed bit at position (x, y)
pixel_value = image[y, x, channel]
new_value = (pixel_value & 0xFE) | bit
image[y, x, channel] = new_value
```

## Security

- **Security Level**: 128-bit (equivalent to AES-128)
- **Proof System**: Groth16 ZK-SNARK
- **Trusted Setup**: Powers of Tau ceremony
- **Chaos Security**: 2^256 search space (SHA-256 based keys)

## License

MIT License

## References

- Groth16: "On the Size of Pairing-based Non-interactive Arguments" (2016)
- Arnold Cat Map: Chaos theory applications in cryptography
- Steganography: LSB embedding techniques

---

**Built with ZK-SNARK technology for privacy-preserving steganography**

*"Prove you embedded the message without revealing what you embedded"*
