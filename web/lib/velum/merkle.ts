/**
 * RFC 6962 Merkle Tree Hash over leaf hashes (VELUM.md section 4). Mirrors velum/src/velum/merkle.py.
 * The input is the list of *leaf hashes*; they are never hashed again, so a hidden tile contributes
 * exactly the 32 bytes found in the sidecar.
 *
 *   MTH(one leaf) = that leaf
 *   MTH(n > 1)    = SHA256(0x01 || MTH(first k) || MTH(the other n - k)), k = largest power of 2 < n
 */
import { sha256 } from './hash'

const NODE_PREFIX = new Uint8Array([0x01])

export function merkleRoot(leaves: readonly Uint8Array[]): Uint8Array {
  if (leaves.length === 0) throw new RangeError('a Merkle tree needs at least one leaf')
  if (leaves.some((l) => l.length !== 32)) throw new RangeError('every leaf hash must be 32 bytes')
  return mth(leaves, 0, leaves.length)
}

function mth(leaves: readonly Uint8Array[], start: number, end: number): Uint8Array {
  const n = end - start
  if (n === 1) return leaves[start]!
  let k = 1
  while (k * 2 < n) k *= 2 // largest power of two strictly smaller than n
  return sha256(NODE_PREFIX, mth(leaves, start, start + k), mth(leaves, start + k, end))
}
