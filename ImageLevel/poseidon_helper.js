#!/usr/bin/env node
/**
 * poseidon_helper.js
 *
 * Batch Poseidon computation for the ZK-SNARK steganography Python prover.
 * Uses circomlibjs so all hash values exactly match what the Groth16 circuit
 * verifier expects (same library, same BN254 constants).
 *
 * Input  (argv[2]): JSON task object
 * Output (stdout):  JSON result
 *
 * Task types:
 *
 * 1. Simple batch
 *    { type: "batch", inputs: [["a","b"], ["c","d","e"], ...] }
 *    → JSON array of result strings
 *
 * 2. Full witness parameter computation
 *    {
 *      type:         "compute_all",
 *      x0:           <number>,
 *      y0:           <number>,
 *      chaos_key:    "<decimal string>",
 *      randomness:   "<decimal string>",
 *      secret:       "<decimal string>",
 *      nonce:        "<decimal string>",
 *      message_bits: [0, 1, 1, 0, ...]   // exactly 32 elements
 *    }
 *    → {
 *        positions:         [["x1","y1"], ["x2","y2"], ...],  // 16 pairs
 *        public_commitment: "<decimal string>",
 *        public_nullifier:  "<decimal string>"
 *      }
 *
 * All large integers are passed and returned as decimal strings to avoid
 * JS Number precision loss.
 */

const { buildPoseidon } = require('circomlibjs');

const BN254_P = BigInt(
  '21888242871839275222246405745257275088548364400416034343698204186575808495617'
);

async function main() {
  const task = JSON.parse(process.argv[2]);
  const poseidon = await buildPoseidon();
  const F = poseidon.F;

  /** Compute Poseidon hash of an array of BigInt-convertible inputs. */
  function hash(inputs) {
    const bigInputs = inputs.map(x => BigInt(x.toString()));
    return BigInt(F.toString(poseidon(bigInputs)));
  }

  // ── Task: batch ─────────────────────────────────────────────────────────
  if (task.type === 'batch') {
    const results = task.inputs.map(inputs => hash(inputs).toString());
    process.stdout.write(JSON.stringify(results) + '\n');
    return;
  }

  // ── Task: compute_all ───────────────────────────────────────────────────
  if (task.type === 'compute_all') {
    const x0        = BigInt(task.x0);
    const y0        = BigInt(task.y0);
    const chaosKey  = BigInt(task.chaos_key);
    const randomness = BigInt(task.randomness);
    const secret    = BigInt(task.secret);
    const nonce     = BigInt(task.nonce);
    const messageBits = task.message_bits.map(b => BigInt(b));

    // 1. SecureArnoldCatMap – 16 iterations
    //    noise = Poseidon(x, y, chaosKey + i) % 256
    //    xNew  = (2*x + y + noise) % 1024
    //    yNew  = (x + y + noise) % 1024
    const positions = [];
    let cx = x0, cy = y0;
    for (let i = 0; i < 16; i++) {
      const iterInput = (chaosKey + BigInt(i)) % BN254_P;
      const noiseHash = hash([cx, cy, iterInput]);
      const noise     = noiseHash % 256n;
      const xNew      = (2n * cx + cy + noise) % 1024n;
      const yNew      = (cx + cy + noise) % 1024n;
      cx = xNew;
      cy = yNew;
      positions.push([cx.toString(), cy.toString()]);
    }

    // 2. SecureMessageCommitment
    //    msgHash1   = Poseidon(messageBits[0..15])
    //    msgHash2   = Poseidon(messageBits[16..31])
    //    combine    = Poseidon([msgHash1, msgHash2])
    //    commitment = Poseidon([combine, chaosKey, randomness])
    const msgHash1         = hash(messageBits.slice(0, 16));
    const msgHash2         = hash(messageBits.slice(16, 32));
    const combine          = hash([msgHash1, msgHash2]);
    const publicCommitment = hash([combine, chaosKey, randomness]);

    // 3. Nullifier
    //    nullifier = Poseidon([secret, nonce])
    const publicNullifier = hash([secret, nonce]);

    process.stdout.write(
      JSON.stringify({
        positions:         positions,
        public_commitment: publicCommitment.toString(),
        public_nullifier:  publicNullifier.toString(),
      }) + '\n'
    );
    return;
  }

  throw new Error('Unknown task type: ' + task.type);
}

main().catch(err => {
  process.stderr.write(err.toString() + '\n');
  process.exit(1);
});
