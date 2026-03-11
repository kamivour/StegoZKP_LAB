#!/bin/bash
# Setup script cho Verifier

echo "Setting up ZK-SNARK Steganography Verifier..."

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js not found. Please install Node.js first."
    exit 1
fi

# Check npm
if ! command -v npm &> /dev/null; then
    echo "ERROR: npm not found. Please install npm first."
    exit 1
fi

# Install snarkjs
echo "Installing snarkjs..."
npm install -g snarkjs

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3 first."
    exit 1
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

echo ""
echo "✓ Setup completed!"
echo ""
echo "You can now verify stego images with:"
echo "  python3 scripts/verify.py <stego_image.png>"
