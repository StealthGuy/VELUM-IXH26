/** SHA-256 and HMAC-SHA256, synchronous (@noble/hashes), so they run the same in a Worker. */
import { hmac } from '@noble/hashes/hmac.js'
import { sha256 as nobleSha256 } from '@noble/hashes/sha2.js'

export function sha256(...parts: Uint8Array[]): Uint8Array {
  const h = nobleSha256.create()
  for (const p of parts) h.update(p)
  return h.digest()
}

export function hmacSha256(key: Uint8Array, msg: Uint8Array): Uint8Array {
  return hmac(nobleSha256, key, msg)
}
