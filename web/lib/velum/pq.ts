/** ML-DSA-44 (FIPS 204) verification with a context string. Mirrors velum/src/velum/pq.py (verify side). */
import { ml_dsa44 } from '@noble/post-quantum/ml-dsa.js'
import { ascii, toHex } from './bytes'
import { sha256 } from './hash'

export const ALG = 'ML-DSA-44'
export const PK_BYTES = 1312
export const SIG_BYTES = 2420
export const MANIFEST_CTX = ascii('VELUM/manifest/v1')

/** True only for a valid signature; malformed inputs are simply false. */
export function verify(pk: Uint8Array, message: Uint8Array, sig: Uint8Array, ctx: Uint8Array): boolean {
  if (pk.length !== PK_BYTES || sig.length !== SIG_BYTES) return false
  try {
    // noble's argument order is (signature, message, publicKey); unknown option keys throw
    return ml_dsa44.verify(sig, message, pk, { context: ctx })
  } catch {
    return false
  }
}

/** SHA256(pk) in lowercase hex: the value a trust list pins. */
export function fingerprint(pk: Uint8Array): string {
  return toHex(sha256(pk))
}
