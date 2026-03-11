"""
Circomlib-compatible Poseidon hash for BN254.

Delegates all computation to poseidon_helper.js via Node.js so every hash
value is *identical* to what the Groth16 circuit verifier expects.

Public API
----------
poseidon_hash(inputs: List[int]) -> int
    Single Poseidon call.

compute_all_zk_params(x0, y0, chaos_key, randomness, secret, nonce,
                      message_bits) -> dict
    Compute all Poseidon-based witness parameters in ONE Node.js call:
      - 16 SecureArnoldCatMap positions
      - publicCommitment  (SecureMessageCommitment template)
      - publicNullifier   (Nullifier template)
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _find_helper_js() -> Path:
    """Locate poseidon_helper.js by walking up from this file."""
    current = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = current / "poseidon_helper.js"
        if candidate.exists():
            return candidate
        current = current.parent
    raise RuntimeError(
        "poseidon_helper.js not found. "
        "Make sure you are running from the ImageLevel project directory."
    )


_HELPER_JS: Path = _find_helper_js()


def _run_helper(task: Dict[str, Any]) -> Any:
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "Node.js is not installed or not in PATH. "
            "Install from https://nodejs.org/ and re-run."
        )
    result = subprocess.run(
        [node, str(_HELPER_JS), json.dumps(task)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"poseidon_helper.js failed:\n{result.stderr.strip()}"
        )
    return json.loads(result.stdout.strip())


def poseidon_hash(inputs: List[int]) -> int:
    """Compute a single Poseidon hash (circomlib BN254-compatible)."""
    results = _run_helper({"type": "batch", "inputs": [inputs]})
    return int(results[0])


def compute_all_zk_params(
    x0: int,
    y0: int,
    chaos_key: int,
    randomness: int,
    secret: int,
    nonce: int,
    message_bits: List[int],
) -> Dict[str, Any]:
    """
    Compute all Poseidon-based ZK witness parameters in one Node.js call.

    Mirrors the following circuit templates exactly:
      - SecureArnoldCatMap        (16 iterations → 16 positions)
      - SecureMessageCommitment   (→ publicCommitment)
      - Nullifier                 (→ publicNullifier)

    Parameters
    ----------
    x0, y0       : Starting position (feature point from image).
    chaos_key    : Numeric chaos key (BN254 field element).
    randomness   : Blinding factor for commitment (BN254 field element).
    secret       : Nullifier secret (BN254 field element).
    nonce        : Nullifier nonce (BN254 field element).
    message_bits : Exactly 32 message bits [0/1].

    Returns
    -------
    {
        "positions":         List[Tuple[int, int]],  # 16 pairs
        "public_commitment": int,
        "public_nullifier":  int,
    }
    """
    task = {
        "type": "compute_all",
        "x0": x0,
        "y0": y0,
        "chaos_key": str(chaos_key),
        "randomness": str(randomness),
        "secret": str(secret),
        "nonce": str(nonce),
        "message_bits": message_bits,
    }
    raw = _run_helper(task)
    return {
        "positions":         [(int(p[0]), int(p[1])) for p in raw["positions"]],
        "public_commitment": int(raw["public_commitment"]),
        "public_nullifier":  int(raw["public_nullifier"]),
    }
