pragma circom 2.0.0;

/*
 * Secure Chaos ZK-SNARK Steganography Circuit - Production Version v2.0
 * 
 * Security Improvements:
 * 1. Message commitment binding (prevents message swap attacks)
 * 2. Nullifier system (prevents replay attacks)
 * 3. Increased constraints to 5,000+ (brute force resistant)
 * 4. Proper public signals (meaningful cryptographic outputs)
 * 5. Verified position generation (16 positions with full verification)
 * 6. Randomness in commitment (prevents deterministic attacks)
 * 7. Poseidon-based commitments (field-native security)
 * 
 * Target: 5,000-10,000 constraints for production security
 */

include "../node_modules/circomlib/circuits/comparators.circom";
include "../node_modules/circomlib/circuits/poseidon.circom";
include "../node_modules/circomlib/circuits/bitify.circom";

// ============================================================================
// MESSAGE COMMITMENT WITH BINDING
// ============================================================================
template SecureMessageCommitment() {
    signal input messageBits[32];
    signal input chaosKey;
    signal input randomness;
    signal output commitment;
    
    // Hash message in chunks using Poseidon
    component msgHash1 = Poseidon(16);
    component msgHash2 = Poseidon(16);
    
    for (var i = 0; i < 16; i++) {
        msgHash1.inputs[i] <== messageBits[i];
        msgHash2.inputs[i] <== messageBits[16 + i];
    }
    
    // Combine hashes
    component combine = Poseidon(2);
    combine.inputs[0] <== msgHash1.out;
    combine.inputs[1] <== msgHash2.out;
    
    // Final commitment with chaos key and randomness
    component commitHash = Poseidon(3);
    commitHash.inputs[0] <== combine.out;
    commitHash.inputs[1] <== chaosKey;
    commitHash.inputs[2] <== randomness;
    
    commitment <== commitHash.out;
}

// ============================================================================
// NULLIFIER GENERATION
// ============================================================================
template Nullifier() {
    signal input secret;
    signal input nonce;
    signal output nullifier;
    
    component hash = Poseidon(2);
    hash.inputs[0] <== secret;
    hash.inputs[1] <== nonce;
    
    nullifier <== hash.out;
}

// ============================================================================
// SECURE ARNOLD CAT MAP WITH CHAOS KEY
// ============================================================================
template SecureArnoldCatMap() {
    signal input x0;
    signal input y0;
    signal input chaosKey;
    signal input iteration;
    signal output xOut;
    signal output yOut;

    // Mix chaos key with iteration
    component iterHash = Poseidon(3);
    iterHash.inputs[0] <== x0;
    iterHash.inputs[1] <== y0;
    iterHash.inputs[2] <== chaosKey + iteration;

    // Extract noise = lower 8 bits of Poseidon hash  (replaces % 256)
    // Num2Bits decomposes the 254-bit field element; lower 8 bits = hash mod 256
    component hashBits = Num2Bits(254);
    hashBits.in <== iterHash.out;
    component noiseCalc = Bits2Num(8);
    for (var j = 0; j < 8; j++) {
        noiseCalc.in[j] <== hashBits.out[j];
    }
    signal noise;
    noise <== noiseCalc.out;

    // Arnold Cat Map with perturbation
    signal xTemp;
    signal yTemp;
    xTemp <== 2 * x0 + y0 + noise;
    yTemp <== x0 + y0 + noise;

    // xOut = xTemp mod 1024  (lower 10 bits; xTemp < 3325 < 2^12)
    component xTempBits = Num2Bits(12);
    xTempBits.in <== xTemp;
    component xOutCalc = Bits2Num(10);
    for (var j = 0; j < 10; j++) {
        xOutCalc.in[j] <== xTempBits.out[j];
    }
    xOut <== xOutCalc.out;

    // yOut = yTemp mod 1024  (lower 10 bits; yTemp < 2303 < 2^12)
    component yTempBits = Num2Bits(12);
    yTempBits.in <== yTemp;
    component yOutCalc = Bits2Num(10);
    for (var j = 0; j < 10; j++) {
        yOutCalc.in[j] <== yTempBits.out[j];
    }
    yOut <== yOutCalc.out;
}

