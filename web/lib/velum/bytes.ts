/** Byte helpers shared by every velum-js module. No dependencies. */

const HEX = '0123456789abcdef'

/** Lowercase hex, as VELUM writes hashes and signatures. */
export function toHex(bytes: Uint8Array): string {
  let out = ''
  for (const b of bytes) out += HEX[b >> 4]! + HEX[b & 15]!
  return out
}

/** Parse hex (either case). Throws on odd length or a non-hex character. */
export function fromHex(hex: string): Uint8Array {
  if (hex.length % 2 !== 0 || !/^[0-9a-fA-F]*$/.test(hex)) throw new Error('invalid hex')
  const out = new Uint8Array(hex.length / 2)
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(2 * i, 2 * i + 2), 16)
  return out
}

/** ASCII string to bytes. Throws on any code point above 0x7F. */
export function ascii(text: string): Uint8Array {
  const out = new Uint8Array(text.length)
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i)
    if (c > 0x7f) throw new Error('non-ASCII character')
    out[i] = c
  }
  return out
}

/** i as 4 bytes, big-endian. */
export function u32be(i: number): Uint8Array {
  if (!Number.isInteger(i) || i < 0 || i > 0xffffffff) throw new RangeError('u32 out of range')
  return new Uint8Array([i >>> 24, (i >>> 16) & 255, (i >>> 8) & 255, i & 255])
}

export function concat(...parts: Uint8Array[]): Uint8Array {
  let n = 0
  for (const p of parts) n += p.length
  const out = new Uint8Array(n)
  let pos = 0
  for (const p of parts) {
    out.set(p, pos)
    pos += p.length
  }
  return out
}

export function equal(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!
  return diff === 0
}

/** Python's `a // b` on integers: floors toward -infinity (Math.trunc does not). */
export function floorDiv(a: number, b: number): number {
  if (!Number.isSafeInteger(a) || !Number.isSafeInteger(b) || b === 0) throw new RangeError('floorDiv needs safe integers, b != 0')
  return Math.floor(a / b)
}
