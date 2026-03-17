# ZK System Metrics — chaos_zk_stego (Groth16 / BN254)

## Circuit

| Property | Value |
|---|---|
| Circuit file | `circuits/source/chaos_zk_stego.circom` |
| Constraint count | 18,429 |
| Trusted setup file | `artifacts/keys/pot16_final.ptau` |
| Setup level | pot16 — supports up to 2^16 = 65,536 constraints |
| Setup utilisation | 18,429 / 65,536 = **28.1 %** |

> To verify constraint count: `snarkjs r1cs info circuits/compiled/build/chaos_zk_stego.r1cs`

---

## Public Signals

| Signal | Type | Purpose |
|---|---|---|
| `publicCommitment` | field element | Poseidon(messageBits[32], chaosKey, randomness) — binds the 32-bit message and key to the proof |
| `publicImageHash[8]` | 8 × field element | SHA-256 of the cover image split into 8 BN254 field elements — ties the proof to a specific image |
| `publicNullifier` | field element | Poseidon(secret, nonce) — prevents proof replay attacks |

---

## Private Signals

| Signal | Size | Purpose |
|---|---|---|
| `messageBits[32]` | 32 bits | 32-bit payload (SHA-256 fingerprint of DICOM metadata) |
| `chaosKey` | 1 field element | Secret key used to derive embedding positions |
| `randomness` | 1 field element | Blinding factor for the message commitment |
| `secret` | 1 field element | Nullifier secret (prevents key reuse attacks) |
| `nonce` | 1 field element | Nullifier nonce |
| `x0`, `y0` | 2 field elements | Starting pixel coordinates for chaos trajectory |
| `positions[16][2]` | 32 field elements | The 16 embedding pixel coordinates proven by the circuit |
| `imageHashPrivate[8]` | 8 field elements | Private copy of image hash (equality-checked against public hash) |

---

## Constraint Breakdown

| Template | Constraints (est.) | Purpose |
|---|---|---|
| `messageBits[i] * (1 - messageBits[i]) === 0` | 32 | Each of 32 message bits is in {0, 1} |
| `SecureMessageCommitment` (Poseidon) | ~250 | Binding: commitment = Poseidon(messageBits, chaosKey, randomness) |
| `Nullifier` (Poseidon) | ~250 | Replay prevention: nullifier = Poseidon(secret, nonce) |
| `ImageHashVerification` (IsEqual × 8) | 8 | imageHashPrivate == publicImageHash for each of 8 elements |
| `FullPositionVerification` (16 × SecureArnoldCatMap) | ~16,000 | All 16 positions correctly derived by ACM from (x0, y0, chaosKey) |
| `AllPositionsRangeProof` (32 × LessThan(11)) | ~640 | Every position (x, y) ∈ [0, 1024) |
| `PositionMerkleTree` (31 × Poseidon) | ~1,250 | Merkle root commitment over all 16 positions |
| Initial position bounds (2 × LessThan) | 2 | x0, y0 ∈ [0, 1024) |
| **Total** | **~18,432** | *(exact count: `snarkjs r1cs info`)* |

---

## Build Artifacts

| File | Size | Description |
|---|---|---|
| `circuits/compiled/build/chaos_zk_stego.r1cs` | 7.8 MB | Rank-1 Constraint System (compiled circuit) |
| `circuits/compiled/build/chaos_zk_stego.sym` | 3.1 MB | Symbol map (constraint → variable names, for debugging) |
| `circuits/compiled/build/chaos_zk_stego.zkey` | 12 MB | Groth16 proving key (required to generate proofs) |
| `circuits/compiled/build/chaos_zk_stego_verification_key.json` | 4.5 KB | Groth16 verification key (public — safe to distribute) |
| `circuits/compiled/build/chaos_zk_stego_js/chaos_zk_stego.wasm` | — | Circuit compiled to WebAssembly (witness generation) |
| `artifacts/keys/pot16_final.ptau` | 73 MB | Powers of Tau ceremony file (trusted setup phase 1) |
| `artifacts/keys/pot12_final.ptau` | 4.6 MB | Smaller ceremony file (for circuits ≤ 4,096 constraints) |

---

## Per-Proof Artifacts

| Artifact | Size | Contents |
|---|---|---|
| `proof.json` | ~1.1 KB | Groth16 proof: three elliptic curve points (pi_a, pi_b, pi_c) |
| `public.json` | ~830 B | Public signals: publicCommitment, publicImageHash[8], publicNullifier |
| **Total embedded in stego image** | **~1.93 KB** | Stored in LSBs of border-zone pixels via proof_key region |

---

## Verification Performance

| Metric | Value |
|---|---|
| Verification input | `verification_key.json` (4.5 KB) + `proof.json` + `public.json` |
| Verification algorithm | Groth16: 3 BN254 pairing operations + scalar multiplications |
| Verification time (measured) | ~1–3 ms on x86-64 desktop via snarkjs |
| Proving key required | **No** — only `verification_key.json` needed |
| WASM required | **No** — only `verification_key.json` needed |

---

## ZK Coverage in This System

The circuit proves:
- The prover knew a secret `chaosKey` such that Arnold Cat Map (16 iterations) correctly
  derives 16 specific embedding positions.
- Those positions are within image bounds [0, 1024).
- The 32-bit message (SHA-256 fingerprint of compressed metadata) was committed correctly.
- The proof is bound to a specific image via SHA-256 hash.
- The nullifier prevents replay of the same proof with a different image.

The circuit does **not** prove full metadata content (too large for pot16). Full payload
integrity is provided by SHA-256(gzip(metadata)) stored in the 84-byte header, which is
covered by the embedding process and verified on extraction.