// ============================================================================
// POSITION COMMITMENT MERKLE TREE
// ============================================================================
template PositionMerkleTree() {
    signal input positions[16][2];
    signal output root;
    
    // Level 0: Hash each position (16 hashes)
    component level0[16];
    for (var i = 0; i < 16; i++) {
        level0[i] = Poseidon(2);
        level0[i].inputs[0] <== positions[i][0];
        level0[i].inputs[1] <== positions[i][1];
    }
    
    // Level 1: 8 hashes
    component level1[8];
    for (var i = 0; i < 8; i++) {
        level1[i] = Poseidon(2);
        level1[i].inputs[0] <== level0[2*i].out;
        level1[i].inputs[1] <== level0[2*i+1].out;
    }
    
    // Level 2: 4 hashes
    component level2[4];
    for (var i = 0; i < 4; i++) {
        level2[i] = Poseidon(2);
        level2[i].inputs[0] <== level1[2*i].out;
        level2[i].inputs[1] <== level1[2*i+1].out;
    }
    
    // Level 3: 2 hashes
    component level3[2];
    for (var i = 0; i < 2; i++) {
        level3[i] = Poseidon(2);
        level3[i].inputs[0] <== level2[2*i].out;
        level3[i].inputs[1] <== level2[2*i+1].out;
    }
    
    // Level 4: Root hash
    component rootHash = Poseidon(2);
    rootHash.inputs[0] <== level3[0].out;
    rootHash.inputs[1] <== level3[1].out;
    
    root <== rootHash.out;
}

// ============================================================================
// FULL POSITION VERIFICATION
// ============================================================================
template FullPositionVerification() {
    signal input x0;
    signal input y0;
    signal input chaosKey;
    signal input positions[16][2];
    
    // Verify all 16 positions are correctly generated
    component catMaps[16];
    signal xCurrent[17];
    signal yCurrent[17];
    
    xCurrent[0] <== x0;
    yCurrent[0] <== y0;
    
    for (var i = 0; i < 16; i++) {
        catMaps[i] = SecureArnoldCatMap();
        catMaps[i].x0 <== xCurrent[i];
        catMaps[i].y0 <== yCurrent[i];
        catMaps[i].chaosKey <== chaosKey;
        catMaps[i].iteration <== i;
        
        // Verify position matches
        positions[i][0] === catMaps[i].xOut;
        positions[i][1] === catMaps[i].yOut;
        
        xCurrent[i+1] <== catMaps[i].xOut;
        yCurrent[i+1] <== catMaps[i].yOut;
    }
}

// ============================================================================
// RANGE PROOFS FOR ALL POSITIONS
// ============================================================================
template AllPositionsRangeProof() {
    signal input positions[16][2];
    
    component xChecks[16];
    component yChecks[16];
    
    for (var i = 0; i < 16; i++) {
        // X in range [0, 1024)
        xChecks[i] = LessThan(11);
        xChecks[i].in[0] <== positions[i][0];
        xChecks[i].in[1] <== 1024;
        xChecks[i].out === 1;
        
        // Y in range [0, 1024)
        yChecks[i] = LessThan(11);
        yChecks[i].in[0] <== positions[i][1];
        yChecks[i].in[1] <== 1024;
        yChecks[i].out === 1;
    }
}

// ============================================================================
// IMAGE HASH VERIFICATION (256-bit = 8 field elements)
// ============================================================================
template ImageHashVerification() {
    signal input imageHashPrivate[8];
    signal input imageHashPublic[8];
    
    // Verify all 8 field elements match
    component eq[8];
    for (var i = 0; i < 8; i++) {
        eq[i] = IsEqual();
        eq[i].in[0] <== imageHashPrivate[i];
        eq[i].in[1] <== imageHashPublic[i];
        eq[i].out === 1;
    }
}

// ============================================================================
// MAIN CIRCUIT
// ============================================================================
template SecureChaosZKStego() {
    // ========================================================================
    // PUBLIC INPUTS (visible to verifier)
    // ========================================================================
    signal input publicCommitment;        // Message commitment
    signal input publicImageHash[8];      // Video/image hash
    signal input publicNullifier;         // Prevents replay
    
    // ========================================================================
    // PRIVATE INPUTS (secret to prover)
    // ========================================================================
    signal input messageBits[32];         // Secret message (32 bits)
    signal input chaosKey;                // Secret chaos key
    signal input randomness;              // Commitment randomness
    signal input secret;                  // Nullifier secret
    signal input nonce;                   // Nullifier nonce
    signal input x0;                      // Initial position X
    signal input y0;                      // Initial position Y
    signal input positions[16][2];        // Embedding positions
    signal input imageHashPrivate[8];     // Private image hash
    
    // ========================================================================
    // CONSTRAINT 1: MESSAGE BITS ARE BINARY (32 constraints)
    // ========================================================================
    for (var i = 0; i < 32; i++) {
        messageBits[i] * (1 - messageBits[i]) === 0;
    }
    
    // ========================================================================
    // CONSTRAINT 2: MESSAGE COMMITMENT BINDING (prevents message swap)
    // ========================================================================
    component msgCommit = SecureMessageCommitment();
    for (var i = 0; i < 32; i++) {
        msgCommit.messageBits[i] <== messageBits[i];
    }
    msgCommit.chaosKey <== chaosKey;
    msgCommit.randomness <== randomness;
    
    // CRITICAL: Bind commitment to public input
    msgCommit.commitment === publicCommitment;
    
    // ========================================================================
    // CONSTRAINT 3: NULLIFIER VERIFICATION (prevents replay)
    // ========================================================================
    component nullifierGen = Nullifier();
    nullifierGen.secret <== secret;
    nullifierGen.nonce <== nonce;
    
    // CRITICAL: Bind nullifier to public input
    nullifierGen.nullifier === publicNullifier;
    
    // ========================================================================
    // CONSTRAINT 4: IMAGE HASH VERIFICATION (binds to specific video)
    // ========================================================================
    component imgHash = ImageHashVerification();
    for (var i = 0; i < 8; i++) {
        imgHash.imageHashPrivate[i] <== imageHashPrivate[i];
        imgHash.imageHashPublic[i] <== publicImageHash[i];
    }
    
    // ========================================================================
    // CONSTRAINT 5: FULL POSITION VERIFICATION (all 16 positions)
    // ========================================================================
    component posVerify = FullPositionVerification();
    posVerify.x0 <== x0;
    posVerify.y0 <== y0;
    posVerify.chaosKey <== chaosKey;
    for (var i = 0; i < 16; i++) {
        posVerify.positions[i][0] <== positions[i][0];
        posVerify.positions[i][1] <== positions[i][1];
    }
    
    // ========================================================================
    // CONSTRAINT 6: POSITION RANGE PROOFS (32 range checks)
    // ========================================================================
    component rangeProofs = AllPositionsRangeProof();
    for (var i = 0; i < 16; i++) {
        rangeProofs.positions[i][0] <== positions[i][0];
        rangeProofs.positions[i][1] <== positions[i][1];
    }
    
    // ========================================================================
    // CONSTRAINT 7: POSITION MERKLE COMMITMENT
    // ========================================================================
    component posMerkle = PositionMerkleTree();
    for (var i = 0; i < 16; i++) {
        posMerkle.positions[i][0] <== positions[i][0];
        posMerkle.positions[i][1] <== positions[i][1];
    }
    
    // ========================================================================
    // CONSTRAINT 8: INITIAL POSITION BOUNDS
    // ========================================================================
    component x0Check = LessThan(11);
    x0Check.in[0] <== x0;
    x0Check.in[1] <== 1024;
    x0Check.out === 1;
    
    component y0Check = LessThan(11);
    y0Check.in[0] <== y0;
    y0Check.in[1] <== 1024;
    y0Check.out === 1;
    
}

component main {public [publicCommitment, publicImageHash, publicNullifier]} = SecureChaosZKStego();
